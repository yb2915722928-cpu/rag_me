"""同步 Embedding 应用流程，仅依赖领域存储协议。"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from typing import Sequence
import uuid

from app.models.embedding import (
    ChunkRecord, EmbeddingContractError, IndexSchemeVersion, LogicalIndexIdentity,
    content_fingerprint,
)
from .batching import (
    EmbeddedItem, EmbeddingBatchResult, LongInputPolicy, embed_texts,
    prepare_long_inputs, resolve_unknown, validate_query_vector,
)
from .ports import RequestRepository, VectorStore
from .requests import BatchRequest


class EmbeddingQueryError(EmbeddingContractError):
    def __init__(self, result: EmbeddingBatchResult):
        self.result = result
        super().__init__("query embedding did not complete: " + result.items[0].status)


def _repository(store, repository):
    selected = repository if repository is not None else store
    required = ("reserve_batch_attempts", "resolve_attempt", "get_attempt_for_identity")
    if any(not callable(getattr(selected, name, None)) for name in required):
        raise EmbeddingContractError("a durable request repository is required for the embedding flow")
    return selected


def _chunk(chunk) -> ChunkRecord:
    # 上游必须同时提供文档和 Chunk 修订；缺失属性属于契约错误，
    # 不能用文档修订或全局默认值推导 Chunk 修订。
    try:
        return ChunkRecord(chunk.chunk_id, chunk.document_id, chunk.document_version,
                           chunk.text, dict(chunk.metadata), chunk.chunk_version)
    except (AttributeError, TypeError) as error:
        raise EmbeddingContractError("Chunk requires document_version and chunk_version") from error


def _identity(chunk, scheme):
    return LogicalIndexIdentity(chunk.document_id, chunk.document_version, chunk.chunk_id,
                                scheme.identity, chunk.chunk_version)


def _restore(attempt, text, adapter):
    payload = attempt.request_payload
    request = BatchRequest(**payload) if payload else None
    if attempt.identity.scheme_identity != IndexSchemeVersion(adapter.metadata).identity:
        raise EmbeddingContractError("durable request belongs to a different representation scheme")
    if request is not None:
        if request.scheme_identity != attempt.identity.scheme_identity or attempt.identity.key not in request.keys:
            raise EmbeddingContractError("durable request does not match logical identity")
        position = request.keys.index(attempt.identity.key)
        algorithm, fingerprint = content_fingerprint(text, adapter.metadata, request.role)
        if (request.texts[position] != text or request.fingerprints[position] != fingerprint
                or attempt.content_fingerprint != fingerprint or request.fingerprint_algorithm != algorithm
                or request.prepared_texts[position] != adapter.prepare_text(text, request.role)):
            raise EmbeddingContractError("durable request does not match actual encoding input")
    state = {"succeeded": "embedded", "pending": "unknown"}.get(attempt.status, attempt.status)
    result = attempt.result_payload or {}
    vector = result.get("vector")
    if vector is not None:
        vector = validate_query_vector(vector, adapter)
    if state == "embedded" and vector is None:
        raise EmbeddingContractError("successful durable request is missing its vector result")
    return EmbeddedItem(attempt.identity.key, text, state, vector=vector,
        error_code="REQUEST_IN_FLIGHT" if attempt.status == "pending" else result.get("error_code"),
        reason=attempt.error, content_fingerprint=attempt.content_fingerprint,
        fingerprint_algorithm="sha256", role=request.role if request else "document",
        request_id=attempt.request_id, idempotency_key=request.idempotency_key if request else attempt.idempotency_key, request=request,
        diagnostics=tuple(result.get("diagnostics", ())),
        attempt_count=result.get("attempt_count", 0), retry_count=result.get("retry_count", 0),
        next_retry_at=datetime.fromisoformat(result["next_retry_at"]) if result.get("next_retry_at") else None,
        updated_at=datetime.fromisoformat(result["updated_at"]) if result.get("updated_at") else None,
        version_suffix=result.get("version_suffix"))


def _persist(result, identities, repository):
    for item in result.items:
        attempt = repository.get_attempt_for_identity(identities[item.key])
        if attempt is None:
            # 因输入、Token 上限或配额而在发送前被拒绝的条目未提交给提供方。
            continue
        status = "succeeded" if item.status in {"embedded", "stored"} else item.status
        if status not in {"succeeded", "failed", "retryable", "unknown"}:
            raise EmbeddingContractError("invalid request result state")
        repository.resolve_attempt(attempt.attempt_id, status, request_id=item.request_id,
            # CAS 预期值取自刚读取的当前请求；旧响应不能覆盖重试后的新请求。
            expected_request_id=attempt.request_id,
            error=item.reason, request_payload=asdict(item.request) if item.request else None,
            result_payload={
                "vector": list(item.vector) if item.vector is not None else None,
                "fingerprint_algorithm": item.fingerprint_algorithm,
                "diagnostics": list(item.diagnostics),
                "attempt_count": item.attempt_count, "retry_count": item.retry_count,
                "error_code": item.error_code, "version_suffix": item.version_suffix,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "next_retry_at": item.next_retry_at.isoformat() if item.next_retry_at else None,
            })


def _write(result, chunks, scheme, store):
    items = []
    for item in result.items:
        if item.status != "embedded":
            items.append(item)
            continue
        chunk = chunks[item.key]
        try:
            store.upsert(scheme, chunk, item.vector,
                         content_fingerprint=item.content_fingerprint,
                         fingerprint_algorithm=item.fingerprint_algorithm, generated_at=item.updated_at)
        except Exception as error:
            # 提供方结果已经持久化；再次调用 index_chunks 时可复用该向量
            # 重试写入，无需向提供方提交新请求。
            items.append(replace(item, status="failed", error_code="INDEX_PERSISTENCE_FAILED", reason=str(error)))
        else:
            items.append(replace(item, status="stored"))
    return EmbeddingBatchResult(tuple(items))


def index_chunks(chunks: Sequence, adapter, store: VectorStore, *,
                 request_repository: RequestRepository | None = None,
                 retry_retryable: bool = False, **batch_options) -> EmbeddingBatchResult:
    if "role" in batch_options:
        raise EmbeddingContractError("index_chunks always encodes the document role")
    scheme = IndexSchemeVersion(adapter.metadata)
    adapter.validate_scheme(scheme)
    repository = _repository(store, request_repository)
    sources = [_chunk(chunk) for chunk in chunks]
    policy = batch_options.pop("long_input_policy", None)
    limits = [limit for limit in (batch_options.get("max_tokens"), batch_options.get("token_budget"))
              if limit is not None]
    effective_max_tokens = min(limits) if limits else None
    prepared = prepare_long_inputs([chunk.text for chunk in sources], adapter,
        max_tokens=effective_max_tokens, token_counter=batch_options.get("token_counter"),
        policy=policy or LongInputPolicy())
    records, identities, prepared_by_key = {}, {}, {}
    for entry in prepared:
        source = sources[entry.parent_index]
        transformed = entry.version_suffix is not None
        metadata = dict(source.metadata)
        if transformed:
            metadata["embedding_transform"] = {"source_chunk_id": source.chunk_id,
                "source_chunk_version": source.chunk_version,
                "source_text": source.text, "policy_id": policy.policy_id,
                "mode": policy.mode, "diagnostics": list(entry.diagnostics)}
        record = ChunkRecord(source.chunk_id, source.document_id, source.document_version,
            entry.text, metadata, source.chunk_version + ":" + entry.version_suffix if transformed else source.chunk_version)
        identity = _identity(record, scheme)
        if identity.key in records:
            raise EmbeddingContractError("duplicate Chunk logical identity in one indexing call")
        records[identity.key], identities[identity.key], prepared_by_key[identity.key] = record, identity, entry
    previous, pending, retrying = {}, [], {}
    for key, record in records.items():
        attempt = repository.get_attempt_for_identity(identities[key])
        if attempt is None:
            pending.append(key)
            continue
        _, fingerprint = content_fingerprint(record.text, adapter.metadata, "document")
        if attempt.content_fingerprint != fingerprint:
            from app.models.embedding import ContentFingerprintConflict
            raise ContentFingerprintConflict("logical identity already names different encoding input")
        if attempt.status == "retryable" and retry_retryable:
            retrying[key] = attempt
        else:
            previous[key] = _restore(attempt, record.text, adapter)

    def run(keys, retry=False):
        def reserve(request, attempt_number):
            if attempt_number:
                return
            if retry:
                # 每个重试组仅含一个条目，确保逐个明确决定是否重试
                # 先前被标记为可重试的逻辑身份。
                old = retrying[keys[0]]
                repository.retry_attempt(old.attempt_id, request_payload=asdict(request))
            else:
                repository.reserve_batch_attempts([identities[key] for key in request.keys],
                    list(request.fingerprints), request_payload=asdict(request))
        prior_result = dict(retrying[keys[0]].result_payload or {}) if retry else {}

        def finalize(outcome):
            if retry:
                outcome = EmbeddingBatchResult(tuple(replace(item,
                    attempt_count=prior_result.get("attempt_count", 0) + item.attempt_count,
                    retry_count=max(0, prior_result.get("attempt_count", 0) + item.attempt_count - 1),
                    diagnostics=tuple(prior_result.get("diagnostics", ())) + item.diagnostics,
                ) for item in outcome.items))
            _persist(outcome, identities, repository)
            return outcome

        outcome = embed_texts([records[key].text for key in keys], adapter, scheme=scheme, role="document",
            keys=keys, prepared_inputs=[prepared_by_key[key] for key in keys],
            before_request=reserve, after_batch=finalize, **batch_options)
        # 补充未发送的条目，它们不会经过提供方批次完成回调。
        return finalize(outcome)

    completed = dict(previous)
    if pending:
        completed.update((item.key, item) for item in run(pending).items)
    for key in retrying:
        completed.update((item.key, item) for item in run([key], retry=True).items)
    ordered = EmbeddingBatchResult(tuple(completed[key] for key in records))
    return _write(ordered, records, scheme, store)


def resolve_index_requests(chunks: Sequence, adapter, store: VectorStore, *,
                           request_repository: RequestRepository | None = None,
                           keys: set[str] | None = None) -> EmbeddingBatchResult:
    """显式向提供方核实请求结果，支持重启后恢复的请求。"""
    scheme = IndexSchemeVersion(adapter.metadata)
    adapter.validate_scheme(scheme)
    repository = _repository(store, request_repository)
    records = {_identity(record, scheme).key: record for record in map(_chunk, chunks)}
    identities = {key: _identity(record, scheme) for key, record in records.items()}
    items = []
    for key, record in records.items():
        attempt = repository.get_attempt_for_identity(identities[key])
        if attempt is None:
            raise EmbeddingContractError("no durable request exists for Chunk")
        _, fingerprint = content_fingerprint(record.text, adapter.metadata, "document")
        if attempt.content_fingerprint != fingerprint:
            raise EmbeddingContractError("resolution Chunk differs from the persisted input")
        items.append(_restore(attempt, record.text, adapter))
    result = resolve_unknown(EmbeddingBatchResult(tuple(items)), adapter, keys=keys)
    _persist(result, identities, repository)
    return _write(result, records, scheme, store)


def adjudicate_index_request(identity: LogicalIndexIdentity, repository, *,
                             state: str, actor: str, reason: str) -> None:
    """提供方无法查询请求状态时，由调用方确认请求结果。"""
    if state not in {"failed", "retryable"} or not actor.strip() or not reason.strip():
        raise EmbeddingContractError("adjudication requires failed/retryable, actor and reason")
    attempt = repository.get_attempt_for_identity(identity)
    if attempt is None or attempt.status not in {"pending", "unknown"}:
        raise EmbeddingContractError("only uncertain requests can be adjudicated")
    repository.resolve_attempt(attempt.attempt_id, state, error=f"{actor}: {reason}")


def search_chunks(query: str, adapter, store: VectorStore, *, limit: int = 10,
                  request_repository: RequestRepository | None = None,
                  batch_options: dict | None = None, **search_options):
    scheme = IndexSchemeVersion(adapter.metadata)
    adapter.validate_scheme(scheme)
    repository = _repository(store, request_repository)
    identity = LogicalIndexIdentity("__query__", scheme.identity, str(uuid.uuid4()), scheme.identity, "query:v1")

    def reserve(request, attempt_number):
        if not attempt_number:
            repository.reserve_batch_attempts([identity], list(request.fingerprints), request_payload=asdict(request))
    result = embed_texts([query], adapter, scheme=scheme, role="query", keys=[identity.key],
                        before_request=reserve, **(batch_options or {}))
    _persist(result, {identity.key: identity}, repository)
    if result.items[0].status != "embedded":
        raise EmbeddingQueryError(result)
    return store.search(scheme, result.items[0].vector, limit=limit, **search_options)


def resolve_query_request(result: EmbeddingBatchResult, adapter, store: VectorStore, *,
                          request_repository: RequestRepository | None = None,
                          limit: int = 10, **search_options):
    """核实已持久化的查询请求，无需重新提交查询文本。"""
    import json
    if len(result.items) != 1 or result.items[0].role != "query":
        raise EmbeddingContractError("query resolution requires exactly one query item")
    repository = _repository(store, request_repository)
    identity = LogicalIndexIdentity(*json.loads(result.items[0].key))
    attempt = repository.get_attempt_for_identity(identity)
    if attempt is None:
        raise EmbeddingContractError("query request has no durable reservation")
    restored = EmbeddingBatchResult((_restore(attempt, result.items[0].text, adapter),))
    resolved = resolve_unknown(restored, adapter)
    _persist(resolved, {identity.key: identity}, repository)
    if resolved.items[0].status != "embedded":
        raise EmbeddingQueryError(resolved)
    scheme = IndexSchemeVersion(adapter.metadata)
    return store.search(scheme, resolved.items[0].vector, limit=limit, **search_options)


def search_serving_chunks(query: str, adapter_for_scheme, store, **options):
    """编码前一次性读取完整的活动方案与物理配置组合。"""
    if "config" in options:
        raise EmbeddingContractError("serving query uses the active physical configuration")
    scheme, config = store.active_binding()
    adapter = adapter_for_scheme(scheme)
    adapter.validate_scheme(scheme)
    return search_chunks(query, adapter, store, config=config, **options)
