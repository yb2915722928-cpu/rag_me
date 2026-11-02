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
from .deadline import budgeted


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
                     strategy: str = "minmax", remaining=None) -> NormalizedScores:
    """Normalize one route's unique evidence scores, preserving their order."""
    if strategy not in ("minmax", "l2"):
        raise RetrievalContractError("normalization must be minmax or l2")
    similarities = ("similarity", "cosine_similarity", "bm25")
    distances = ("distance", "cosine_distance")
    if metric not in similarities + distances:
        raise NormalizationError("unknown_metric")
    values = tuple(budgeted(scores, remaining))
    for score in budgeted(values, remaining):
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise NormalizationError("invalid_score")
        try:
            finite = math.isfinite(score)
        except OverflowError:
            finite = False
        if not finite:
            raise NormalizationError("invalid_score")
    values = tuple(float(score) for score in budgeted(values, remaining))
    directed = tuple(-score for score in budgeted(values, remaining)) if metric in distances else values
    if not directed:
        return NormalizedScores(())
    if strategy == "l2":
        scale = max(abs(score) for score in budgeted(directed, remaining))
        if scale == 0:
            return NormalizedScores((0.0,) * len(directed))
        scaled = tuple(score / scale for score in budgeted(directed, remaining))
        norm = math.sqrt(math.fsum(score * score for score in budgeted(scaled, remaining)))
        return NormalizedScores(tuple(score / norm for score in budgeted(scaled, remaining)))
    low, high = min(budgeted(directed, remaining)), max(budgeted(directed, remaining))
    if low == high:
        return NormalizedScores((1.0,) * len(directed), ("no_discrimination",))
    span = high - low
    if math.isfinite(span):
        return NormalizedScores(tuple((score - low) / span for score in budgeted(directed, remaining)))
    # Opposite signed finite extrema can overflow subtraction. Scale only in
    # that case, keeping precision for close non-equal values on normal routes.
    scale = max(abs(low), abs(high))
    scaled_low, scaled_high = low / scale, high / scale
    return NormalizedScores(tuple((score / scale - scaled_low) / (scaled_high - scaled_low)
                                  for score in budgeted(directed, remaining)))


def fuse_weighted(routes: tuple[RouteResult, ...], config: RetrievalConfig, *, remaining=None
                  ) -> tuple[tuple[FusedCandidate, ...], tuple[RouteResult, ...]]:
    """Fuse valid routes and return their diagnostics in original request order.

    Missing evidence contributes zero. Failed routes never donate their weight
    to successful routes. Route order is ranked by the adapter; duplicate
    identities retain the first (best ranked) hit, as in RRF.
    """
    records = {}
    traces = defaultdict(list)
    diagnosed = {}
    for route in budgeted(sorted(budgeted(routes, remaining), key=lambda item: item.route_id), remaining):
        diagnosed[route.route_id] = route
        if route.status != "success":
            continue
        try:
            # Validate the entire returned route, including duplicate and excess
            # hits, so invalid measurements cannot disappear at the pool boundary.
            for hit in budgeted(route.candidates, remaining):
                normalize_scores((hit.raw_score,), metric=hit.metric, strategy=config.normalization, remaining=remaining)
            if not route.candidates:
                raise NormalizationError("empty_successful_route")
            metric = route.candidates[0].metric
            if any(hit.metric != metric for hit in budgeted(route.candidates, remaining)):
                raise NormalizationError("mixed_metrics")
            unique = {}
            for hit in budgeted(route.candidates, remaining):
                unique.setdefault(hit.content.identity, hit)
            hits = tuple(budgeted(unique.values(), remaining))[:config.route_top_k]
            normalized = normalize_scores((hit.raw_score for hit in hits), metric=metric,
                                          strategy=config.normalization, remaining=remaining)
        except NormalizationError as exc:
            diagnosed[route.route_id] = replace(route, status="failed", candidates=(),
                                                reason=exc.code,
                                                limitations=route.limitations + (exc.code,))
            continue
        diagnosed[route.route_id] = replace(route, limitations=route.limitations + normalized.diagnostics)
        weight = config.route_weights.get(route.route_id, 1.0)
        for rank, (hit, score) in enumerate(budgeted(zip(hits, normalized.values), remaining), 1):
            identity = hit.content.identity
            records.setdefault(identity, hit.content)
            traces[identity].append(ScoreTrace(
                route.route_id, route.knowledge_base_id, route.method, rank,
                hit.raw_score, hit.metric, hit.scheme_identity, identity,
                hit.snapshot_id, weight, weight * score, score,
                matched_questions=hit.matched_questions,
            ))
    candidates = [FusedCandidate(records[identity], math.fsum(trace.contribution for trace in budgeted(evidence, remaining)),
                                 tuple(evidence), (identity,), (records[identity].source,))
                  for identity, evidence in budgeted(traces.items(), remaining)]

    def rank_key(item):
        if remaining is not None:
            remaining.check()
        return -item.score, item.content.identity.parts

    ranked = sorted(candidates, key=rank_key)
    if remaining is not None:
        remaining.check()
    pool = tuple(ranked[:config.pool_size])
    return pool, tuple(diagnosed[route.route_id] for route in budgeted(routes, remaining))
