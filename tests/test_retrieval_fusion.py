"""Public query behavior for #86. Authored test-first; NOT EXECUTED."""
import importlib
import unittest
from datetime import datetime, timezone

r = importlib.import_module("app.modules.4_retrievalAndFusion")


class PublishedStore:
    """Deterministic external publication boundary, not a production backend."""
    def __init__(self):
        self.records = {}
        self.publications = {}
        self.calls = []

    def ingest(self, records):
        self.records.update((record.identity, record) for record in records)

    def prepare(self, kb, snapshot, identities):
        return (kb, snapshot, tuple(identities))

    def publish(self, prepared):
        kb, snapshot, identities = prepared
        self.publications[kb] = snapshot

    def pin(self, knowledge_base_ids, *, authorization, conditions=None, snapshot_ids=None):
        self.calls.append((tuple(knowledge_base_ids), authorization, conditions))
        snapshots = {kb: (snapshot_ids or {}).get(kb, self.publications[kb]) for kb in knowledge_base_ids}
        return r.ReadScope(snapshots, authorization, conditions, datetime(2026, 1, 1, tzinfo=timezone.utc))


def content(chunk, *, kb="kb", doc="manual", version="v1", chunk_version="c1", text="相同正文 USB-C"):
    return r.ContentRecord(r.EvidenceIdentity(kb, doc, version, chunk, chunk_version), text, {"uri": doc})


