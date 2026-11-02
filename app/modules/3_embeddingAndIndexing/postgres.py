"""兼容旧接口的导入；PostgreSQL 持久化实现位于 app.models.db。"""
from app.models.embedding import ChunkRecord, SearchHit
from app.models.db.pgvector import (
    PostgresVectorStore, PhysicalIndexConfig, RequestAttempt,
    DuplicateRequestAttempt, FingerprintConflict,
)

__all__ = ["ChunkRecord", "SearchHit", "PostgresVectorStore", "PhysicalIndexConfig",
           "RequestAttempt", "DuplicateRequestAttempt", "FingerprintConflict"]
