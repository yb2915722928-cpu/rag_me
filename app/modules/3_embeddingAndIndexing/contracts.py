"""Public contracts for synchronous embedding and versioned index schemes."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
from typing import Iterable, Sequence


class EmbeddingContractError(ValueError):
    """Raised when an adapter or index scheme is incompatible."""


@dataclass(frozen=True)
class EmbeddingMetadata:
    provider: str
    model: str
    model_revision: str
    dimensions: int
    metric: str = "cosine"
    normalization: str = "unit"
    chunking_policy: str = "unknown"

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (
            self.provider, self.model, self.model_revision, self.metric,
            self.normalization, self.chunking_policy,
        )):
            raise EmbeddingContractError("embedding metadata fields must be non-empty strings")
        if not isinstance(self.dimensions, int) or isinstance(self.dimensions, bool) or self.dimensions <= 0:
            raise EmbeddingContractError("dimensions must be a positive integer")
        if self.metric != "cosine":
            raise EmbeddingContractError("only cosine metric is supported")
        if self.normalization not in {"unit", "none"}:
            raise EmbeddingContractError("normalization must be unit or none")

    def with_changes(self, **changes: object) -> "EmbeddingMetadata":
        return replace(self, **changes)


@dataclass(frozen=True)
class IndexSchemeVersion:
    metadata: EmbeddingMetadata

    @property
    def identity(self) -> str:
        metadata = self.metadata
        return ":".join((
            f"{metadata.provider}/{metadata.model}@{metadata.model_revision}",
            str(metadata.dimensions), metadata.metric, metadata.normalization,
            metadata.chunking_policy,
        ))


class EmbeddingAdapter:
    """Synchronous provider-neutral embedding boundary."""

    metadata: EmbeddingMetadata

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        raise NotImplementedError

    def validate_scheme(self, scheme: IndexSchemeVersion) -> None:
        if scheme.metadata != self.metadata:
            raise EmbeddingContractError("adapter metadata does not match index scheme")


class DeterministicEmbeddingAdapter(EmbeddingAdapter):
    """Stable hash-based adapter for tests and local contract verification."""

    def __init__(self, dimensions: int, normalization: str = "unit", token_counter=None) -> None:
        self.token_counter = token_counter
        self.metadata = EmbeddingMetadata(
            provider="test", model="deterministic-hash", model_revision="v1",
            dimensions=dimensions, normalization=normalization,
        )

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            values = []
            for index in range(self.metadata.dimensions):
                digest = hashlib.sha256(f"{index}:{text}".encode("utf-8")).digest()
                values.append((int.from_bytes(digest[:8], "big") / 2**63) - 1.0)
            if self.metadata.normalization == "unit":
                magnitude = math.sqrt(sum(value * value for value in values))
                values = [value / magnitude for value in values]
            vectors.append(tuple(values))
        return vectors
