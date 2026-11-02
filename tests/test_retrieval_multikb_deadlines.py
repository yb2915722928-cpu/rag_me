"""Multi-KB public query deadline specifications; authored, NOT RUN (#87)."""
import importlib
import threading
import unittest
from datetime import datetime, timezone

r = importlib.import_module("app.modules.4_retrievalAndFusion")
b = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")
s = importlib.import_module("app.modules.4_retrievalAndFusion.scheduler")


class PinnedStore:
    def __init__(self, clock=None):
        self.publications = {"a": "v1", "b": "v1"}
        self.pins = []
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.clock = clock

    def pin(self, knowledge_base_ids, *, authorization, conditions=None, snapshot_ids=None, remaining=None):
        self.pins.append(tuple(knowledge_base_ids))
        return r.ReadScope({kb: (snapshot_ids or {}).get(kb, self.publications[kb])
                            for kb in knowledge_base_ids}, authorization, conditions, self.now)


class MultiKnowledgeBaseDeadlineTests(unittest.TestCase):
    def test_all_kbs_pin_once_and_publication_change_does_not_change_scope(self):
        store = PinnedStore()
        seen = []
        def route(kb):
            def search(query, *, scope, **options):
                seen.append(scope)
                store.publications[kb] = "v2"
                return r.RouteResult(kb, kb, "vector", "empty")
            return r.RetrievalRoute(kb, kb, "vector", search)
        result = r.RetrievalService(store, routes=[route("a"), route("b")]).query(
            "query", knowledge_base_ids=["a", "b"], authorization=r.AuthorizationScope(("a", "b")))
        self.assertEqual(store.pins, [("a", "b")])
        self.assertIs(seen[0], seen[1])
        self.assertEqual(dict(result.scope.snapshots), {"a": "v1", "b": "v1"})
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.candidates, ())

    def test_failed_backend_is_not_empty_and_other_kb_can_complete(self):
        def fail(query, **options):
            raise RuntimeError("private database detail")
        def empty(query, **options):
            return r.RouteResult("b", "b", "bm25", "empty")
        result = r.RetrievalService(PinnedStore(), routes=[
            r.RetrievalRoute("a", "a", "vector", fail), r.RetrievalRoute("b", "b", "bm25", empty),
        ]).query("query", knowledge_base_ids=["a", "b"], authorization=r.AuthorizationScope(("a", "b")))
        self.assertEqual(result.status, "partial")
        self.assertEqual([route.status for route in result.routes], ["failed", "empty"])
        self.assertNotIn("private", str(result))

    def test_no_authorization_rejects_before_pin_or_backend(self):
        store = PinnedStore()
        with self.assertRaises(r.RetrievalContractError):
            r.RetrievalService(store, routes=[]).query("query", knowledge_base_ids=["a"], authorization=None)
        self.assertEqual(store.pins, [])

    def test_started_timeout_and_queued_not_executed_leave_incomplete_result(self):
        release = threading.Event()
        started = threading.Event()
        scheduler = s.BoundedScheduler(1)
        def slow(query, **options):
            started.set()
            release.wait(2)
            return r.RouteResult("a", "a", "vector", "empty")
        def queued(query, **options):
            self.fail("queued backend must not start")
        try:
            result = r.RetrievalService(PinnedStore(), scheduler=scheduler, routes=[
                r.RetrievalRoute("a", "a", "vector", slow), r.RetrievalRoute("b", "b", "bm25", queued),
            ]).query("query", knowledge_base_ids=["a", "b"], authorization=r.AuthorizationScope(("a", "b")),
                     config=r.RetrievalConfig(total_timeout=.05, route_timeout=.01, max_concurrency=1))
            self.assertTrue(started.is_set())
            self.assertEqual(result.status, "incomplete")
            self.assertEqual([route.status for route in result.routes], ["timeout", "not_executed"])
            self.assertEqual(result.candidates, ())
        finally:
            release.set()
            scheduler.close()

    def test_pin_consumes_total_budget_before_any_route_starts(self):
        instant = [0.0]
        class SlowPin(PinnedStore):
            def pin(self, *args, **kwargs):
                scope = super().pin(*args, **kwargs)
                instant[0] = 11.0
                return scope
        service = r.RetrievalService(SlowPin(), clock=lambda: instant[0], routes=[
            r.RetrievalRoute("a", "a", "vector", lambda *args, **kwargs: self.fail("expired")),
        ])
        result = service.query("query", knowledge_base_ids=["a"], authorization=r.AuthorizationScope(("a",)))
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.routes[0].status, "not_executed")