class PublicFusionTests(unittest.TestCase):
    def setUp(self):
        self.store = PublishedStore()
        self.a, self.b = content("a"), content("b")
        self.store.ingest((self.a, self.b))
        self.store.publish(self.store.prepare("kb", "s1", (self.a.identity, self.b.identity)))
        self.observed = []

    def route(self, route_id, method, records, *, kb="kb", scheme=None, status=None):
        def search(query, *, scope, top_k, exact_terms):
            self.observed.append((query, scope, top_k, exact_terms))
            hits = tuple(r.RouteHit(record, scope.snapshots[kb], score,
                                   "bm25" if method == "bm25" else "cosine_similarity", scheme)
                         for record, score in records)
            return r.RouteResult(route_id, kb, method, status or ("success" if hits else "empty"), hits)
        return r.RetrievalRoute(route_id, kb, method, search)

    def query(self, routes, **kwargs):
        return r.RetrievalService(self.store, routes=routes).query(
            "USB-C", knowledge_base_ids=("kb",), authorization=r.AuthorizationScope(("kb",)), **kwargs)

    def test_public_query_merges_schemes_without_adding_raw_scores(self):
        result = self.query((self.route("v1", "vector", [(self.a, .2), (self.b, .1)], scheme="scheme:one"),
                             self.route("v2", "vector", [(self.a, -.8)], scheme="scheme:two"),
                             self.route("b", "bm25", [(self.b, 800), (self.a, 300)])))
        self.assertEqual(result.status, "complete")
        self.assertEqual([item.content.identity for item in result.candidates], [self.a.identity, self.b.identity])
        self.assertAlmostEqual(result.candidates[0].score, 0.04891591750396616)
        self.assertEqual([trace.raw_score for trace in result.candidates[0].traces], [300, .2, -.8])
        self.assertEqual({trace.scheme_identity for trace in result.candidates[0].traces}, {None, "scheme:one", "scheme:two"})
        self.assertTrue(all(trace.identity == self.a.identity for trace in result.candidates[0].traces))
        self.assertTrue(all(call[1] is result.scope for call in self.observed))
        self.assertTrue(all(call[2] == 50 for call in self.observed))
        self.assertEqual(result.scope.snapshots["kb"], "s1")
        self.assertEqual(result.candidates[0].content.source, {"uri": "manual"})

    def test_same_route_duplicates_do_not_gain_votes_or_consume_ranks(self):
        result = self.query((self.route("v", "vector", [(self.a, .9), (self.a, .8), (self.b, .7)]),))
        self.assertEqual(len(result.candidates), 2)
        self.assertAlmostEqual(result.candidates[0].score, 0.01639344262295082)
        self.assertAlmostEqual(result.candidates[1].score, 0.016129032258064516)
        self.assertEqual(result.candidates[1].traces[0].rank, 2)
        self.assertEqual(len(result.candidates[0].traces), 1)

    def test_full_identity_and_distinct_sources_are_not_text_deduplicated(self):
        records = [self.a, content("a", doc="other"), content("a", version="v2"),
                   content("a", chunk_version="c2"), content("a", kb="other-kb")]
        self.store.ingest(records)
        self.store.publish(self.store.prepare("other-kb", "s2", [records[-1].identity]))
        routes = tuple(self.route(str(i), "bm25", [(record, 1)], kb=record.identity.knowledge_base_id)
                       for i, record in reversed(list(enumerate(records))))
        result = r.RetrievalService(self.store, routes=routes).query(
            "USB-C", knowledge_base_ids=("kb", "other-kb"), authorization=r.AuthorizationScope(("kb", "other-kb")))
        self.assertEqual([item.content.identity for item in result.candidates], sorted(record.identity for record in records))
        self.assertEqual(len(result.candidates), 5)

    def test_route_weights_and_separate_pool_and_final_limits(self):
        result = self.query((self.route("v", "vector", [(self.a, 1), (self.b, 0)]),
                             self.route("b", "bm25", [(self.b, 1), (self.a, 0)])),
                            config=r.RetrievalConfig(route_top_k=2, pool_size=2, final_top_k=1,
                                                     route_weights={"b": 2}))
        self.assertEqual(len(result.working_pool), 2)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].content.identity, self.b.identity)
        self.assertAlmostEqual(result.candidates[0].score, 0.04891591750396616)
        self.assertEqual(result.candidates[0].traces[0].weight, 2)
        self.assertTrue(all(call[2] == 2 for call in self.observed))

    def test_default_routes_adapt_vector_and_bm25_with_diagnostics(self):
        calls = []

        def vector(query, *, knowledge_base_id, scope, top_k):
            calls.append(("vector", scope, top_k))
            return r.VectorQueryResult("success", (r.VectorCandidate(self.a, "s1", "scheme:one", .8),),
                                       algorithm="hnsw", candidate_limit=50, exhaustive=False,
                                       limitations=("approximate recall",))

        def bm25(query, *, knowledge_base_id, scope, top_k, exact_terms):
            calls.append(("bm25", scope, top_k))
            self.assertEqual(exact_terms, ("USB-C",))
            return r.BM25QueryResult("success", (r.BM25Candidate(self.a, "s1", 5, "analyzer"),))

        self.store.search_vector = vector
        self.store.search_bm25 = bm25
        result = r.RetrievalService(self.store).query("USB-C", knowledge_base_ids=("kb",),
            authorization=r.AuthorizationScope(("kb",)), exact_terms=("USB-C",))
        self.assertEqual(result.status, "complete")
        self.assertEqual([route.route_id for route in result.routes], ["kb:vector", "kb:bm25"])
        self.assertEqual(result.routes[0].algorithm, "hnsw")
        self.assertEqual(result.routes[0].limitations, ("approximate recall",))
        self.assertEqual(result.routes[0].candidate_limit, 50)
        self.assertEqual({trace.scheme_identity for trace in result.candidates[0].traces}, {"scheme:one", "bm25:analyzer"})
        self.assertAlmostEqual(result.candidates[0].score, .03278688524590164)
        self.assertTrue(all(call[1] is result.scope for call in calls))

    def test_pool_limit_and_zero_weight_have_deterministic_behavior(self):
        routes = (self.route("v", "vector", [(self.b, .9), (self.a, .1)]),)
        result = self.query(routes, config=r.RetrievalConfig(pool_size=1, final_top_k=20,
                                                           route_weights={"v": 0}))
        self.assertEqual(len(result.working_pool), 1)
        self.assertEqual(result.candidates[0].content.identity, self.a.identity)
        self.assertEqual(result.candidates[0].score, 0)
        first_rank = self.query(routes, config=r.RetrievalConfig(rrf_k=0))
        self.assertEqual([item.score for item in first_rank.candidates], [1, .5])

    def test_empty_is_complete_but_no_success_is_incomplete(self):
        for statuses, expected in ((("empty", "empty"), "complete"),
                                   (("empty", "failed"), "partial"),
                                   (("failed", "timeout"), "incomplete"),
                                   (("not_executed", "failed"), "incomplete")):
            with self.subTest(statuses=statuses):
                result = self.query(tuple(self.route(str(i), "vector", [], status=status)
                                          for i, status in enumerate(statuses)))
                self.assertEqual(result.status, expected)
                self.assertEqual(result.candidates, ())
                self.assertEqual(tuple(route.status for route in result.routes), statuses)

    def test_failed_route_never_contributes_and_surviving_weight_is_not_redistributed(self):
        result = self.query((self.route("v", "vector", [(self.a, .9)]),
                             self.route("b", "bm25", [(self.b, 100)], status="failed")))
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.candidates), 1)
        self.assertAlmostEqual(result.candidates[0].score, 0.01639344262295082)
        self.assertEqual(result.routes[1].candidates, ())

    def test_route_exception_and_nonfinite_score_are_explicit_failures(self):
        def broken(query, **kwargs):
            raise RuntimeError("sensitive backend detail")
        routes = (r.RetrievalRoute("broken", "kb", "vector", broken),
                  self.route("invalid", "bm25", [(self.a, float("nan"))]))
        result = self.query(routes)
        self.assertEqual(result.status, "incomplete")
        self.assertTrue(all(route.reason == "route_execution_failed" for route in result.routes))
        self.assertEqual(result.candidates, ())

    def test_query_pins_once_and_forwards_filters_history_and_exact_terms(self):
        conditions = {"product": "AX-100"}
        result = self.query((self.route("v", "vector", [(self.a, .5)]),
                             self.route("b", "bm25", [(self.a, 3)])),
                            conditions=conditions, snapshot_ids={"kb": "historical"}, exact_terms=("USB-C",))
        self.assertEqual(len(self.store.calls), 1)
        self.assertIs(result.scope.conditions, conditions)
        self.assertEqual(result.scope.snapshots["kb"], "historical")
        self.assertTrue(all(call[3] == ("USB-C",) for call in self.observed))

    def test_authorization_is_required_and_cannot_be_expanded_by_kb_selection(self):
        service = r.RetrievalService(self.store, routes=(self.route("v", "vector", [(self.a, .5)]),))
        for authorization in (None, r.AuthorizationScope(("foreign",))):
            with self.assertRaises(r.RetrievalContractError):
                service.query("USB-C", knowledge_base_ids=("kb",), authorization=authorization)
        self.assertEqual(self.store.calls, [])
        result = service.query("USB-C", knowledge_base_ids=("kb",),
                               authorization=r.AuthorizationScope(("kb",), {"kb": ()}))
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.candidates, ())

    def test_wrong_snapshot_or_knowledge_base_fails_closed(self):
        for record, snapshot in ((self.a, "another-snapshot"), (content("a", kb="foreign"), "s1")):
            def search(query, *, scope, top_k, exact_terms):
                return r.RouteResult("v", "kb", "vector", "success",
                                     (r.RouteHit(record, snapshot, .5, "cosine_similarity"),))
            result = self.query((r.RetrievalRoute("v", "kb", "vector", search),))
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(result.candidates, ())

    def test_limit_applies_after_duplicate_identity_removal_and_pool_does_not_fill(self):
        result = self.query((self.route("v", "vector", [(self.a, .9), (self.a, .8), (self.b, .7)]),),
                            config=r.RetrievalConfig(route_top_k=2, pool_size=100, final_top_k=20))
        self.assertEqual([item.content.identity for item in result.candidates], [self.a.identity, self.b.identity])
        limited = self.query((self.route("v", "vector", [(self.a, .9), (self.b, .7)]),),
                             config=r.RetrievalConfig(route_top_k=1, pool_size=100, final_top_k=20))
        self.assertEqual([item.content.identity for item in limited.candidates], [self.a.identity])

    def test_ties_are_stable_when_route_completion_order_changes(self):
        routes = (self.route("left", "vector", [(self.a, .9), (self.b, .7)]),
                  self.route("right", "bm25", [(self.b, 2), (self.a, 1)]))
        first, second = self.query(routes), self.query(tuple(reversed(routes)))
        self.assertEqual(first.candidates, second.candidates)
        self.assertEqual([item.content.identity for item in first.candidates], [self.a.identity, self.b.identity])

    def test_invalid_config_is_rejected_before_publication_reads(self):
        for options in ({"rrf_k": -1}, {"route_top_k": True}, {"pool_size": 0},
                        {"route_weights": {"v": float("inf")}}, {"final_top_k": -1}):
            with self.subTest(options=options), self.assertRaises(r.RetrievalContractError):
                r.RetrievalConfig(**options)
        with self.assertRaises(r.RetrievalContractError):
            self.query((self.route("v", "vector", []),), config=r.RetrievalConfig(route_weights={"typo": 1}))
        self.assertEqual(self.store.calls, [])
