"""Synchronous retrieval library: authoritative ingestion, snapshots and safe reads."""
from .contracts import (
    AuthorizationScope, ContentConflict, ContentRecord, EvidenceIdentity, ReadScope,
    RetrievalContractError, Snapshot, SnapshotNotReady,
)
from .filters import All, Eq
from .postgres import PostgresRetrievalStore
from .fusion_contracts import (
    FusedCandidate, PostprocessStep, RetrievalConfig, RetrievalResult, RetrievalRoute,
    RouteHit, RouteResult, ScoreTrace,
)
from .body_dedup import BodyDedupProof, BodyDedupProver, process_body_dedup
from .service import RetrievalService
from .typed_filters import FilterPlan, FilterValidationError, compile_filter
from .vector import PostgresVectorRetrievalStore, VectorCandidate, VectorQueryResult
from .bm25 import BM25Analyzer, BM25Candidate, BM25QueryResult
from .bm25_postgres import PostgresBM25RetrievalStore
from .faq_contracts import FAQIdentity, FAQRecord, MatchedQuestion
from .faq_postgres import PostgresFAQRetrievalStore
from .faq_vector import FAQVectorCandidate
from .faq_bm25 import FAQBM25Analyzer, FAQBM25Candidate, FAQBM25QueryResult
from .faq_bm25_postgres import PostgresFAQBM25RetrievalStore

__all__ = [
    "AuthorizationScope", "ContentConflict", "ContentRecord", "EvidenceIdentity",
    "ReadScope", "RetrievalContractError", "Snapshot", "SnapshotNotReady",
    "All", "Eq", "PostgresRetrievalStore", "FilterPlan", "FilterValidationError", "compile_filter",
    "FusedCandidate", "PostprocessStep", "RetrievalConfig", "RetrievalResult", "RetrievalRoute",
    "RouteHit", "RouteResult", "ScoreTrace", "RetrievalService",
    "BodyDedupProof", "BodyDedupProver", "process_body_dedup",
    "PostgresVectorRetrievalStore", "VectorCandidate", "VectorQueryResult",
    "PostgresBM25RetrievalStore", "BM25Analyzer", "BM25Candidate", "BM25QueryResult",
    "FAQIdentity", "FAQRecord", "MatchedQuestion", "PostgresFAQRetrievalStore", "FAQVectorCandidate",
    "FAQBM25Analyzer", "FAQBM25Candidate", "FAQBM25QueryResult", "PostgresFAQBM25RetrievalStore",
]
