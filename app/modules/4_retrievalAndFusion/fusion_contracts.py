"""Public query results and route inputs; scores are not correctness probabilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import fsum, isfinite
from types import MappingProxyType
from typing import Callable, Literal, Mapping

from .contracts import ContentRecord, EvidenceIdentity, ReadScope, RetrievalContractError, required_strings
from .faq_contracts import FAQIdentity, FAQRecord, MatchedQuestion

RouteStatus = Literal["success", "empty", "failed", "timeout", "not_executed"]
QueryStatus = Literal["complete", "partial", "incomplete"]


@dataclass(frozen=True)
class RetrievalConfig:
    route_top_k: int = 50
    pool_size: int = 100
    final_top_k: int = 20
    rrf_k: float = 60
    route_weights: Mapping[str, float] = field(default_factory=dict)
    mmr: bool = False
    mmr_lambda: float = 0.7
    parent_expansion: bool = False
    body_dedup: bool = False
    postprocess_strict: bool = False
    total_timeout: float = 10
    route_timeout: float = 5
    max_concurrency: int = 4
    fusion_strategy: Literal["rrf", "weighted"] = "rrf"
    normalization: Literal["minmax", "l2"] = "minmax"

    def __post_init__(self):
        from .mmr import MMRConfig

        MMRConfig(self.mmr, self.mmr_lambda)
        for name in ("parent_expansion", "body_dedup", "postprocess_strict"):
            if not isinstance(getattr(self, name), bool):
                raise RetrievalContractError(f"{name} must be a boolean")
        if self.fusion_strategy not in ("rrf", "weighted"):
            raise RetrievalContractError("fusion_strategy must be rrf or weighted")
        if self.normalization not in ("minmax", "l2"):
            raise RetrievalContractError("normalization must be minmax or l2")
        for name in ("total_timeout", "route_timeout"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise RetrievalContractError(f"{name} must be finite and positive")
        for name in ("route_top_k", "pool_size", "final_top_k", "max_concurrency"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise RetrievalContractError(f"{name} must be a positive integer")
        if isinstance(self.rrf_k, bool) or not isinstance(self.rrf_k, (int, float)) or not isfinite(self.rrf_k) or self.rrf_k < 0:
            raise RetrievalContractError("rrf_k must be finite and nonnegative")
        weights = dict(self.route_weights)
        for route_id, weight in weights.items():
            required_strings(route_id)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not isfinite(weight) or weight < 0:
                raise RetrievalContractError("route weights must be finite and nonnegative")
        if self.fusion_strategy == "weighted":
            try:
                fsum(weights.values())
            except OverflowError as exc:
                raise RetrievalContractError("combined route weights exceed finite score range") from exc
        object.__setattr__(self, "route_weights", MappingProxyType(weights))


@dataclass(frozen=True)
class RouteHit:
    content: ContentRecord | FAQRecord
    snapshot_id: str
    raw_score: float
    metric: str
    scheme_identity: str | None = None
    matched_questions: tuple[MatchedQuestion, ...] = ()


@dataclass(frozen=True)
class RouteResult:
    route_id: str
    knowledge_base_id: str
    method: str
    status: RouteStatus
    candidates: tuple[RouteHit, ...] = ()
    algorithm: str | None = None
    candidate_limit: int | None = None
    limitations: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class RetrievalRoute:
    """Search returns ranked hits after enforcing the pinned scope, never postfilters top-N.

    The callable accepts (query, *, scope, top_k, exact_terms, remaining) and returns
    a RouteResult. Legacy callbacks may omit remaining and use current_deadline().
    Distinct index-scheme paths need distinct stable route IDs.
    """
    route_id: str
    knowledge_base_id: str
    method: str
    search: Callable

    def __post_init__(self):
        required_strings(self.route_id, self.knowledge_base_id, self.method)
        if not callable(self.search):
            raise RetrievalContractError("route search must be callable")


@dataclass(frozen=True)
class ScoreTrace:
    route_id: str
    knowledge_base_id: str
    method: str
    rank: int
    raw_score: float
    metric: str
    scheme_identity: str | None
    identity: EvidenceIdentity | FAQIdentity
    snapshot_id: str
    weight: float
    contribution: float
    normalized_score: float | None = None
    matched_questions: tuple[MatchedQuestion, ...] = ()


@dataclass(frozen=True)
class FusedCandidate:
    content: ContentRecord | FAQRecord
    score: float
    traces: tuple[ScoreTrace, ...]
    # Postprocessing may represent multiple original sources without discarding provenance.
    represented_identities: tuple[EvidenceIdentity | FAQIdentity, ...] = ()
    sources: tuple[dict, ...] = ()
    matched_children: tuple[ContentRecord, ...] = ()


@dataclass(frozen=True)
class PostprocessStep:
    name: str
    status: Literal["complete", "partial", "failed", "skipped"]
    reason: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    """incomplete means no route completed; complete + empty candidates is a valid empty result."""
    status: QueryStatus
    candidates: tuple[FusedCandidate, ...]
    working_pool: tuple[FusedCandidate, ...]
    routes: tuple[RouteResult, ...]
    scope: ReadScope | None
    steps: tuple[PostprocessStep, ...] = ()
