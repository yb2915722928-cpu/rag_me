"""Compatibility imports. PostgreSQL persistence lives in app.models.db."""
from app.models.embedding import ChunkRecord, SearchHit
from app.models.db.pgvector import (
    PostgresVectorStore, PhysicalIndexConfig, RequestAttempt,
    DuplicateRequestAttempt, FingerprintConflict,
)

__all__ = ["ChunkRecord", "SearchHit", "PostgresVectorStore", "PhysicalIndexConfig",
           "RequestAttempt", "DuplicateRequestAttempt", "FingerprintConflict"]
