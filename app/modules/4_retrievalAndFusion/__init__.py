"""Synchronous retrieval library: authoritative ingestion, snapshots and safe reads."""
from .contracts import (
    AuthorizationScope, ContentConflict, ContentRecord, EvidenceIdentity, ReadScope,
    RetrievalContractError, Snapshot, SnapshotNotReady,
)
from .filters import All, Eq
from .postgres import PostgresRetrievalStore
from .typed_filters import FilterPlan, FilterValidationError, compile_filter
from .vector import PostgresVectorRetrievalStore, VectorCandidate, VectorQueryResult
from .bm25 import BM25Analyzer, BM25Candidate, BM25QueryResult
from .bm25_postgres import PostgresBM25RetrievalStore

__all__ = [
    "AuthorizationScope", "ContentConflict", "ContentRecord", "EvidenceIdentity",
    "ReadScope", "RetrievalContractError", "Snapshot", "SnapshotNotReady",
    "All", "Eq", "PostgresRetrievalStore", "FilterPlan", "FilterValidationError", "compile_filter",
    "PostgresVectorRetrievalStore", "VectorCandidate", "VectorQueryResult",
    "PostgresBM25RetrievalStore", "BM25Analyzer", "BM25Candidate", "BM25QueryResult",
]
