"""区分编码角色的同步 Embedding 与版本化向量索引 API。"""
from .batching import (
    EmbeddedItem, EmbeddingBatchResult, LongInputPolicy, PreparedInput,
    embed_texts, prepare_long_inputs, retry_failed, resolve_unknown, validate_query_vector,
)
from .contracts import (
    ChunkRecord, SearchHit, ContentFingerprintConflict, LogicalIndexIdentity,
    DeterministicEmbeddingAdapter, EmbeddingAdapter, EmbeddingContractError,
    EmbeddingMetadata, EmbeddingRoleConfig, IndexSchemeVersion, content_fingerprint,
)
from .flow import (
    EmbeddingQueryError, index_chunks, search_chunks, resolve_index_requests,
    adjudicate_index_request, resolve_query_request, search_serving_chunks,
)
from .lifecycle import IndexItemState, InvalidLifecycleTransition
from .migration import (
    ActiveSchemeDeletionError, InMemoryIndexRegistry, IndexValidationError, ValidationReport,
)
from .ports import VectorStore, RequestRepository
from .requests import (
    BatchRequest, RequestState, ProviderOutcome, ProviderError, UnknownResolution,
    RequestAdapter,
)
from .scheduling import LocalRateLimiter, QuotaCapacityExceeded, QuotaWaitExceeded
# 为现有调用方保留兼容入口；应用流程本身依赖存储协议。
from .postgres import (
    PostgresVectorStore, PhysicalIndexConfig, RequestAttempt,
    DuplicateRequestAttempt, FingerprintConflict,
)

__all__ = [
    "EmbeddingAdapter", "DeterministicEmbeddingAdapter", "EmbeddingContractError",
    "EmbeddingMetadata", "EmbeddingRoleConfig", "IndexSchemeVersion", "content_fingerprint",
    "ContentFingerprintConflict", "ChunkRecord", "SearchHit", "LogicalIndexIdentity",
    "EmbeddedItem", "EmbeddingBatchResult", "LongInputPolicy", "PreparedInput",
    "embed_texts", "prepare_long_inputs", "retry_failed", "resolve_unknown", "validate_query_vector",
    "resolve_query_request", "search_serving_chunks",
    "index_chunks", "search_chunks", "resolve_index_requests", "adjudicate_index_request", "EmbeddingQueryError",
    "IndexItemState", "InvalidLifecycleTransition", "InMemoryIndexRegistry", "ValidationReport",
    "IndexValidationError", "ActiveSchemeDeletionError", "VectorStore", "RequestRepository",
    "BatchRequest", "RequestState", "ProviderOutcome", "ProviderError", "UnknownResolution", "RequestAdapter",
    "LocalRateLimiter", "QuotaCapacityExceeded", "QuotaWaitExceeded",
    "PostgresVectorStore", "PhysicalIndexConfig", "RequestAttempt", "DuplicateRequestAttempt", "FingerprintConflict",
]
