"""Public parent pipeline specifications, authored only; NOT EXECUTED."""
import importlib
import unittest
from datetime import datetime, timezone

r = importlib.import_module("app.modules.4_retrievalAndFusion")


def record(chunk, text, parent=None):
    return r.ContentRecord(r.EvidenceIdentity("kb", "manual", "v1", chunk, "c1"),
                           text, {"chunk": chunk}, parent=parent)


class PublicParentTests(unittest.TestCase):
    def setUp(self):
        self.parent = record("parent", "Full parent body with unmatched details")
        self.children = (record("a", "First hit", self.parent.identity),
                         record("b", "Second hit", self.parent.identity))
        self.other = record("other", "Additional independent evidence")
        self.auth = r.AuthorizationScope(("kb",))
        self.scope = r.ReadScope({"kb": "s1"}, self.auth, None,
                                datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.reads = []
        self.route_scopes = []
        owner = self

        class Store:
            def pin(self, knowledge_base_ids, **options):
                return owner.scope

            def read(self, identity, *, scope, remaining=None):
                owner.reads.append((identity, scope, remaining))
                return owner.parent

        def search(query, *, scope, top_k, exact_terms, **options):
            owner.route_scopes.append(scope)
            hits = tuple(r.RouteHit(item, "s1", 10. - rank, "bm25")
                         for rank, item in enumerate((*owner.children, owner.other)))
            return r.RouteResult("lexical", "kb", "bm25", "success", hits[:top_k])

        self.service = r.RetrievalService(Store(), routes=(r.RetrievalRoute("lexical", "kb", "bm25", search),))

    def query(self, **options):
        return self.service.query("hit", knowledge_base_ids=("kb",), authorization=self.auth, **options)

    def test_default_disabled_preserves_children_and_reports_all_stage_slots(self):
        result = self.query()
        self.assertEqual([item.content for item in result.candidates], [*self.children, self.other])
        self.assertEqual([(step.name, step.status) for step in result.steps],
                         [("parent", "skipped"), ("dedup", "skipped"), ("mmr", "skipped")])
        self.assertEqual(self.reads, [])

    def test_parent_merge_before_final_cut_backfills_and_keeps_child_traces(self):
        result = self.query(config=r.RetrievalConfig(parent_expansion=True, final_top_k=2))
        self.assertEqual(result.status, "complete")
        self.assertEqual([item.content for item in result.candidates], [self.parent, self.other])
        self.assertEqual(len(result.working_pool), 2)
        parent = result.candidates[0]
        self.assertEqual(parent.matched_children, self.children)
        self.assertEqual([trace.identity for trace in parent.traces], [item.identity for item in self.children])
        self.assertAlmostEqual(parent.score, 1 / 61)
        self.assertEqual(len(self.reads), 1)
        self.assertIs(self.reads[0][1], result.scope)
        self.assertTrue(all(scope is result.scope for scope in self.route_scopes))

    def test_unavailable_parent_preserves_route_status_and_strict_diagnostics(self):
        self.parent = None
        for strict in (False, True):
            with self.subTest(strict=strict):
                result = self.query(config=r.RetrievalConfig(parent_expansion=True, postprocess_strict=strict))
                self.assertEqual(result.status, "complete")
                self.assertEqual(result.routes[0].status, "success")
                self.assertEqual([item.content for item in result.working_pool], [*self.children, self.other])
                self.assertEqual(result.steps[0].status, "failed" if strict else "partial")
                self.assertEqual(result.steps[0].reason, "parent_unavailable")
                if strict:
                    self.assertEqual(result.candidates, ())
                    self.assertTrue(all(step.reason == "prior_stage_failed" for step in result.steps[1:]))
                else:
                    self.assertEqual(result.candidates, result.working_pool)

    def test_public_budget_object_is_forwarded_without_replacement(self):
        deadlines = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")
        remaining = deadlines.Deadline(30)
        result = self.query(config=r.RetrievalConfig(parent_expansion=True), remaining=remaining)
        self.assertEqual(result.steps[0].status, "complete")
        self.assertIs(self.reads[0][2], remaining)

    def test_legacy_reader_receives_same_root_through_context(self):
        deadlines = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")
        root = deadlines.Deadline(30)
        seen = []
        def read(identity, *, scope):
            seen.append(deadlines.current_deadline())
            return self.parent
        self.service.store.read = read
        result = self.query(config=r.RetrievalConfig(parent_expansion=True), remaining=root)
        self.assertEqual(result.steps[0].status, "complete")
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0], root)

    def test_uncooperative_parent_reader_is_bounded_and_late_body_never_published(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        deadlines = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")
        scheduler = importlib.import_module("app.modules.4_retrievalAndFusion.scheduler")
        for strict in (False, True):
            with self.subTest(strict=strict):
                started, release, finished = threading.Event(), threading.Event(), threading.Event()
                workers = scheduler.BoundedScheduler(1)
                self.service.scheduler = workers
                root = deadlines.Deadline(30)
                def read(identity, *, scope, remaining):
                    started.set()
                    release.wait()
                    finished.set()
                    return self.parent
                self.service.store.read = read
                caller = ThreadPoolExecutor(max_workers=1)
                try:
                    future = caller.submit(self.query, remaining=root, config=r.RetrievalConfig(
                        parent_expansion=True, postprocess_strict=strict, max_concurrency=1))
                    self.assertTrue(started.wait(2))
                    root.cancel()
                    result = future.result(timeout=2)
                    self.assertEqual(result.status, "complete")
                    self.assertEqual(result.steps[0].reason, "parent_budget_exhausted")
                    self.assertEqual(result.steps[0].status, "failed" if strict else "partial")
                    self.assertFalse(finished.is_set())
                    self.assertEqual([item.content for item in result.working_pool], [*self.children, self.other])
                    self.assertEqual([item.content for item in result.candidates],
                                     [] if strict else [*self.children, self.other])
                    release.set()
                    self.assertTrue(finished.wait(2))
                    self.assertNotIn(self.parent, [item.content for item in result.candidates])
                finally:
                    release.set()
                    caller.shutdown(wait=True)
                    workers.close()

    def test_flags_reject_truthy_non_booleans(self):
        for flag in ("parent_expansion", "postprocess_strict"):
            with self.subTest(flag=flag), self.assertRaises(r.RetrievalContractError):
                r.RetrievalConfig(**{flag: "true"})
