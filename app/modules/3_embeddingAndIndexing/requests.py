"""与提供方无关的请求身份，以及调用边界上的明确结果分类。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence


class RequestState(str, Enum):
    EMBEDDED = "embedded"
    FAILED = "failed"
    RETRYABLE = "retryable"
    UNKNOWN = "unknown"


class ProviderOutcome(str, Enum):
    FAILED = "failed"
    RETRYABLE = "retryable"
    UNKNOWN = "unknown"


class ProviderError(Exception):
    """提供方适配器显式分类错误；unknown 状态绝不自动重试。"""

    def __init__(self, outcome: ProviderOutcome | str, code: str, message: str, *,
                 request_id: str | None = None, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.outcome = ProviderOutcome(outcome)
        self.code = code
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class BatchRequest:
    request_id: str
    idempotency_key: str
    keys: tuple[str, ...]
    texts: tuple[str, ...]
    prepared_texts: tuple[str, ...]
    role: str
    fingerprints: tuple[str, ...]
    fingerprint_algorithm: str
    scheme_identity: str

    def __post_init__(self):
        for name in ("keys", "texts", "prepared_texts", "fingerprints"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.keys or len(set(self.keys)) != len(self.keys):
            raise ValueError("request keys must be nonempty and unique")
        if any(len(getattr(self, name)) != len(self.keys) for name in ("texts", "prepared_texts", "fingerprints")):
            raise ValueError("request identities and inputs must have matching counts")
        if self.role not in {"document", "query"}:
            raise ValueError("request role must be document or query")
        values = (self.request_id, self.idempotency_key, self.fingerprint_algorithm, self.scheme_identity, *self.keys, *self.fingerprints)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("request identity fields must be nonempty strings")
        if any(not isinstance(text, str) for text in (*self.texts, *self.prepared_texts)):
            raise ValueError("request inputs must be strings")


@dataclass(frozen=True)
class UnknownResolution:
    state: RequestState
    request_id: str
    idempotency_key: str
    keys: tuple[str, ...]
    fingerprints: tuple[str, ...]
    vectors: Sequence[Sequence[float]] | None = None
    error_code: str | None = None
    reason: str | None = None


class RequestAdapter(Protocol):
    """可选能力；基础适配器仅需实现 embed_role(texts, role)。"""

    supports_request_metadata: bool
    supports_status_query: bool

    # Deadline-capable providers must apply remaining.remaining() to network
    # connect/read timeouts and check cancellation between chunks/retries.
    supports_deadline: bool

    def embed_request(self, request: BatchRequest, *, remaining=None) -> Sequence[Sequence[float]]: ...

    def resolve_request(self, request: BatchRequest) -> UnknownResolution: ...


def classify_provider_error(adapter, error: Exception) -> ProviderError:
    if isinstance(error, TimeoutError):
        return ProviderError(ProviderOutcome.UNKNOWN, "EMBEDDING_TIMEOUT", str(error),
                             request_id=getattr(error, "request_id", None))
    if isinstance(error, ProviderError):
        return error
    if getattr(adapter, "supports_error_mapping", False):
        mapped = adapter.map_error(error)
        if not isinstance(mapped, ProviderError):
            raise TypeError("adapter.map_error must return ProviderError")
        return mapped
    return ProviderError(ProviderOutcome.FAILED, "EMBEDDING_FAILED", str(error))
