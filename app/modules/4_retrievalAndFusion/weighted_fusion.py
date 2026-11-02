"""Optional, explicitly directed score normalization for weighted fusion.

Normalized scores are relative retrieval signals, never probabilities. Distance
is negated before normalization so that larger directed scores always rank first.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import math
from typing import Iterable

from .contracts import RetrievalContractError
from .fusion_contracts import FusedCandidate, RetrievalConfig, RouteResult, ScoreTrace


class NormalizationError(RetrievalContractError):
    """A route cannot contribute because its score contract is invalid."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NormalizedScores:
    values: tuple[float, ...]
    diagnostics: tuple[str, ...] = ()


def normalize_scores(scores: Iterable[float], *, metric: str,
                     strategy: str = "minmax") -> NormalizedScores:
    """Normalize one route's unique evidence scores, preserving their order."""
    if strategy not in ("minmax", "l2"):
        raise RetrievalContractError("normalization must be minmax or l2")
    similarities = ("similarity", "cosine_similarity", "bm25")
    distances = ("distance", "cosine_distance")
    if metric not in similarities + distances:
        raise NormalizationError("unknown_metric")
    values = tuple(scores)
    for score in values:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise NormalizationError("invalid_score")
        try:
            finite = math.isfinite(score)
        except OverflowError:
            finite = False
        if not finite:
            raise NormalizationError("invalid_score")
    values = tuple(float(score) for score in values)
    directed = tuple(-score for score in values) if metric in distances else values
    if not directed:
        return NormalizedScores(())
    if strategy == "l2":
        scale = max(abs(score) for score in directed)
        if scale == 0:
            return NormalizedScores((0.0,) * len(directed))
        scaled = tuple(score / scale for score in directed)
        norm = math.sqrt(math.fsum(score * score for score in scaled))
        return NormalizedScores(tuple(score / norm for score in scaled))
    low, high = min(directed), max(directed)
    if low == high:
        return NormalizedScores((1.0,) * len(directed), ("no_discrimination",))
    span = high - low
    if math.isfinite(span):
        return NormalizedScores(tuple((score - low) / span for score in directed))
    # Opposite signed finite extrema can overflow subtraction. Scale only in
    # that case, keeping precision for close non-equal values on normal routes.
    scale = max(abs(low), abs(high))
    scaled_low, scaled_high = low / scale, high / scale
    return NormalizedScores(tuple((score / scale - scaled_low) / (scaled_high - scaled_low)
                                  for score in directed))


def fuse_weighted(routes: tuple[RouteResult, ...], config: RetrievalConfig
                  ) -> tuple[tuple[FusedCandidate, ...], tuple[RouteResult, ...]]:
    """Fuse valid routes and return their diagnostics in original request order.

    Missing evidence contributes zero. Failed routes never donate their weight
    to successful routes. Route order is ranked by the adapter; duplicate
    identities retain the first (best ranked) hit, as in RRF.
    """
    records = {}
    traces = defaultdict(list)
    diagnosed = {}
    for route in sorted(routes, key=lambda item: item.route_id):
        diagnosed[route.route_id] = route
        if route.status != "success":
            continue
        try:
            # Validate the entire returned route, including duplicate and excess
            # hits, so invalid measurements cannot disappear at the pool boundary.
            for hit in route.candidates:
                normalize_scores((hit.raw_score,), metric=hit.metric, strategy=config.normalization)
            if not route.candidates:
                raise NormalizationError("empty_successful_route")
            metric = route.candidates[0].metric
            if any(hit.metric != metric for hit in route.candidates):
                raise NormalizationError("mixed_metrics")
            unique = {}
            for hit in route.candidates:
                unique.setdefault(hit.content.identity, hit)
            hits = tuple(unique.values())[:config.route_top_k]
            normalized = normalize_scores((hit.raw_score for hit in hits), metric=metric,
                                          strategy=config.normalization)
        except NormalizationError as exc:
            diagnosed[route.route_id] = replace(route, status="failed", candidates=(),
                                                reason=exc.code,
                                                limitations=route.limitations + (exc.code,))
            continue
        diagnosed[route.route_id] = replace(route, limitations=route.limitations + normalized.diagnostics)
        weight = config.route_weights.get(route.route_id, 1.0)
        for rank, (hit, score) in enumerate(zip(hits, normalized.values), 1):
            identity = hit.content.identity
            records.setdefault(identity, hit.content)
            traces[identity].append(ScoreTrace(
                route.route_id, route.knowledge_base_id, route.method, rank,
                hit.raw_score, hit.metric, hit.scheme_identity, identity,
                hit.snapshot_id, weight, weight * score, score,
                matched_questions=hit.matched_questions,
            ))
    candidates = [FusedCandidate(records[identity], math.fsum(trace.contribution for trace in evidence),
                                 tuple(evidence), (identity,), (records[identity].source,))
                  for identity, evidence in traces.items()]
    pool = tuple(sorted(candidates, key=lambda item: (-item.score, item.content.identity.parts))[:config.pool_size])
    return pool, tuple(diagnosed[route.route_id] for route in routes)
