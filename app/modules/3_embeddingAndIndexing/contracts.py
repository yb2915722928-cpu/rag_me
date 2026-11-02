"""区分编码角色的同步提供方接口及兼容导出。"""
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
    """适配器必须显式声明兼容的 document/query 编码角色组合。

    ``embed`` 保留为兼容旧实现的同步扩展方法。使用不同编码器端点的
    适配器必须覆盖 ``embed_role``；默认实现仅支持同一编码器，
    但两个角色可以使用不同指令。
    """

    metadata: EmbeddingMetadata
    supports_status_query = False
    supports_request_metadata = False
    # Opt in only when embed_role/embed_request forwards remaining to every
    # network connect/read and retry boundary. Unsupported providers fail closed.
    supports_deadline = False

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        raise NotImplementedError

    def prepare_text(self, text: str, role: str) -> str:
        if not isinstance(text, str):
            raise EmbeddingContractError("embedding text must be a string")
        return self.metadata.role_config(role).instruction + text

    def embed_role(self, texts: Sequence[str], role: str, *, remaining=None) -> list[tuple[float, ...]]:
        if not self.metadata.verifiable:
            raise EmbeddingContractError("adapter must explicitly declare both encoding roles")
        document = self.metadata.role_config("document")
        query = self.metadata.role_config("query")
        if document.encoder_id != query.encoder_id:
            raise EmbeddingContractError("different encoder endpoints require an explicit role-aware adapter")
        if remaining is not None:
            remaining.check()
            if not self.supports_deadline:
                raise EmbeddingContractError("adapter does not support a retrieval deadline")
            return self.embed([self.prepare_text(text, role) for text in texts], remaining=remaining)
        return self.embed([self.prepare_text(text, role) for text in texts])

    def validate_scheme(self, scheme: IndexSchemeVersion) -> None:
        if not self.metadata.verifiable:
            raise EmbeddingContractError("adapter must explicitly declare both encoding roles")
        if scheme.metadata != self.metadata:
            raise EmbeddingContractError("adapter metadata does not match index scheme")


class DeterministicEmbeddingAdapter(EmbeddingAdapter):
    """输出稳定的本地适配器，显式声明兼容的对称编码角色组合。"""

    supports_deadline = True

    def __init__(self, dimensions: int, normalization: str = "unit", token_counter=None) -> None:
        self.token_counter = token_counter
        self.metadata = EmbeddingMetadata(
            provider="test", model="deterministic-hash", model_revision="v1",
            dimensions=dimensions, normalization=normalization,
            document_role=EmbeddingRoleConfig("document", "deterministic-hash:v1"),
            query_role=EmbeddingRoleConfig("query", "deterministic-hash:v1"),
        )

    def embed(self, texts: Sequence[str], *, remaining=None) -> list[tuple[float, ...]]:
        vectors = []
        for text in texts:
            if remaining is not None:
                remaining.check()
            values = []
            for index in range(self.metadata.dimensions):
                digest = hashlib.sha256(f"{index}:{text}".encode("utf-8")).digest()
                values.append((int.from_bytes(digest[:8], "big") / 2**63) - 1.0)
            if self.metadata.normalization == "unit":
                magnitude = math.sqrt(sum(value * value for value in values))
                values = [value / magnitude for value in values]
            vectors.append(tuple(values))
        return vectors
