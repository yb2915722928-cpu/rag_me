"""Small synchronous public orchestration for Chunk indexing and retrieval."""
from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .batching import embed_texts
from .contracts import EmbeddingAdapter, IndexSchemeVersion
from .postgres import SearchHit


def index_chunks(chunks: Sequence[object], adapter: EmbeddingAdapter, store, *, max_batch_size: int = 64, max_tokens: int | None = None, token_counter=None):
    scheme = IndexSchemeVersion(adapter.metadata)
    batch = embed_texts([chunk.text for chunk in chunks], adapter, max_batch_size=max_batch_size, max_tokens=max_tokens, token_counter=token_counter, scheme=scheme)
    indexed = []
    for chunk, item in zip(chunks, batch.items):
        if item.status == "embedded":
            try:
                store.upsert(scheme, chunk, item.vector)
                indexed.append(replace(item, status="stored"))
            except Exception as error:
                indexed.append(replace(item, status="failed", error_code="PERSISTENCE_FAILED", reason=str(error)))
        else:
            indexed.append(item)
    return tuple(indexed)


def search_chunks(query: str, adapter: EmbeddingAdapter, store, *, scheme: IndexSchemeVersion | None = None, limit: int = 10) -> list[SearchHit]:
    selected = scheme or IndexSchemeVersion(adapter.metadata)
    adapter.validate_scheme(selected)
    vector = adapter.embed([query])[0]
    return store.search(selected, vector, limit=limit)
