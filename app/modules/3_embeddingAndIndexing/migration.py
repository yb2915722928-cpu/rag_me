"""Versioned parallel index build and guarded activation."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
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

    @property
    def valid(self) -> bool:
        return (
            self.expected_count == self.actual_count
            and self.dimensions_valid
            and self.states_valid
            and self.representative_retrieval_valid
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
            self._items[scheme.identity] = [item for item in self._items[scheme.identity] if item[0] != key]
            self._items[scheme.identity].append((key, values))

    def validate(self, scheme: IndexSchemeVersion, expected_count: int | None = None) -> ValidationReport:
        items = self._items.get(scheme.identity, [])
        dimensions_valid = all(len(vector) == scheme.metadata.dimensions for _, vector in items)
        states_valid = True
        representative_valid = bool(items) and _cosine(items[0][1], items[0][1]) >= 0.999999
        report = ValidationReport(scheme, expected_count if expected_count is not None else len(items), len(items), dimensions_valid, states_valid, representative_valid)
        if not report.valid:
            raise IndexValidationError(f"index validation failed for {scheme.identity}")
        return report

    def activate(self, scheme: IndexSchemeVersion, validator: Callable[[ValidationReport], bool] | None = None) -> None:
        expected_count = None
        if self._active is not None and self._active != scheme.identity:
            expected_count = len(self._items.get(self._active, []))
        report = self.validate(scheme, expected_count=expected_count)
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
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
