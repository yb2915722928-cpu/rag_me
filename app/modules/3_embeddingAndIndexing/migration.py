"""并行构建版本化索引，并在校验通过后激活。"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Callable, Sequence

from .contracts import EmbeddingContractError, IndexSchemeVersion


class IndexValidationError(ValueError):
    pass


class ActiveSchemeDeletionError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationReport:
    scheme: IndexSchemeVersion
    expected_count: int
    actual_count: int
    dimensions_valid: bool
    states_valid: bool
    representative_retrieval_valid: bool
    identities_valid: bool = True

    @property
    def valid(self) -> bool:
        return (
            self.expected_count == self.actual_count
            and self.dimensions_valid
            and self.states_valid
            and self.representative_retrieval_valid
            and self.identities_valid
        )


class InMemoryIndexRegistry:
    """行为确定的内存迁移适配器，与版本化存储契约保持一致。"""

    def __init__(self) -> None:
        self.schemes: dict[str, IndexSchemeVersion] = {}
        self._items: dict[str, list[tuple[str, tuple[float, ...]]]] = {}
        self._active: str | None = None

    @property
    def active_scheme(self) -> IndexSchemeVersion | None:
        return self.schemes.get(self._active) if self._active else None

    def register(self, scheme: IndexSchemeVersion) -> None:
        if scheme.metadata.metric != "cosine":
            raise EmbeddingContractError("only cosine metric is supported")
        self.schemes.setdefault(scheme.identity, scheme)
        self._items.setdefault(scheme.identity, [])

    def seed(self, scheme: IndexSchemeVersion, keys: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        if scheme.identity not in self.schemes:
            raise KeyError("scheme must be registered before building")
        if len(keys) != len(vectors):
            raise ValueError("keys and vectors must have the same length")
        for key, vector in zip(keys, vectors):
            values = tuple(float(value) for value in vector)
            if len(values) != scheme.metadata.dimensions:
                raise EmbeddingContractError("vector dimension does not match scheme")
            if not all(isfinite(value) for value in values):
                raise EmbeddingContractError("vector values must be finite")
            magnitude = sqrt(sum(value * value for value in values))
            if magnitude == 0:
                raise EmbeddingContractError("zero vectors are not valid for cosine indexing")
            if scheme.metadata.normalization == "unit" and abs(magnitude - 1.0) > 1e-6:
                raise EmbeddingContractError("vector does not satisfy unit normalization policy")
            existing = self._items[scheme.identity]
            self._items[scheme.identity] = [item for item in existing if item[0] != key]
            self._items[scheme.identity].append((key, values))

    def validate(self, scheme: IndexSchemeVersion, expected_count: int | None = None,
                 expected_keys: set[str] | None = None, representative_key: str | None = None,
                 representative_vector: Sequence[float] | None = None, threshold: float = 0.99) -> ValidationReport:
        if not scheme.metadata.verifiable:
            raise IndexValidationError("legacy scheme requires explicit role backfill and revalidation")
        items = self._items.get(scheme.identity, [])
        dimensions_valid = all(len(vector) == scheme.metadata.dimensions for _, vector in items)
        states_valid = True
        if not expected_keys or representative_vector is None:
            raise IndexValidationError("expected_keys and an independent representative query vector are required")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not isfinite(threshold) or not -1 <= threshold <= 1:
            raise IndexValidationError("representative threshold must be finite in -1..1")
        keys = {key for key, _ in items}
        identities_valid = keys == expected_keys
        representative_key = representative_key or sorted(expected_keys)[0]
        expected_vector = tuple(float(value) for value in representative_vector)
        if (len(expected_vector) != scheme.metadata.dimensions
                or not all(isfinite(value) for value in expected_vector)
                or not any(expected_vector)):
            raise IndexValidationError("representative query vector is invalid")
        ranked = sorted(((_cosine(vector, expected_vector), key) for key, vector in items),
                        key=lambda hit: (-hit[0], hit[1]))
        representative_valid = bool(ranked) and ranked[0][1] == representative_key and ranked[0][0] >= threshold
        report = ValidationReport(
            scheme, expected_count if expected_count is not None else len(items), len(items),
            dimensions_valid, states_valid, representative_valid, identities_valid,
        )
        if not report.valid:
            raise IndexValidationError(f"index validation failed for {scheme.identity}: {report}")
        return report

    def activate(self, scheme: IndexSchemeVersion, validator: Callable[[ValidationReport], bool] | None = None,
                 *, expected_keys: set[str] | None = None,
                 representative_key: str | None = None,
                 representative_vector: Sequence[float] | None = None) -> None:
        if expected_keys is None:
            raise IndexValidationError("expected_keys manifest is required for activation")
        report = self.validate(scheme, expected_keys=expected_keys,
                               representative_key=representative_key,
                               representative_vector=representative_vector)
        if validator is not None and not validator(report):
            raise IndexValidationError(f"index validation rejected {scheme.identity}")
        self._active = scheme.identity

    def query_scheme(self, scheme: IndexSchemeVersion | None = None) -> IndexSchemeVersion:
        selected = scheme or self.active_scheme
        if selected is None or selected.identity not in self.schemes:
            raise KeyError("no retained index scheme is available")
        return selected

    def delete(self, scheme: IndexSchemeVersion) -> None:
        if scheme.identity == self._active:
            raise ActiveSchemeDeletionError("active index scheme must be switched before deletion")
        self.schemes.pop(scheme.identity, None)
        self._items.pop(scheme.identity, None)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
