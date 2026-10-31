"""Explicit index item lifecycle and compensating retry state."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone


class InvalidLifecycleTransition(ValueError):
    pass


@dataclass(frozen=True)
class LogicalIndexIdentity:
    document_id: str
    document_version: str
    chunk_id: str
    scheme_identity: str

    @property
    def key(self) -> str:
        return "|".join((self.document_id, self.document_version, self.chunk_id, self.scheme_identity))


@dataclass(frozen=True)
class IndexItemState:
    document_id: str
    document_version: str
    chunk_id: str
    scheme_identity: str
    status: str
    error_code: str | None = None
    error_reason: str | None = None
    retry_count: int = 0
    updated_at: datetime | None = None

    _allowed = {
        "pending": {"embedded", "failed", "deleted"},
        "embedded": {"stored", "failed", "deleted"},
        "stored": {"deleted", "failed"},
        "failed": {"pending", "deleted"},
        "deleted": set(),
    }

    @property
    def identity(self) -> LogicalIndexIdentity:
        return LogicalIndexIdentity(self.document_id, self.document_version, self.chunk_id, self.scheme_identity)

    @property
    def searchable(self) -> bool:
        return self.status == "stored"

    def transition(self, status: str) -> "IndexItemState":
        if status not in self._allowed:
            raise InvalidLifecycleTransition(f"unknown index item status: {status}")
        if status not in self._allowed[self.status]:
            raise InvalidLifecycleTransition(f"cannot transition {self.status} to {status}")
        return replace(self, status=status, updated_at=datetime.now(timezone.utc))

    @classmethod
    def from_failure(cls, identity: LogicalIndexIdentity, error_code: str, reason: str) -> "IndexItemState":
        return cls(*identity.__dict__.values(), "failed", error_code, reason, 0, datetime.now(timezone.utc))

    def retry(self) -> "IndexItemState":
        if self.status != "failed":
            raise InvalidLifecycleTransition("only failed items can be retried")
        return replace(self.transition("pending"), retry_count=self.retry_count + 1, error_code=None, error_reason=None)
