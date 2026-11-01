"""索引条目的生命周期；结果未知的请求必须显式确认。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from app.models.embedding import LogicalIndexIdentity


class InvalidLifecycleTransition(ValueError):
    pass


@dataclass(frozen=True)
class IndexItemState:
    document_id: str
    document_version: str
    chunk_id: str
    scheme_identity: str
    status: str
    chunk_version: str
    error_code: str | None = None
    error_reason: str | None = None
    retry_count: int = 0
    updated_at: datetime | None = None

    _allowed = {
        "pending": {"embedded", "failed", "retryable", "unknown", "deleted"},
        "embedded": {"stored", "failed", "deleted"},
        "stored": {"deleted"},
        "failed": {"deleted"},
        "retryable": {"pending", "deleted"},
        "unknown": {"embedded", "failed", "retryable", "deleted"},
        "deleted": set(),
    }

    def __post_init__(self) -> None:
        if self.status not in self._allowed:
            raise InvalidLifecycleTransition(f"unknown index item status: {self.status}")
        self.identity

    @property
    def identity(self) -> LogicalIndexIdentity:
        return LogicalIndexIdentity(self.document_id, self.document_version, self.chunk_id,
                                    self.scheme_identity, self.chunk_version)

    @property
    def searchable(self) -> bool:
        return self.status == "stored"

    def transition(self, status: str) -> IndexItemState:
        if status not in self._allowed[self.status]:
            raise InvalidLifecycleTransition(f"cannot transition {self.status} to {status}")
        if self.status == "unknown":
            raise InvalidLifecycleTransition("unknown items require explicit resolution")
        return replace(self, status=status, updated_at=datetime.now(timezone.utc))

    def resolve_unknown(self, status: str) -> IndexItemState:
        if self.status != "unknown" or status not in {"embedded", "failed", "retryable"}:
            raise InvalidLifecycleTransition("only an unknown request can be explicitly resolved")
        return replace(self, status=status, updated_at=datetime.now(timezone.utc))

    @classmethod
    def from_failure(cls, identity: LogicalIndexIdentity, error_code: str, reason: str,
                     *, retryable: bool = False) -> IndexItemState:
        return cls(identity.document_id, identity.document_version, identity.chunk_id,
                   identity.scheme_identity, "retryable" if retryable else "failed",
                   identity.chunk_version, error_code, reason, updated_at=datetime.now(timezone.utc))

    def retry(self) -> IndexItemState:
        if self.status != "retryable":
            raise InvalidLifecycleTransition("only explicitly retryable items can be retried")
        return replace(self.transition("pending"), retry_count=self.retry_count + 1,
                       error_code=None, error_reason=None)
