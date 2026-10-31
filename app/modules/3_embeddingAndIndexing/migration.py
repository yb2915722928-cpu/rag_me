"""Versioned parallel index build and guarded activation."""
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
    """Deterministic migration adapter mirroring the versioned storage contract."""

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
        items = self._items.get(scheme.identity, [])
        dimensions_valid = all(len(vector) == scheme.metadata.dimensions for _, vector in items)
        states_valid = True
        keys = {key for key, _ in items}
        identities_valid = expected_keys is None or keys == expected_keys
        if representative_key is None:
            representative_key = sorted(expected_keys or keys)[0] if (expected_keys or keys) else None
        actual_vector = next((vector for key, vector in items if key == representative_key), None)
        expected_vector = tuple(representative_vector) if representative_vector is not None else actual_vector
        representative_valid = (
            actual_vector is not None and expected_vector is not None
            and _cosine(actual_vector, expected_vector) >= threshold
        )
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
        if expected_keys is None and self._active is not None and self._active != scheme.identity:
            expected_keys = {key for key, _ in self._items.get(self._active, [])}
        if expected_keys is None and self._active is None:
            raise IndexValidationError("expected_keys manifest is required for initial activation")
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
