"""Bounded synchronous embedding batches with item-level retry state."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Iterable, Sequence

from .contracts import EmbeddingAdapter, EmbeddingContractError, IndexSchemeVersion


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


@dataclass(frozen=True)
class EmbeddingBatchResult:
    items: tuple[EmbeddedItem, ...]


def validate_query_vector(vector: Sequence[float], adapter: EmbeddingAdapter) -> tuple[float, ...]:
    return _validate_vector(vector, adapter)


def _validate_vector(vector: Sequence[float], adapter: EmbeddingAdapter) -> tuple[float, ...]:
    if len(vector) != adapter.metadata.dimensions:
        raise EmbeddingContractError(
            f"vector dimension {len(vector)} does not match declared dimension {adapter.metadata.dimensions}"
        )
    values = tuple(float(value) for value in vector)
    if not all(__import__("math").isfinite(value) for value in values):
        raise EmbeddingContractError("vector values must be finite")
    magnitude = sum(value * value for value in values) ** 0.5
    if adapter.metadata.normalization == "unit" and abs(magnitude - 1.0) > 1e-6:
        raise EmbeddingContractError("vector does not satisfy unit normalization policy")
    return values


def embed_texts(
    texts: Sequence[str],
    adapter: EmbeddingAdapter,
    *,
    max_batch_size: int = 64,
    max_tokens: int | None = None,
    token_counter: Callable[[str], int] | None = None,
    scheme: IndexSchemeVersion | None = None,
) -> EmbeddingBatchResult:
    if not isinstance(max_batch_size, int) or isinstance(max_batch_size, bool) or max_batch_size <= 0:
        raise ValueError("max_batch_size must be a positive integer")
    if max_tokens is not None and (not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0):
        raise ValueError("max_tokens must be a positive integer")
    adapter.validate_scheme(scheme or IndexSchemeVersion(adapter.metadata))
    counter = token_counter or getattr(adapter, "token_counter", None)
    if max_tokens is not None and counter is None:
        raise ValueError("a token counter is required when max_tokens is set")

    staged: list[EmbeddedItem | None] = [None] * len(texts)
    batches: list[list[int]] = []
    current: list[int] = []
    current_tokens = 0
    for index, text in enumerate(texts):
        count = counter(text) if counter else 0
        if not isinstance(count, int):
            try:
                count = len(count)
            except TypeError as error:
                raise ValueError("token counter must return a countable value") from error
        if isinstance(count, bool) or count < 0:
            raise ValueError("token counter must return a nonnegative integer")
        if max_tokens is not None and count > max_tokens:
            staged[index] = EmbeddedItem(str(index), text, "failed", error_code="ITEM_EXCEEDS_TOKEN_BUDGET", reason=f"item uses {count} tokens; limit is {max_tokens}", updated_at=datetime.now(timezone.utc))
            continue
        if current and (len(current) >= max_batch_size or (max_tokens is not None and current_tokens + count > max_tokens)):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(index)
        current_tokens += count
    if current:
        batches.append(current)

    for indexes in batches:
        try:
            vectors = adapter.embed([texts[index] for index in indexes])
            if len(vectors) != len(indexes):
                raise EmbeddingContractError("adapter returned a different number of vectors than inputs")
        except Exception as error:
            for index in indexes:
                staged[index] = EmbeddedItem(str(index), texts[index], "failed", error_code="EMBEDDING_FAILED", reason=str(error), updated_at=datetime.now(timezone.utc))
            continue
        for index, vector in zip(indexes, vectors):
            try:
                validated = _validate_vector(vector, adapter)
            except Exception as error:
                staged[index] = EmbeddedItem(str(index), texts[index], "failed", error_code="EMBEDDING_FAILED", reason=str(error), updated_at=datetime.now(timezone.utc))
            else:
                staged[index] = EmbeddedItem(str(index), texts[index], "embedded", validated, updated_at=datetime.now(timezone.utc))
    return EmbeddingBatchResult(tuple(item for item in staged if item is not None))


def retry_failed(
    result: EmbeddingBatchResult,
    adapter: EmbeddingAdapter,
    *,
    keys: set[str] | None = None,
    max_batch_size: int = 64,
    max_tokens: int | None = None,
    token_counter: Callable[[str], int] | None = None,
) -> EmbeddingBatchResult:
    selected = [item for item in result.items if item.status == "failed" and item.error_code != "ITEM_EXCEEDS_TOKEN_BUDGET" and (keys is None or item.key in keys)]
    if not selected:
        return result
    retried = embed_texts(
        [item.text for item in selected], adapter, max_batch_size=max_batch_size,
        max_tokens=max_tokens, token_counter=token_counter,
    )
    by_key = {original.key: replace(retried_item, key=original.key)
              for original, retried_item in zip(selected, retried.items)}
    updated = []
    for item in result.items:
        replacement_item = by_key.get(item.key)
        if replacement_item is None:
            updated.append(item)
        else:
            updated.append(replace(replacement_item, key=item.key, retry_count=item.retry_count + 1))
    return EmbeddingBatchResult(tuple(updated))
