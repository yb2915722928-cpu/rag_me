"""Storage seams used by the synchronous application flow."""
from __future__ import annotations

from typing import Any, Protocol, Sequence
from datetime import datetime

from app.models.embedding import ChunkRecord, IndexSchemeVersion, LogicalIndexIdentity, SearchHit


class VectorStore(Protocol):
    def upsert(self, scheme: IndexSchemeVersion, chunk: ChunkRecord,
               vector: Sequence[float], *, content_fingerprint: str,
               fingerprint_algorithm: str, generated_at: datetime | None = None) -> None: ...

    def search(self, scheme: IndexSchemeVersion, vector: Sequence[float], *,
               limit: int = 10, **options: Any) -> list[SearchHit]: ...


class RequestRepository(Protocol):
    def reserve_batch_attempts(self, identities: Sequence[LogicalIndexIdentity],
                               fingerprints: Sequence[str], *, request_payload: dict) -> Sequence[Any]: ...

    def resolve_attempt(self, attempt_id: str, status: str, *,
                        request_id: str | None = None, error: str | None = None,
                        result_payload: dict | None = None,
                        request_payload: dict | None = None) -> None: ...

    def get_attempt_for_identity(self, identity: LogicalIndexIdentity) -> Any: ...

    def retry_attempt(self, attempt_id: str, *, request_payload: dict) -> Any: ...
