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
        self.assertIsNone(result.scope)
        self.assertEqual(result.steps[0].name, "pin")

    def test_root_expiry_after_completed_pin_returns_diagnostics_without_new_budget(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                instant = [0.0]
                root = b.Deadline(1, clock=lambda: instant[0])

                class Scheduler(s.BoundedScheduler):
                    pin_completed = False

                    def run(self, *args, **kwargs):
                        outcomes = super().run(*args, **kwargs)
                        if not self.pin_completed:
                            self.pin_completed = True
                            if cancelled:
                                root.cancel()
                            else:
                                instant[0] = 1.0
                        return outcomes

                scheduler = Scheduler(1)
                self.addCleanup(scheduler.close)
                route = r.RetrievalRoute("a", "a", "vector",
                    lambda *args, **kwargs: self.fail("route must not start after root expiry"))
                result = r.RetrievalService(PinnedStore(), scheduler=scheduler, routes=(route,)).query(
                    "query", knowledge_base_ids=("a",), authorization=r.AuthorizationScope(("a",)),
                    remaining=root, config=r.RetrievalConfig(max_concurrency=1))
                self.assertEqual(result.status, "incomplete")
                self.assertEqual(result.scope.snapshots, {"a": "v1"})
                self.assertEqual(result.routes[0].status, "not_executed")
                self.assertEqual(result.steps[0], r.PostprocessStep("fusion", "failed", "fusion_timeout"))
                self.assertEqual(result.candidates, ())
                self.assertEqual(result.working_pool, ())

    def test_pin_and_fusion_share_root_and_route_is_clipped_child(self):
        roots, children = [], []
        class Store(PinnedStore):
            def pin(self, *args, remaining, **kwargs):
                roots.append(remaining)
                return super().pin(*args, remaining=remaining, **kwargs)
        class Service(r.RetrievalService):
            @staticmethod
            def _fuse(results, config, remaining):
                roots.append(remaining)
                return r.RetrievalService._fuse(results, config, remaining)
        def search(query, *, remaining, **kwargs):
            children.append(remaining)
            return r.RouteResult("a", "a", "vector", "empty")
        result = Service(Store(), routes=[r.RetrievalRoute("a", "a", "vector", search)]).query(
            "query", knowledge_base_ids=["a"], authorization=r.AuthorizationScope(("a",)))
        self.assertEqual(result.status, "complete")
        self.assertIs(roots[0], roots[1])
        self.assertIsNot(children[0], roots[0])
        self.assertLessEqual(children[0].expires_at, roots[0].expires_at)

    def test_completed_hits_fuse_when_last_route_exhausts_stage_with_no_free_worker(self):
        for strategy in ("rrf", "weighted"):
            with self.subTest(strategy=strategy):
                instant = [0.0]
                release = threading.Event()
                scheduler = s.BoundedScheduler(1)
                self.addCleanup(scheduler.close)
                self.addCleanup(release.set)
                content = r.ContentRecord(r.EvidenceIdentity("a", "doc", "v1", "child", "v1"),
                                          "retained evidence", {"source": "fixture"}, {})

                def completed(query, **kwargs):
                    return r.RouteResult("a", "a", "vector", "success",
                        (r.RouteHit(content, "v1", .8, "cosine_similarity"),))

                def stalled(query, **kwargs):
                    instant[0] = .91
                    release.wait(2)
                    return r.RouteResult("b", "b", "bm25", "empty")

                result = r.RetrievalService(PinnedStore(), scheduler=scheduler,
                    clock=lambda: instant[0], routes=(
                        r.RetrievalRoute("a", "a", "vector", completed),
                        r.RetrievalRoute("b", "b", "bm25", stalled),
                    )).query("query", knowledge_base_ids=("a", "b"),
                        authorization=r.AuthorizationScope(("a", "b")),
                        config=r.RetrievalConfig(total_timeout=1, route_timeout=1,
                                                max_concurrency=1, fusion_strategy=strategy))
                self.assertEqual(result.status, "partial")
                self.assertEqual([route.status for route in result.routes], ["success", "timeout"])
                self.assertEqual([item.content for item in result.candidates], [content])
                self.assertEqual(result.working_pool, result.candidates)
                self.assertAlmostEqual(result.candidates[0].score, 1 / 61 if strategy == "rrf" else 1)
                self.assertEqual([step.status for step in result.steps], ["skipped"] * 3)
                release.set()

    def test_late_fusion_is_discarded_and_reports_failed_step_preserving_route_status(self):
        instant = [0.0]
        class Service(r.RetrievalService):
            @staticmethod
            def _fuse(results, config, remaining):
                instant[0] = 11
                return ()
        route = r.RetrievalRoute("a", "a", "vector", lambda *args, **kwargs: r.RouteResult("a", "a", "vector", "empty"))
        result = Service(PinnedStore(), routes=[route], clock=lambda: instant[0]).query(
            "query", knowledge_base_ids=["a"], authorization=r.AuthorizationScope(("a",)))
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.steps[0].status, "failed")
        self.assertEqual(result.steps[0].name, "fusion")
        self.assertEqual(result.candidates, ())
