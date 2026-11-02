"""Scheme-independent identity fusion, followed by a bounded working pool."""
from __future__ import annotations

from collections import defaultdict
from math import fsum

from .fusion_contracts import FusedCandidate, RetrievalConfig, RouteResult, ScoreTrace
from .deadline import budgeted


def fuse_rrf(routes: tuple[RouteResult, ...], config: RetrievalConfig, *, remaining=None) -> tuple[FusedCandidate, ...]:
    records = {}
    traces = defaultdict(list)
    for route in budgeted(sorted(budgeted(routes, remaining), key=lambda item: item.route_id), remaining):
        if route.status != "success":
            continue
        weight = config.route_weights.get(route.route_id, 1.0)
        seen = set()
        for hit in budgeted(route.candidates, remaining):
            identity = hit.content.identity
            if identity in seen:
                continue
            seen.add(identity)
            rank = len(seen)
            if rank > config.route_top_k:
                break
            records.setdefault(identity, hit.content)
            traces[identity].append(ScoreTrace(
                route.route_id, route.knowledge_base_id, route.method, rank,
                hit.raw_score, hit.metric, hit.scheme_identity, identity,
                hit.snapshot_id, weight, weight / (config.rrf_k + rank),
                matched_questions=hit.matched_questions,
            ))
    candidates = [FusedCandidate(records[identity], fsum(trace.contribution for trace in budgeted(evidence, remaining)),
                                 tuple(evidence), (identity,), (records[identity].source,))
                  for identity, evidence in budgeted(traces.items(), remaining)]

    def rank_key(item):
        if remaining is not None:
            remaining.check()
        return -item.score, item.content.identity.parts

    ranked = sorted(candidates, key=rank_key)
    if remaining is not None:
        remaining.check()
    return tuple(ranked[:config.pool_size])
