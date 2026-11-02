"""Public query acceptance for #90; test-first source, intentionally NOT RUN."""
import importlib
import unittest
from types import SimpleNamespace

from tests.test_retrieval_fusion import PublishedStore, content

r = importlib.import_module("app.modules.4_retrievalAndFusion")


class PublicWeightedFusionTests(unittest.TestCase):
    def setUp(self):
        self.store = PublishedStore()
        self.a, self.b, self.c = content("a"), content("b"), content("c")
        self.store.ingest((self.a, self.b, self.c))
        self.store.publish(self.store.prepare("kb", "s1", (self.a.identity, self.b.identity, self.c.identity)))
        self.scopes = []

    def route(self, route_id, records, *, metric="cosine_similarity", status=None,
              scheme=None, limitations=()):
        def search(query, *, scope, top_k, exact_terms):
            self.scopes.append(scope)
            hits = tuple(r.RouteHit(record, scope.snapshots["kb"], score, metric, scheme)
                         for record, score in records)
            return r.RouteResult(route_id, "kb", "vector", status or ("success" if hits else "empty"),
                                 hits, algorithm="hnsw", candidate_limit=top_k,
                                 limitations=limitations)
        return r.RetrievalRoute(route_id, "kb", "vector", search)

    def query(self, routes, *, config=None, **kwargs):
        return r.RetrievalService(self.store, routes=routes).query(
            "USB-C", knowledge_base_ids=("kb",), authorization=r.AuthorizationScope(("kb",)),
            config=config or r.RetrievalConfig(fusion_strategy="weighted"), **kwargs)

    def test_faq_matched_questions_and_document_evidence_survive_weighted_fusion(self):
        faq = r.FAQRecord(r.FAQIdentity("kb", "usb", "v1"), "支持 USB-C 吗？",
                          ("USB-C 能用吗？",), "支持 USB-C。", {"product": "AX-100"}, {"uri": "faq"})
        questions = (r.MatchedQuestion(faq.standard_question, .9),
                     r.MatchedQuestion(faq.similar_questions[0], .8))
        self.store.ingest((faq,))
        def search(query, *, scope, top_k, exact_terms, remaining):
            remaining.check()
            return r.RouteResult("faq", "kb", "faq_vector", "success", (
                r.RouteHit(faq, scope.snapshots["kb"], .9, "cosine_similarity", "scheme:faq", questions),))
        routes = (r.RetrievalRoute("faq", "kb", "faq_vector", search),
                  self.route("document", [(self.a, .7)]))
        result = self.query(routes)
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.candidates), 2)
        candidate = next(item for item in result.candidates if item.content.identity == faq.identity)
        self.assertEqual(candidate.content.text, faq.answer)
        self.assertEqual(candidate.content.conditions, {"product": "AX-100"})
        self.assertEqual(candidate.traces[0].matched_questions, questions)
        self.assertEqual(candidate.traces[0].normalized_score, 1)
        self.assertEqual(candidate.traces[0].contribution, 1)
        self.assertEqual(candidate.represented_identities, (faq.identity,))
        denied = r.RetrievalService(self.store, routes=routes).query(
            "USB-C", knowledge_base_ids=("kb",),
            authorization=r.AuthorizationScope(("kb",), {"kb": ("manual",)}),
            config=r.RetrievalConfig(fusion_strategy="weighted"))
        self.assertEqual(denied.status, "partial")
        self.assertEqual([item.content.identity for item in denied.candidates], [self.a.identity])
        allowed = r.RetrievalService(self.store, routes=routes).query(
            "USB-C", knowledge_base_ids=("kb",),
            authorization=r.AuthorizationScope(("kb",), {"kb": ()}, {"kb": ("usb",)}),
            config=r.RetrievalConfig(fusion_strategy="weighted"))
        self.assertEqual(allowed.status, "partial")
        self.assertEqual([item.content.identity for item in allowed.candidates], [faq.identity])
        self.assertEqual(allowed.candidates[0].traces[0].matched_questions, questions)

    def test_weighted_fusion_uses_original_budget_and_keeps_route_status_on_expiry(self):
        instant = [0.0]
        budgets = []
        # Public scheduler injection deterministically consumes pin/recall time;
        # no wall-clock sleep or private fusion function mocking is needed.
        class Scheduler:
            capacity = 4
            def run(self, jobs, *, remaining, route_timeout, max_concurrency):
                budgets.append(remaining)
                if len(budgets) == 3:
                    instant[0] = 11.0
                outcomes = []
                for job in jobs:
                    try:
                        remaining.check()
                        value = job(remaining.child(route_timeout))
                        remaining.check()
                        outcomes.append(SimpleNamespace(status="completed", value=value, error=None))
                    except TimeoutError as exc:
                        outcomes.append(SimpleNamespace(status="not_executed", value=None, error=exc))
                return outcomes
        result = r.RetrievalService(self.store, routes=(self.route("v", [(self.a, 3)]),),
                                    scheduler=Scheduler(), clock=lambda: instant[0]).query(
            "USB-C", knowledge_base_ids=("kb",), authorization=r.AuthorizationScope(("kb",)),
            config=r.RetrievalConfig(fusion_strategy="weighted", total_timeout=10))
        self.assertEqual(len(budgets), 3)
        self.assertTrue(all(budget is budgets[0] for budget in budgets))
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.routes[0].status, "success")
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.steps[0].name, "fusion")
        self.assertEqual(result.steps[0].status, "failed")

    def test_switching_strategy_keeps_rrf_default_and_weighted_minmax_trace(self):
        routes = (self.route("v", [(self.a, 4), (self.b, 3), (self.c, 0)], scheme="scheme:one"),
                  self.route("b", [(self.b, 9), (self.a, 2)], metric="bm25", scheme="bm25:analyzer"))
        default = self.query(routes, config=r.RetrievalConfig())
        explicit = self.query(routes, config=r.RetrievalConfig(fusion_strategy="rrf"))
        self.assertEqual(default.candidates, explicit.candidates)
        self.assertTrue(all(trace.normalized_score is None for item in default.candidates for trace in item.traces))
        result = self.query(routes, config=r.RetrievalConfig(fusion_strategy="weighted", route_weights={"b": 2}))
        self.assertEqual(result.status, "complete")
        self.assertEqual([item.content.identity for item in result.candidates],
                         [self.b.identity, self.a.identity, self.c.identity])
        self.assertEqual([item.score for item in result.candidates], [2.75, 1.0, 0.0])
        trace = result.candidates[0].traces[0]
        self.assertEqual((trace.route_id, trace.knowledge_base_id, trace.method, trace.rank,
                          trace.raw_score, trace.metric, trace.scheme_identity, trace.identity,
                          trace.snapshot_id, trace.weight, trace.normalized_score, trace.contribution),
                         ("b", "kb", "vector", 1, 9, "bm25", "bm25:analyzer", self.b.identity,
                          "s1", 2, 1.0, 2.0))
        self.assertEqual(result.candidates[0].traces[1].normalized_score, .75)

    def test_distance_l2_and_minmax_are_explicitly_selectable(self):
        route = self.route("d", [(self.a, 3), (self.b, 4)], metric="distance")
        result = self.query((route,))
        self.assertEqual([item.score for item in result.candidates], [1.0, 0.0])
        result = self.query((route,), config=r.RetrievalConfig(fusion_strategy="weighted", normalization="l2"))
        self.assertEqual([item.content.identity for item in result.candidates], [self.a.identity, self.b.identity])
        self.assertEqual([item.score for item in result.candidates], [-.6, -.8])
        self.assertEqual(result.candidates[0].traces[0].metric, "distance")
        self.assertEqual(result.candidates[0].traces[0].raw_score, 3)

    def test_equal_and_singleton_diagnostics_preserve_backend_limitations(self):
        for records in ([(self.a, 4)], [(self.b, 0), (self.a, 0)]):
            result = self.query((self.route("v", records, limitations=("approximate_recall",)),))
            self.assertEqual(result.routes[0].limitations, ("approximate_recall", "no_discrimination"))
            self.assertEqual(result.routes[0].algorithm, "hnsw")
            self.assertEqual(result.routes[0].candidate_limit, 50)
            self.assertTrue(all(item.score == 1 for item in result.candidates))
            self.assertEqual(result.candidates[0].content.identity, self.a.identity)
        result = self.query((self.route("v", [(self.b, 0), (self.a, 0)]),),
                            config=r.RetrievalConfig(fusion_strategy="weighted", normalization="l2"))
        self.assertEqual([item.score for item in result.candidates], [0.0, 0.0])
        self.assertEqual(result.routes[0].limitations, ())

    def test_invalid_route_scores_fail_with_diagnostics_and_no_weight_redistribution(self):
        for score, metric, reason in ((float("nan"), "bm25", "invalid_score"),
                                      (float("inf"), "bm25", "invalid_score"),
                                      (-float("inf"), "bm25", "invalid_score"),
                                      (1, "unknown", "unknown_metric"),
                                      (1, "", "unknown_metric"),
                                      (1, None, "unknown_metric")):
            with self.subTest(score=score, metric=metric):
                routes = (self.route("good", [(self.a, 2)]),
                          self.route("bad", [(self.b, 3), (self.a, score)], metric=metric,
                                     limitations=("backend_limit",)))
                result = self.query(routes, config=r.RetrievalConfig(fusion_strategy="weighted",
                                    route_weights={"good": .25, "bad": .75}))
                self.assertEqual(result.status, "partial")
                self.assertEqual(len(result.candidates), 1)
                self.assertEqual(result.candidates[0].score, .25)
                self.assertEqual(result.routes[1].status, "failed")
                self.assertEqual(result.routes[1].reason, reason)
                self.assertEqual(result.routes[1].limitations, ("backend_limit", reason))
                self.assertEqual(result.routes[1].candidates, ())
                self.assertEqual(len(result.candidates[0].traces), 1)
                failed = self.query((routes[1],))
                self.assertEqual(failed.status, "incomplete")
                self.assertEqual(failed.candidates, ())

    def test_missing_hits_and_failed_paths_contribute_zero_without_redistribution(self):
        routes = (self.route("good", [(self.a, 4), (self.b, 0)]),
                  self.route("only-b", [(self.b, 1)]),
                  self.route("bad", [(self.c, 9)], status="failed"),
                  self.route("empty", []))
        result = self.query(routes, config=r.RetrievalConfig(fusion_strategy="weighted",
                            route_weights={"good": 2, "only-b": .5, "bad": 10}))
        self.assertEqual(result.status, "partial")
        self.assertEqual([item.score for item in result.candidates], [2, .5])
        self.assertEqual([trace.route_id for trace in result.candidates[0].traces], ["good"])
        self.assertEqual(result.routes[2].candidates, ())
        self.assertEqual(result.routes[3].status, "empty")
        empty = self.query((self.route("empty", []),))
        self.assertEqual((empty.status, empty.candidates), ("complete", ()))

    def test_identity_merge_duplicate_ranks_stable_ties_and_independent_limits(self):
        routes = (self.route("one", [(self.a, 9), (self.a, 8), (self.b, 3)], scheme="one"),
                  self.route("two", [(self.b, 7), (self.a, 1)], scheme="two"))
        config = r.RetrievalConfig(fusion_strategy="weighted", route_top_k=2, pool_size=2, final_top_k=1)
        result = self.query(routes, config=config)
        reversed_result = self.query(tuple(reversed(routes)), config=config)
        self.assertEqual(result.candidates, reversed_result.candidates)
        self.assertEqual(len(result.working_pool), 2)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].content.identity, self.a.identity)
        self.assertEqual(result.candidates[0].score, 1)
        self.assertEqual([trace.rank for trace in result.candidates[0].traces], [1, 2])
        self.assertEqual([trace.scheme_identity for trace in result.candidates[0].traces], ["one", "two"])
        self.assertEqual([trace.rank for trace in result.working_pool[1].traces], [2, 1])
        self.assertEqual(result.candidates[0].represented_identities, (self.a.identity,))
        self.assertEqual(result.candidates[0].sources, (self.a.source,))
        limited = self.query(routes, config=r.RetrievalConfig(fusion_strategy="weighted", pool_size=1))
        self.assertEqual(len(limited.working_pool), 1)
        zero = self.query(routes, config=r.RetrievalConfig(fusion_strategy="weighted",
                          route_weights={"one": 0, "two": 0}))
        self.assertEqual([item.score for item in zero.candidates], [0, 0])

    def test_distinct_versions_and_sources_remain_distinct_even_with_equal_text(self):
        records = [self.a, content("a", doc="other"), content("a", version="v2"),
                   content("a", chunk_version="c2")]
        self.store.ingest(records)
        result = self.query((self.route("v", [(record, 1) for record in reversed(records)]),))
        self.assertEqual([item.content.identity for item in result.candidates],
                         sorted(record.identity for record in records))
        self.assertTrue(all(len(item.traces) == 1 for item in result.candidates))

    def test_pinned_scope_filters_and_authorization_still_apply(self):
        conditions = {"product": "AX-100"}
        routes = (self.route("v", [(self.a, 3)]), self.route("b", [(self.a, 5)]))
        result = self.query(routes, conditions=conditions, snapshot_ids={"kb": "history"})
        self.assertEqual(len(self.store.calls), 1)
        self.assertIs(result.scope.conditions, conditions)
        self.assertTrue(all(scope is result.scope for scope in self.scopes))
        self.assertTrue(all(trace.snapshot_id == "history" for trace in result.candidates[0].traces))
        denied = r.RetrievalService(self.store, routes=routes).query(
            "USB-C", knowledge_base_ids=("kb",), authorization=r.AuthorizationScope(("kb",), {"kb": ()}),
            config=r.RetrievalConfig(fusion_strategy="weighted"))
        self.assertEqual((denied.status, denied.candidates), ("incomplete", ()))

    def test_invalid_duplicate_or_excess_hit_cannot_be_hidden_by_truncation(self):
        for record in (self.a, self.b):
            result = self.query((self.route("v", [(self.a, 3), (record, float("nan"))]),),
                                config=r.RetrievalConfig(fusion_strategy="weighted", route_top_k=1))
            self.assertEqual((result.status, result.candidates), ("incomplete", ()))
            self.assertEqual(result.routes[0].reason, "invalid_score")

    def test_mixed_metrics_fail_one_route_instead_of_combining_unrelated_scales(self):
        def search(query, *, scope, top_k, exact_terms):
            return r.RouteResult("mixed", "kb", "vector", "success", (
                r.RouteHit(self.a, scope.snapshots["kb"], .8, "cosine_similarity"),
                r.RouteHit(self.b, scope.snapshots["kb"], 8, "bm25")))
        result = self.query((r.RetrievalRoute("mixed", "kb", "vector", search),))
        self.assertEqual((result.status, result.candidates), ("incomplete", ()))
        self.assertEqual(result.routes[0].reason, "mixed_metrics")

    def test_bad_configuration_is_rejected_before_routes_or_snapshot_reads(self):
        for options in ({"fusion_strategy": "typo"}, {"normalization": "probability"},
                        {"route_weights": {"v": -1}}, {"route_weights": {"v": float("nan")}},
                        {"fusion_strategy": "weighted", "route_weights": {"a": 1e308, "b": 1e308}}):
            with self.subTest(options=options), self.assertRaises(r.RetrievalContractError):
                r.RetrievalConfig(**options)
        with self.assertRaises(r.RetrievalContractError):
            self.query((self.route("v", []),), config=r.RetrievalConfig(
                fusion_strategy="weighted", route_weights={"typo": 1}))
        self.assertEqual(self.store.calls, [])
        self.assertEqual(self.scopes, [])
