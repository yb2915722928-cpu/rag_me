"""Provider- and storage-independent identities for embedding and retrieval."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping


class EmbeddingContractError(ValueError):
    """An input or a vector does not satisfy its representation contract."""


class ContentFingerprintConflict(EmbeddingContractError):
    """The same immutable logical identity names different encoding input."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _required_strings(*values: object) -> None:
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise EmbeddingContractError("identity fields must be non-empty strings")


@dataclass(frozen=True)
class EmbeddingRoleConfig:
    role: str
    encoder_id: str
    instruction: str = ""
    config_version: str = "v1"
    tokenizer_policy: str = "identity"

    def __post_init__(self) -> None:
        if self.role not in {"document", "query"}:
            raise EmbeddingContractError("role must be document or query")
        _required_strings(self.encoder_id, self.config_version, self.tokenizer_policy)
        if not isinstance(self.instruction, str):
            raise EmbeddingContractError("instruction must be a string")


@dataclass(frozen=True)
class EmbeddingMetadata:
    provider: str
    model: str
    model_revision: str
    dimensions: int
    metric: str = "cosine"
    normalization: str = "unit"
    chunking_policy: str = "unknown"
    document_role: EmbeddingRoleConfig | None = None
    query_role: EmbeddingRoleConfig | None = None
    fingerprint_version: str = "v1"

    def __post_init__(self) -> None:
        _required_strings(self.provider, self.model, self.model_revision, self.metric,
                          self.normalization, self.chunking_policy, self.fingerprint_version)
        if not isinstance(self.dimensions, int) or isinstance(self.dimensions, bool) or self.dimensions <= 0:
            raise EmbeddingContractError("dimensions must be a positive integer")
        if self.metric != "cosine":
            raise EmbeddingContractError("only cosine metric is supported")
        if self.normalization not in {"unit", "none"}:
            raise EmbeddingContractError("normalization must be unit or none")
        for role, config in (("document", self.document_role), ("query", self.query_role)):
            if config is not None and (not isinstance(config, EmbeddingRoleConfig) or config.role != role):
                raise EmbeddingContractError("role config is assigned to the wrong role")
        if self.fingerprint_version != "v1":
            raise EmbeddingContractError("unsupported fingerprint canonicalization version")

    @property
    def verifiable(self) -> bool:
        return self.document_role is not None and self.query_role is not None

    def with_changes(self, **changes: object) -> EmbeddingMetadata:
        return replace(self, **changes)

    def role_config(self, role: str) -> EmbeddingRoleConfig:
        if role not in {"document", "query"}:
            raise EmbeddingContractError("role must be document or query")
        config = self.document_role if role == "document" else self.query_role
        if config is None:
            raise EmbeddingContractError("legacy metadata has no explicit role compatibility declaration")
        return config


@dataclass(frozen=True)
class IndexSchemeVersion:
    metadata: EmbeddingMetadata

    @property
    def identity(self) -> str:
        # Hash the complete structured contract; delimiter-concatenated identities
        # cannot distinguish delimiters inside model IDs or policy names.
        digest = hashlib.sha256(canonical_json(asdict(self.metadata)).encode("utf-8")).hexdigest()
        return ("scheme:v2:" if self.metadata.verifiable else "legacy:") + digest


def scheme_from_metadata(metadata: Mapping[str, Any]) -> IndexSchemeVersion:
    values = dict(metadata)
    for key in ("document_role", "query_role"):
        config = values.get(key)
        if isinstance(config, Mapping):
            values[key] = EmbeddingRoleConfig(**config)
    return IndexSchemeVersion(EmbeddingMetadata(**values))


def content_fingerprint(text: str, metadata: EmbeddingMetadata, role: str) -> tuple[str, str]:
    if not isinstance(text, str):
        raise EmbeddingContractError("embedding text must be a string")
    config = metadata.role_config(role)
    payload = {
        "version": metadata.fingerprint_version,
        "text_utf8": text,
        "prepared_text_utf8": config.instruction + text,
        "role_config": asdict(config),
        "chunking_policy": metadata.chunking_policy,
    }
    return "sha256", hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    document_version: str
    text: str
    metadata: dict[str, Any]
    chunk_version: str

    def __post_init__(self) -> None:
        _required_strings(self.chunk_id, self.document_id, self.document_version, self.chunk_version)
        if not isinstance(self.text, str) or not isinstance(self.metadata, dict):
            raise EmbeddingContractError("chunk requires text and metadata")

    @property
    def version(self) -> str:
        """Legacy document revision alias, never a Chunk revision."""
        return self.document_version


@dataclass(frozen=True)
class LogicalIndexIdentity:
    document_id: str
    document_version: str
    chunk_id: str
    scheme_identity: str
    chunk_version: str

    def __post_init__(self) -> None:
        _required_strings(self.document_id, self.document_version, self.chunk_id,
                          self.scheme_identity, self.chunk_version)

    @property
    def key(self) -> str:
        return canonical_json([self.document_id, self.document_version, self.chunk_id,
                               self.scheme_identity, self.chunk_version])


@dataclass(frozen=True)
class SearchHit:
    chunk: ChunkRecord
    score: float
    scheme_identity: str
    content_fingerprint: str | None = None
    fingerprint_algorithm: str | None = None
    generated_at: datetime | None = None
