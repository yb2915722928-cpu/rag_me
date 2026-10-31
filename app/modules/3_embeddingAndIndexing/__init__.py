"""Synchronous Embedding and versioned indexing contracts."""

from .batching import EmbeddedItem, EmbeddingBatchResult, embed_texts, retry_failed
from .postgres import ChunkRecord, PostgresVectorStore, SearchHit
from .lifecycle import IndexItemState, InvalidLifecycleTransition, LogicalIndexIdentity
from .contracts import (
    DeterministicEmbeddingAdapter,
    EmbeddingAdapter,
    EmbeddingContractError,
    EmbeddingMetadata,
    IndexSchemeVersion,
)

__all__ = [
    "DeterministicEmbeddingAdapter", "EmbeddingAdapter", "EmbeddingContractError",
    "EmbeddingMetadata", "IndexSchemeVersion", "EmbeddedItem", "EmbeddingBatchResult",
    "embed_texts", "retry_failed", "ChunkRecord", "PostgresVectorStore", "SearchHit",
    "IndexItemState", "InvalidLifecycleTransition", "LogicalIndexIdentity",
]
