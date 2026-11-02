"""区分编码角色的有界同步 Embedding 批处理，支持持久化请求身份。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import random
import time
from typing import Callable, Sequence
import uuid

from .contracts import EmbeddingAdapter, EmbeddingContractError, IndexSchemeVersion, content_fingerprint
from .requests import BatchRequest, ProviderError, ProviderOutcome, RequestState, UnknownResolution, classify_provider_error
from .scheduling import LocalRateLimiter, QuotaCapacityExceeded, QuotaWaitExceeded, WaitBudget, shared_limiter, _positive_integer, _seconds


@dataclass(frozen=True)
class LongInputPolicy:
    mode: str = "reject"
    policy_id: str = ""
    transform: Callable[[str, str], Sequence[str]] | None = None

    def __post_init__(self):
        if self.mode not in {"reject", "truncate", "rechunk"}:
            raise ValueError("long input mode must be reject, truncate or rechunk")
        if self.mode != "reject" and (not self.policy_id or not callable(self.transform)):
            raise ValueError("truncate/rechunk require an explicit policy_id and transformation handler")


@dataclass(frozen=True)
class PreparedInput:
    parent_index: int
    text: str
    version_suffix: str | None = None
    diagnostics: tuple[str, ...] = ()
    rejected_reason: str | None = None


@dataclass(frozen=True)
class EmbeddedItem:
    key: str
    text: str
    status: str
    vector: tuple[float, ...] | None = None
    error_code: str | None = None
    reason: str | None = None
    retry_count: int = 0
    updated_at: datetime | None = None
    content_fingerprint: str | None = None
    fingerprint_algorithm: str | None = None
    role: str = "document"
    request_id: str | None = None
    next_retry_at: datetime | None = None
    idempotency_key: str | None = None
    attempt_count: int = 0
    request: BatchRequest | None = None
    diagnostics: tuple[str, ...] = ()
    version_suffix: str | None = None


@dataclass(frozen=True)
class EmbeddingBatchResult:
    items: tuple[EmbeddedItem, ...]


def _prepared_text(adapter, text, role):
    expected = adapter.metadata.role_config(role).instruction + text
    prepare = getattr(adapter, "prepare_text", None)
    actual = prepare(text, role) if prepare else expected
    if actual != expected:
        raise EmbeddingContractError("adapter preparation differs from the declared role input; transform text into an explicit revision first")
    return actual


def _count_tokens(counter, text):
    if counter is None:
        return 0
    count = counter(text)
    if isinstance(count, bool):
        raise ValueError("token counter must return a nonnegative integer or token sequence")
    if not isinstance(count, int):
        if not isinstance(count, Sequence) or isinstance(count, (str, bytes)):
            raise ValueError("token counter must return a nonnegative integer or token sequence")
        count = len(count)
    if count < 0:
        raise ValueError("token counter must return a nonnegative integer or token sequence")
    return count


def prepare_long_inputs(texts: Sequence[str], adapter: EmbeddingAdapter, *, max_tokens: int | None,
                        token_counter=None, role="document", policy: LongInputPolicy | None = None) -> tuple[PreparedInput, ...]:
    """先显式转换文本，再由流程创建新的 Chunk 修订；不修改源身份。"""
    role_config = adapter.metadata.role_config(role)
    if max_tokens is not None:
        _positive_integer(max_tokens, "max_tokens")
    selected = policy or LongInputPolicy()
    if not isinstance(selected, LongInputPolicy):
        raise ValueError("policy must be a LongInputPolicy")
    if selected.mode != "reject" and (role_config.tokenizer_policy == "identity"
            or selected.policy_id != role_config.tokenizer_policy):
        raise EmbeddingContractError("transformation policy_id must match the role's explicit non-identity tokenizer_policy")
    counter = token_counter or getattr(adapter, "token_counter", None)
    if max_tokens is not None and counter is None:
        raise ValueError("a token counter is required when max_tokens is set")
    prepared = []
    for index, text in enumerate(texts):
        if not isinstance(text, str):
            raise ValueError("embedding inputs must be strings")
        count = _count_tokens(counter, _prepared_text(adapter, text, role))
        if max_tokens is None or count <= max_tokens:
            prepared.append(PreparedInput(index, text))
            continue
        diagnostic = f"input uses {count} prepared tokens; limit is {max_tokens}"
        if selected.mode == "reject":
            prepared.append(PreparedInput(index, text, diagnostics=(diagnostic,), rejected_reason=diagnostic))
            continue
        transformed = selected.transform(text, selected.mode)
        if isinstance(transformed, (str, bytes)) or not isinstance(transformed, Sequence) or not transformed:
            raise ValueError("transformation handler must return a nonempty sequence of texts")
        if selected.mode == "truncate" and len(transformed) != 1:
            raise ValueError("truncate must return exactly one text")
        for child_index, child in enumerate(transformed):
            if not isinstance(child, str):
                raise ValueError("transformation handler must return texts")
            child_count = _count_tokens(counter, _prepared_text(adapter, child, role))
            if child_count > max_tokens:
                raise ValueError("transformation handler output still exceeds the prepared token limit")
            payload = json.dumps([selected.policy_id, selected.mode, child_index, child], ensure_ascii=False)
            suffix = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
            prepared.append(PreparedInput(index, child, suffix, (diagnostic, f"{selected.mode} policy {selected.policy_id}; new chunk revision required")))
    return tuple(prepared)


def validate_query_vector(vector: Sequence[float], adapter: EmbeddingAdapter) -> tuple[float, ...]:
    return _validate_vector(vector, adapter)


def _validate_vector(vector: Sequence[float], adapter: EmbeddingAdapter) -> tuple[float, ...]:
    if len(vector) != adapter.metadata.dimensions:
        raise EmbeddingContractError(f"vector dimension {len(vector)} does not match declared dimension {adapter.metadata.dimensions}")
    if any(isinstance(value, (bool, str, bytes)) for value in vector):
        raise EmbeddingContractError("vector values must be numeric")
    values = tuple(float(value) for value in vector)
    if not all(math.isfinite(value) for value in values):
        raise EmbeddingContractError("vector values must be finite")
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude == 0:
        raise EmbeddingContractError("vector must be nonzero for cosine search")
    if adapter.metadata.normalization == "unit" and abs(magnitude - 1.0) > 1e-6:
        raise EmbeddingContractError("vector does not satisfy unit normalization policy")
    return values


def _request(items, adapter, scheme, role):
    texts = tuple(item.text for item in items)
    keys = tuple(item.key for item in items)
    fingerprints = tuple(item.content_fingerprint for item in items)
    payload = json.dumps([scheme.identity, role, keys, fingerprints], separators=(",", ":"))
    return BatchRequest(str(uuid.uuid4()), hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        keys, texts, tuple(_prepared_text(adapter, text, role) for text in texts), role,
        fingerprints, items[0].fingerprint_algorithm, scheme.identity)


def _backoff(attempt, base, maximum, jitter, retry_after=None):
    # 先限制指数范围，避免过大的重试配置导致幂运算溢出。
    exponential = min(maximum, base * 2 ** min(attempt, 60))
    sample = jitter()
    if not isinstance(sample, (int, float)) or not math.isfinite(sample):
        raise ValueError("jitter must return a finite number")
    delay = exponential * max(0.0, min(1.0, sample))
    if retry_after is not None:
        _seconds(retry_after, "retry_after_seconds")
        delay = max(delay, retry_after)
    return delay


def embed_texts(
    texts: Sequence[str], adapter: EmbeddingAdapter, *, max_batch_size: int = 64,
    max_tokens: int | None = None, token_counter=None,
    scheme: IndexSchemeVersion | None = None, role: str = "document",
    request_budget: int | None = None, token_budget: int | None = None,
    max_wait_seconds: float = 30, clock=time.monotonic, sleeper=time.sleep,
    max_retries: int = 2, base_backoff_seconds: float = 0.25,
    max_backoff_seconds: float = 8, jitter=random.random,
    rate_window_seconds: float = 1, max_concurrency: int = 1,
    limiter: LocalRateLimiter | None = None, keys: Sequence[str] | None = None,
    long_input_policy: LongInputPolicy | None = None,
    before_request: Callable[[BatchRequest, int], None] | None = None,
    after_batch: Callable[[EmbeddingBatchResult], None] | None = None,
    prepared_inputs: Sequence[PreparedInput] | None = None,
    remaining=None,
) -> EmbeddingBatchResult:
    if remaining is not None:
        remaining.check()
        if not getattr(adapter, "supports_deadline", False):
            raise EmbeddingContractError("adapter does not support a retrieval deadline")
    _positive_integer(max_batch_size, "max_batch_size")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ValueError("max_retries must be a nonnegative integer")
    for value, name in ((max_wait_seconds, "max_wait_seconds"), (base_backoff_seconds, "base_backoff_seconds"), (max_backoff_seconds, "max_backoff_seconds")):
        _seconds(value, name)
    _positive_integer(request_budget, "request_budget", optional=True)
    _positive_integer(token_budget, "token_budget", optional=True)
    selected = scheme or IndexSchemeVersion(adapter.metadata)
    adapter.validate_scheme(selected)
    if long_input_policy is not None and long_input_policy.mode == "rechunk":
        raise ValueError("rechunk requires prepare_long_inputs and explicit new Chunk revisions in flow")
    item_keys = list(keys) if keys is not None else [str(index) for index in range(len(texts))]
    if len(item_keys) != len(texts) or len(set(item_keys)) != len(item_keys) or any(not isinstance(key, str) or not key for key in item_keys):
        raise ValueError("keys must be unique nonempty strings, one for each input")
    local = limiter or shared_limiter(adapter, request_budget=request_budget, token_budget=token_budget,
        window_seconds=rate_window_seconds, max_concurrency=max_concurrency, clock=clock, sleeper=sleeper)
    counter = token_counter or getattr(adapter, "token_counter", None)
    if local.token_budget is not None and counter is None:
        raise ValueError("a token counter is required for a token quota")
    limits = [limit for limit in (max_tokens, local.token_budget) if limit is not None]
    item_limit = min(limits) if limits else None
    if prepared_inputs is not None:
        if long_input_policy is not None:
            raise ValueError("prepared_inputs cannot be combined with a transformation policy")
        prepared = tuple(prepared_inputs)
        if len(prepared) != len(texts) or any(not isinstance(entry, PreparedInput) or entry.text != text for entry, text in zip(prepared, texts)):
            raise ValueError("prepared_inputs must match the final texts one to one")
        # 仅重新检查最终准备文本的 Token 上限，并保留转换诊断。
        checked = prepare_long_inputs(texts, adapter, max_tokens=item_limit, token_counter=counter, role=role)
        prepared = tuple(replace(entry, rejected_reason=entry.rejected_reason or check.rejected_reason,
            diagnostics=entry.diagnostics + check.diagnostics) for entry, check in zip(prepared, checked))
    else:
        prepared = prepare_long_inputs(texts, adapter, max_tokens=item_limit, token_counter=counter, role=role, policy=long_input_policy)
    staged = []
    counts = []
    for index, entry in enumerate(prepared):
        algorithm, fingerprint = content_fingerprint(entry.text, adapter.metadata, role)
        staged.append(EmbeddedItem(item_keys[index], entry.text, "failed" if entry.rejected_reason else "pending",
            error_code="ITEM_EXCEEDS_TOKEN_BUDGET" if entry.rejected_reason else None,
            reason=entry.rejected_reason, role=role, content_fingerprint=fingerprint,
            fingerprint_algorithm=algorithm, updated_at=datetime.now(timezone.utc),
            diagnostics=entry.diagnostics, version_suffix=entry.version_suffix))
        counts.append(_count_tokens(counter, _prepared_text(adapter, entry.text, role)))
    batches, current, current_tokens = [], [], 0
    for index, item in enumerate(staged):
        if item.status != "pending":
            continue
        if current and (len(current) >= max_batch_size or (item_limit is not None and current_tokens + counts[index] > item_limit)):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(index)
        current_tokens += counts[index]
    if current:
        batches.append(current)
    for indexes in batches:
        request = _request([staged[index] for index in indexes], adapter, selected, role)
        attempts = 0
        waiting = WaitBudget(max_wait_seconds, local.clock, local.sleeper, deadline=remaining)
        error = None
        vectors = None
        while True:
            if remaining is not None:
                remaining.check()
            try:
                local.acquire(sum(counts[index] for index in indexes), wait_budget=waiting)
            except (QuotaWaitExceeded, QuotaCapacityExceeded) as failure:
                error = ProviderError(ProviderOutcome.RETRYABLE if isinstance(failure, QuotaWaitExceeded) else ProviderOutcome.FAILED,
                    "RATE_LIMITED" if isinstance(failure, QuotaWaitExceeded) else "BATCH_EXCEEDS_TOKEN_BUDGET", str(failure))
                break
            if before_request is not None:
                try:
                    before_request(request, attempts)
                except Exception:
                    local.release()
                    raise
            try:
                attempts += 1
                if remaining is not None:
                    remaining.check()
                budget_options = {"remaining": remaining} if remaining is not None else {}
                if getattr(adapter, "supports_request_metadata", False):
                    vectors = adapter.embed_request(request, **budget_options)
                else:
                    vectors = adapter.embed_role(request.texts, role, **budget_options)
                if remaining is not None:
                    remaining.check()
                if len(vectors) != len(indexes):
                    raise EmbeddingContractError("adapter returned a different number of vectors than inputs")
                error = None
            except Exception as failure:
                vectors = None
                # 提供方不能将契约错误重新归类为暂时性故障。
                error = (ProviderError(ProviderOutcome.FAILED, "EMBEDDING_CONTRACT", str(failure))
                    if isinstance(failure, EmbeddingContractError) else classify_provider_error(adapter, failure))
                if error.request_id:
                    request = replace(request, request_id=error.request_id)
            finally:
                local.release()
            if error is None or error.outcome != ProviderOutcome.RETRYABLE or attempts > max_retries:
                break
            delay = _backoff(attempts - 1, base_backoff_seconds, max_backoff_seconds, jitter, error.retry_after_seconds)
            try:
                if delay:
                    waiting.sleep(delay)
            except QuotaWaitExceeded:
                break
        for position, index in enumerate(indexes):
            common = dict(request=request, request_id=request.request_id, idempotency_key=request.idempotency_key,
                attempt_count=attempts, retry_count=max(0, attempts - 1), updated_at=datetime.now(timezone.utc))
            if error is not None:
                delay = _backoff(max(0, attempts - 1), base_backoff_seconds, max_backoff_seconds, lambda: 1, error.retry_after_seconds) if error.outcome == ProviderOutcome.RETRYABLE else None
                staged[index] = replace(staged[index], status=error.outcome.value, error_code=error.code,
                    reason=str(error), next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=delay) if delay is not None else None, **common)
                continue
            try:
                vector = _validate_vector(vectors[position], adapter)
            except (ValueError, TypeError, OverflowError) as failure:
                staged[index] = replace(staged[index], status="failed", error_code="EMBEDDING_CONTRACT", reason=str(failure), **common)
            else:
                staged[index] = replace(staged[index], status="embedded", vector=vector, **common)
        if after_batch is not None:
            after_batch(EmbeddingBatchResult(tuple(staged[index] for index in indexes)))
    return EmbeddingBatchResult(tuple(staged))


def retry_failed(result: EmbeddingBatchResult, adapter: EmbeddingAdapter, *, keys: set[str] | None = None, **options) -> EmbeddingBatchResult:
    """仅重试明确允许重试的条目，并保留稳定键和累计尝试次数。"""
    selected = [item for item in result.items if item.status == "retryable" and (keys is None or item.key in keys)]
    replacements = {}
    # 按角色分组，避免将首个条目的角色错误地应用于全部条目。
    for role in ("document", "query"):
        group = [item for item in selected if item.role == role]
        if not group:
            continue
        for item in group:
            algorithm, fingerprint = content_fingerprint(item.text, adapter.metadata, role)
            if item.content_fingerprint != fingerprint or item.fingerprint_algorithm != algorithm:
                raise EmbeddingContractError("retry adapter does not match the original input identity")
            if item.request is not None and item.request.scheme_identity != IndexSchemeVersion(adapter.metadata).identity:
                raise EmbeddingContractError("retry adapter does not match the original scheme")
        retried = embed_texts([item.text for item in group], adapter, keys=[item.key for item in group], role=role, **options)
        for original, updated in zip(group, retried.items):
            total = original.attempt_count + updated.attempt_count
            replacements[original.key] = replace(updated, attempt_count=total, retry_count=max(0, total - 1),
                diagnostics=original.diagnostics + updated.diagnostics, version_suffix=original.version_suffix)
    return EmbeddingBatchResult(tuple(replacements.get(item.key, item) for item in result.items))


def resolve_unknown(result: EmbeddingBatchResult, adapter: EmbeddingAdapter, *, keys: set[str] | None = None) -> EmbeddingBatchResult:
    """使用提供方显式声明的状态确认能力，核实结果未知的请求。"""
    if not getattr(adapter, "supports_status_query", False):
        raise EmbeddingContractError("adapter does not support explicit request resolution")
    resolved = {}
    for item in result.items:
        if item.status != "unknown" or (keys is not None and item.key not in keys):
            continue
        request = item.request
        if request is None:
            raise EmbeddingContractError("unknown item has no persisted request identity")
        if request in resolved:
            continue
        if request.scheme_identity != IndexSchemeVersion(adapter.metadata).identity:
            raise EmbeddingContractError("resolution adapter does not match original scheme")
        expected = tuple(content_fingerprint(text, adapter.metadata, request.role) for text in request.texts)
        if (any(algorithm != request.fingerprint_algorithm for algorithm, _ in expected)
                or tuple(fingerprint for _, fingerprint in expected) != request.fingerprints
                or tuple(_prepared_text(adapter, text, request.role) for text in request.texts) != request.prepared_texts):
            raise EmbeddingContractError("persisted request content does not match its identity")
        response = adapter.resolve_request(request)
        if not isinstance(response, UnknownResolution):
            raise EmbeddingContractError("resolver must return UnknownResolution")
        if (response.request_id, response.idempotency_key, tuple(response.keys), tuple(response.fingerprints)) != (request.request_id, request.idempotency_key, request.keys, request.fingerprints):
            raise EmbeddingContractError("resolved request identity does not match persisted identity")
        try:
            state = RequestState(response.state)
        except ValueError as error:
            raise EmbeddingContractError("invalid resolved request state") from error
        if state == RequestState.EMBEDDED:
            if response.vectors is None or len(response.vectors) != len(request.keys):
                raise EmbeddingContractError("resolver returned a different number of vectors than inputs")
            vectors = tuple(_validate_vector(vector, adapter) for vector in response.vectors)
        else:
            if response.vectors is not None:
                raise EmbeddingContractError("unresolved request must not include vectors")
            vectors = None
        resolved[request] = (response, state, vectors)
    items = []
    for item in result.items:
        response = resolved.get(item.request) if item.status == "unknown" and (keys is None or item.key in keys) else None
        if response is None:
            items.append(item)
            continue
        outcome, state, vectors = response
        position = item.request.keys.index(item.key)
        if item.content_fingerprint != item.request.fingerprints[position]:
            raise EmbeddingContractError("item fingerprint does not match persisted request identity")
        items.append(replace(item, status=state.value, vector=vectors[position] if vectors else None,
            error_code=outcome.error_code, reason=outcome.reason, updated_at=datetime.now(timezone.utc)))
    return EmbeddingBatchResult(tuple(items))
