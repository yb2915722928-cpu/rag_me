"""Authoritative evidence identities, independent of derived index schemes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Mapping

from app.models.embedding import ChunkRecord, canonical_json


class RetrievalContractError(ValueError):
    """The request cannot safely describe a retrieval operation."""


class SnapshotNotReady(RetrievalContractError):
    """A required resource or visible relation is incomplete."""


class ContentConflict(RetrievalContractError):
    """An immutable evidence identity was reused with different content."""


def required_strings(*values):
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise RetrievalContractError("identity fields must be non-empty strings")


def json_copy(value):
    try:
        return json.loads(canonical_json(value))
    except (TypeError, ValueError) as exc:
        raise RetrievalContractError("content metadata and sources must be finite JSON values") from exc


@dataclass(frozen=True, order=True)
class EvidenceIdentity:
    knowledge_base_id: str
    document_id: str
    document_version: str
    chunk_id: str
    chunk_version: str

    def __post_init__(self):
        required_strings(*self.parts)

    @property
    def parts(self) -> tuple[str, ...]:
        return (self.knowledge_base_id, self.document_id, self.document_version,
                self.chunk_id, self.chunk_version)

    @property
    def key(self) -> str:
        return canonical_json(self.parts)

    @classmethod
    def from_key(cls, key: str) -> EvidenceIdentity:
        parts = json.loads(key)
        if not isinstance(parts, list) or len(parts) != 5:
            raise RetrievalContractError("evidence identity requires five fields")
        return cls(*parts)


@dataclass(frozen=True)
class ContentRecord:
    identity: EvidenceIdentity
    text: str
    source: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    parent: EvidenceIdentity | None = None

    def __post_init__(self):
        if not isinstance(self.identity, EvidenceIdentity) or not isinstance(self.text, str):
            raise RetrievalContractError("content requires a complete identity and text")
        if not isinstance(self.source, dict) or not self.source or not isinstance(self.metadata, dict):
            raise RetrievalContractError("content requires source information and metadata")
        if self.parent is not None:
            if (not isinstance(self.parent, EvidenceIdentity)
                    or self.parent.parts[:3] != self.identity.parts[:3]
                    or self.parent == self.identity):
                raise RetrievalContractError("parent must identify a different chunk in the same document revision")
        object.__setattr__(self, "source", json_copy(self.source))
        object.__setattr__(self, "metadata", json_copy(self.metadata))

    @classmethod
    def from_chunk(cls, chunk, *, knowledge_base_id: str, document_version: str,
                   chunk_version: str, parent: EvidenceIdentity | None = None) -> ContentRecord:
        """Adapt module2 Chunk; its ambiguous `version` is never inferred as either revision.

        Parent revisions must be supplied explicitly. Reverse child relations are
        derived from the children's complete parent identities at prepare time.
        """
        identity = EvidenceIdentity(knowledge_base_id, chunk.document_id, document_version,
                                    chunk.chunk_id, chunk_version)
        if chunk.parent_chunk_id != (parent.chunk_id if parent else None):
            raise RetrievalContractError("chunk parent requires its complete explicit identity")
        source = {
            "source_ids": list(chunk.source_ids), "unit_ids": list(chunk.unit_ids),
            "structure_path": list(chunk.structure_path), "body_span": chunk.body_span,
            "alignment": chunk.alignment, "diagnostics": list(chunk.diagnostics),
            "business_id": chunk.business_id, "upstream_version": chunk.version,
            "order": chunk.order, "strategy": chunk.strategy,
            "count_mode": chunk.count_mode, "count": chunk.count,
            "requires_review": chunk.requires_review, "projected_context": chunk.projected_context,
            # Upstream IDs describe provenance only; they do not invent revisions.
            "parent_chunk_id": chunk.parent_chunk_id, "child_chunk_ids": list(chunk.child_chunk_ids),
        }
        if not chunk.source_ids and not chunk.unit_ids:
            raise RetrievalContractError("chunk handoff requires source_ids or unit_ids")
        return cls(identity, chunk.text, json_copy(source), chunk.metadata, parent)

    def to_chunk_record(self) -> ChunkRecord:
        """Module3 encoding input; KB qualification remains the retrieval adapter's duty.

        Module3's LogicalIndexIdentity omits KB, so callers must not share an
        unqualified vector namespace between KBs just because this metadata exists.
        """
        metadata = json_copy(self.metadata)
        metadata.update(knowledge_base_id=self.identity.knowledge_base_id,
                        source=json_copy(self.source),
                        parent_identity=self.parent.key if self.parent else None)
        return ChunkRecord(self.identity.chunk_id, self.identity.document_id,
                           self.identity.document_version, self.text, metadata,
                           self.identity.chunk_version)


@dataclass(frozen=True)
class AuthorizationScope:
    """Caller-confirmed KB grants, optionally narrowed to document IDs per KB.

    An absent document restriction means all documents in that granted KB;
    an explicit empty tuple grants none. Conditions can only narrow these grants.
    """
    knowledge_base_ids: tuple[str, ...]
    document_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self):
        from types import MappingProxyType
        ids = tuple(self.knowledge_base_ids)
        required_strings(*ids)
        documents = {kb: tuple(values) for kb, values in self.document_ids.items()}
        if set(documents) - set(ids):
            raise RetrievalContractError("document authorization refers to an ungranted knowledge base")
        for values in documents.values():
            required_strings(*values)
        object.__setattr__(self, "knowledge_base_ids", ids)
        object.__setattr__(self, "document_ids", MappingProxyType(documents))


@dataclass(frozen=True)
class Snapshot:
    knowledge_base_id: str
    snapshot_id: str
    identities: tuple[EvidenceIdentity, ...]
    required_indexes: tuple[str, ...]
    field_types: Mapping[str, str]


@dataclass(frozen=True)
class ReadScope:
    """A pinned set of published snapshots and one fixed timezone-aware instant."""
    snapshots: Mapping[str, str]
    authorization: AuthorizationScope
    conditions: object
    now: datetime

    def __post_init__(self):
        from types import MappingProxyType
        if not isinstance(self.authorization, AuthorizationScope):
            raise RetrievalContractError("authorization is required")
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise RetrievalContractError("query time must be timezone-aware")
        if set(self.snapshots) - set(self.authorization.knowledge_base_ids):
            raise RetrievalContractError("requested knowledge base is outside authorization")
        object.__setattr__(self, "snapshots", MappingProxyType(dict(self.snapshots)))
