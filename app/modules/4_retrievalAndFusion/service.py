"""Synchronous public query boundary over pinned, authorized retrieval routes."""
from __future__ import annotations

from dataclasses import replace
from math import isfinite

from .contracts import AuthorizationScope, ContentRecord, RetrievalContractError, required_strings
from .fusion import fuse_rrf
from .fusion_contracts import PostprocessStep, RetrievalConfig, RetrievalResult, RetrievalRoute, RouteHit, RouteResult
from .parent_expansion import expand_parents


class RetrievalService:
    def __init__(self, store, *, routes=None):
        self.store = store
        self.routes = None if routes is None else tuple(routes)

    def query(self, query: str, *, knowledge_base_ids, authorization, conditions=None,
              snapshot_ids=None, config: RetrievalConfig | None = None, exact_terms=(),
              remaining=None) -> RetrievalResult:
        required_strings(query)
        config = RetrievalConfig() if config is None else config
        if not isinstance(config, RetrievalConfig):
            raise RetrievalContractError("config must be RetrievalConfig")
        if not isinstance(authorization, AuthorizationScope):
            raise RetrievalContractError("authorization is required")
        knowledge_base_ids = tuple(dict.fromkeys(knowledge_base_ids))
        required_strings(*knowledge_base_ids)
        if not knowledge_base_ids:
            raise RetrievalContractError("at least one knowledge base is required")
        if set(knowledge_base_ids) - set(authorization.knowledge_base_ids):
            raise RetrievalContractError("requested knowledge base is outside authorization")
        exact_terms = tuple(exact_terms)
        required_strings(*exact_terms)
        routes = self._routes(knowledge_base_ids)
        route_ids = [route.route_id for route in routes]
        if len(set(route_ids)) != len(route_ids):
            raise RetrievalContractError("route IDs must be unique")
        if set(config.route_weights) - set(route_ids):
            raise RetrievalContractError("route weight refers to an unrequested route")
        scope = self.store.pin(knowledge_base_ids, authorization=authorization,
                               conditions=conditions, snapshot_ids=snapshot_ids)
        results = tuple(self._execute(route, query, scope, config, exact_terms) for route in routes)
        pool = fuse_rrf(results, config)
        completed = sum(result.status in ("success", "empty") for result in results)
        status = "complete" if completed == len(results) and completed else "partial" if completed else "incomplete"
        parent = expand_parents(pool, store=self.store, scope=scope,
                                enabled=config.parent_expansion, strict=config.postprocess_strict,
                                remaining=remaining)
        if parent.step.status == "failed":
            # Keep route diagnostics and the compliant input pool on strict failure.
            steps = (parent.step, PostprocessStep("dedup", "skipped", "prior_stage_failed"),
                     PostprocessStep("mmr", "skipped", "prior_stage_failed"))
            return RetrievalResult(status, (), pool, results, scope, steps)
        pool = parent.candidates
        # Later optional stages consume this full pool before the final cut.
        steps = (parent.step, PostprocessStep("dedup", "skipped", "disabled"),
                 PostprocessStep("mmr", "skipped", "disabled"))
        return RetrievalResult(status, pool[:config.final_top_k], pool, results, scope, steps)

    def _routes(self, knowledge_base_ids):
        if self.routes is None:
            return tuple(self._backend_route(kb, method) for kb in knowledge_base_ids
                         for method in ("vector", "bm25"))
        selected = tuple(route for route in self.routes if route.knowledge_base_id in knowledge_base_ids)
        if set(knowledge_base_ids) - {route.knowledge_base_id for route in selected}:
            raise RetrievalContractError("every requested knowledge base requires a retrieval route")
        return selected

    def _backend_route(self, knowledge_base_id, method):
        """Adapt the real snapshot backends without interpreting their raw scores."""
        route_id = f"{knowledge_base_id}:{method}"

        def search(query, *, scope, top_k, exact_terms):
            options = {"knowledge_base_id": knowledge_base_id, "scope": scope, "top_k": top_k}
            if method == "bm25":
                options["exact_terms"] = exact_terms
            result = getattr(self.store, f"search_{method}")(query, **options)
            successful = result.status in ("success", "empty")
            hits = tuple(RouteHit(hit.content, hit.snapshot_id, hit.raw_score, hit.metric, hit.scheme_identity)
                         for hit in result.candidates) if successful else ()
            return RouteResult(route_id, knowledge_base_id, method, result.status, hits,
                               algorithm=result.algorithm,
                               candidate_limit=getattr(result, "candidate_limit", top_k),
                               limitations=result.limitations,
                               reason=None if successful else "route_execution_failed")

        return RetrievalRoute(route_id, knowledge_base_id, method, search)

    @staticmethod
    def _execute(route, query, scope, config, exact_terms):
        try:
            result = route.search(query, scope=scope, top_k=config.route_top_k, exact_terms=exact_terms)
            if not isinstance(result, RouteResult) or (
                    result.route_id, result.knowledge_base_id, result.method) != (
                    route.route_id, route.knowledge_base_id, route.method):
                raise RetrievalContractError("route result does not match its requested route")
            if result.status not in ("success", "empty", "failed", "timeout", "not_executed"):
                raise RetrievalContractError("unknown route status")
            if result.status not in ("success", "empty"):
                return replace(result, candidates=())
            if (result.status == "success") != bool(result.candidates):
                raise RetrievalContractError("route status and candidates disagree")
            for hit in result.candidates:
                if not isinstance(hit.content, ContentRecord):
                    raise RetrievalContractError("route requires authoritative content")
                if (hit.content.identity.knowledge_base_id != route.knowledge_base_id
                        or hit.snapshot_id != scope.snapshots[route.knowledge_base_id]):
                    raise RetrievalContractError("route returned evidence outside its pinned scope")
                documents = scope.authorization.document_ids.get(route.knowledge_base_id)
                if documents is not None and hit.content.identity.document_id not in documents:
                    raise RetrievalContractError("route returned evidence outside authorization")
                if (isinstance(hit.raw_score, bool) or not isinstance(hit.raw_score, (float, int))
                        or not isfinite(hit.raw_score) or not isinstance(hit.metric, str) or not hit.metric):
                    raise RetrievalContractError("route scores require a finite value and declared metric")
            return replace(result, candidates=tuple(result.candidates))
        except Exception:
            # Do not expose backend errors containing query text, content or credentials.
            return RouteResult(route.route_id, route.knowledge_base_id, route.method,
                               "failed", reason="route_execution_failed")
