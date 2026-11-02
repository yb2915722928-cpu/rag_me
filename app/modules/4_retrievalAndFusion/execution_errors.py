"""Safe execution diagnostics and explicit recovery of durable query requests."""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib

indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


@dataclass(frozen=True)
class QueryRecovery:
    """Keeps module3's original result out of diagnostics until explicitly resolved."""
    _result: indexing.EmbeddingBatchResult = field(repr=False)

    @property
    def key(self) -> str:
        return self._result.items[0].key

    @property
    def status(self) -> str:
        return self._result.items[0].status

    @property
    def request_id(self) -> str | None:
        return self._result.items[0].request_id

    @property
    def error_code(self) -> str | None:
        return self._result.items[0].error_code

    def resolve(self, adapter, store, *, request_repository=None, limit=10, **search_options):
        """Use the original durable request; callers choose the pinned search store."""
        return indexing.resolve_query_request(self._result, adapter, store,
            request_repository=request_repository, limit=limit, **search_options)


def execution_failure(error: Exception) -> tuple[str, str, QueryRecovery | None]:
    recovery = QueryRecovery(error.result) if isinstance(error, indexing.EmbeddingQueryError) else None
    timed_out = (isinstance(error, TimeoutError)
                 or (recovery is not None and recovery.error_code == "EMBEDDING_TIMEOUT")
                 or (getattr(error, "sqlstate", getattr(error, "pgcode", None)) == "57014"
                     and getattr(getattr(error, "diag", None), "message_primary", None)
                     == "canceling statement due to statement timeout"))
    return ("timeout", "route_timeout", recovery) if timed_out else (
        "failed", "route_execution_failed", recovery)
