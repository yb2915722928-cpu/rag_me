"""Role-aware synchronous provider boundary and compatibility exports."""
from __future__ import annotations

import hashlib
import math
from typing import Sequence

from app.models.embedding import (
    ChunkRecord, ContentFingerprintConflict, EmbeddingContractError,
    EmbeddingMetadata, EmbeddingRoleConfig, IndexSchemeVersion,
    LogicalIndexIdentity, SearchHit, content_fingerprint, scheme_from_metadata,
)


class EmbeddingAdapter:
    """Adapters explicitly declare the compatible document/query role pair.

    ``embed`` remains the synchronous legacy implementation hook. Adapters using
    different encoder endpoints must override ``embed_role``; the default hook
    supports one encoder with optional different instructions only.
    """

    metadata: EmbeddingMetadata
    supports_status_query = False
    supports_request_metadata = False

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        raise NotImplementedError

    def prepare_text(self, text: str, role: str) -> str:
        if not isinstance(text, str):
            raise EmbeddingContractError("embedding text must be a string")
        return self.metadata.role_config(role).instruction + text

    def embed_role(self, texts: Sequence[str], role: str) -> list[tuple[float, ...]]:
        if not self.metadata.verifiable:
            raise EmbeddingContractError("adapter must explicitly declare both encoding roles")
        document = self.metadata.role_config("document")
        query = self.metadata.role_config("query")
        if document.encoder_id != query.encoder_id:
            raise EmbeddingContractError("different encoder endpoints require an explicit role-aware adapter")
        return self.embed([self.prepare_text(text, role) for text in texts])

    def validate_scheme(self, scheme: IndexSchemeVersion) -> None:
        if not self.metadata.verifiable:
            raise EmbeddingContractError("adapter must explicitly declare both encoding roles")
        if scheme.metadata != self.metadata:
            raise EmbeddingContractError("adapter metadata does not match index scheme")


class DeterministicEmbeddingAdapter(EmbeddingAdapter):
    """Stable local adapter explicitly declaring a compatible symmetric pair."""

    def __init__(self, dimensions: int, normalization: str = "unit", token_counter=None) -> None:
        self.token_counter = token_counter
        self.metadata = EmbeddingMetadata(
            provider="test", model="deterministic-hash", model_revision="v1",
            dimensions=dimensions, normalization=normalization,
            document_role=EmbeddingRoleConfig("document", "deterministic-hash:v1"),
            query_role=EmbeddingRoleConfig("query", "deterministic-hash:v1"),
        )

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        vectors = []
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
