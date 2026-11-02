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
from .service import RetrievalService

__all__ = [
    "AuthorizationScope", "ContentConflict", "ContentRecord", "EvidenceIdentity",
    "ReadScope", "RetrievalContractError", "Snapshot", "SnapshotNotReady",
    "All", "Eq", "PostgresRetrievalStore",
    "FusedCandidate", "PostprocessStep", "RetrievalConfig", "RetrievalResult", "RetrievalRoute",
    "RouteHit", "RouteResult", "ScoreTrace", "RetrievalService",
]
