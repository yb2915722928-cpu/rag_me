"""Synchronous Embedding and versioned indexing contracts."""

from .batching import EmbeddedItem, EmbeddingBatchResult, embed_texts, retry_failed
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
    "embed_texts", "retry_failed",
]
