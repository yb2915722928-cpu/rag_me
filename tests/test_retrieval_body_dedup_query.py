"""#92 public published-query behaviors. Authored test-first; NOT EXECUTED."""
import importlib
import unittest
import threading
import time
from datetime import datetime, timezone

r = importlib.import_module("app.modules.4_retrievalAndFusion")


class PublishedStore:
    def ingest(self, records):
        self.records = tuple(records)

    def prepare(self, kb, snapshot):
        return kb, snapshot, self.records

    def publish(self, prepared):
        self.kb, self.snapshot, self.visible = prepared

    def pin(self, ids, *, authorization, conditions=None, snapshot_ids=None, **kwargs):
        return r.ReadScope({self.kb: self.snapshot}, authorization, conditions,
                           datetime(2026, 11, 2, tzinfo=timezone.utc))


def record(doc, text, version="v1", metadata=None):
    return r.ContentRecord(r.EvidenceIdentity("kb", doc, version, "body", "c1"),
                           text, {"uri": doc}, metadata or {})


def approved(left, right, *, scope, remaining):
    return r.BodyDedupProof("authority:applicability-reviewed", "authority:versions-reviewed")


class PublicBodyDedupTests(unittest.TestCase):
    def query(self, records, *, config=None, prover=None, scheduler=None, clock=time.monotonic,
              on_search=None):
        store = PublishedStore()
        store.ingest(records)
        store.publish(store.prepare("kb", "published"))

        def search(query, *, scope, top_k, exact_terms, **kwargs):
            if on_search is not None:
                on_search(kwargs["remaining"])
            hits = tuple(r.RouteHit(item, scope.snapshots["kb"], 10 - index, "cosine",
                                   matched_questions=(r.MatchedQuestion(item.standard_question, 10 - index),)
                                   if isinstance(item, r.FAQRecord) else ())
                         for index, item in enumerate(store.visible[:top_k]))
            return r.RouteResult("vector", "kb", "vector", "success" if hits else "empty", hits)

        return r.RetrievalService(store, routes=(r.RetrievalRoute("vector", "kb", "vector", search),),
                                  scheduler=scheduler, clock=clock).query(
            "USB-C", knowledge_base_ids=("kb",), authorization=r.AuthorizationScope(("kb",)),
            config=config, body_dedup_prover=prover,
        )

    def test_disabled_and_unproven_duplicates_survive_public_query(self):
        records = (record("a", "same"), record("b", "same"))
        for config, prover in ((r.RetrievalConfig(), approved),
                               (r.RetrievalConfig(body_dedup=True), None)):
            result = self.query(records, config=config, prover=prover)
            self.assertEqual(len(result.candidates), 2)
            step = next(step for step in result.steps if step.name == "dedup")
            self.assertEqual(step.status, "complete" if config.body_dedup else "skipped")

    def test_full_pool_dedup_refills_final_and_preserves_late_source_and_versions(self):
        records = (record("a", " USB-C\r\nanswer "), record("b", "USB-C\nanswer", "v2"),
                   record("c", "other"), record("d", "last"), record("e", "USB-C\nanswer", "v3"))
        baseline = self.query(records)
        result = self.query(records, config=r.RetrievalConfig(body_dedup=True, final_top_k=3), prover=approved)
        self.assertEqual([c.content.identity.document_id for c in result.candidates], ["a", "c", "d"])
        merged = result.candidates[0]
        self.assertEqual(merged.content, records[0])
        self.assertEqual(merged.score, baseline.candidates[0].score)
        self.assertEqual(set(merged.represented_identities), {records[i].identity for i in (0, 1, 4)})
        self.assertEqual(merged.sources, ({"uri": "a"}, {"uri": "b"}, {"uri": "e"}))
        self.assertEqual({t.identity for t in merged.traces}, {records[i].identity for i in (0, 1, 4)})
        self.assertEqual(len(result.working_pool), 3)

    def test_internal_whitespace_case_and_lone_cr_remain_distinct_and_no_padding(self):
        records = tuple(record(str(i), text) for i, text in enumerate(
            ("USB-C answer", "USB-C  answer", "usb-c answer", "USB-C\ranswer")))
        result = self.query(records, config=r.RetrievalConfig(body_dedup=True, final_top_k=20), prover=approved)
        self.assertEqual(len(result.candidates), 4)
        self.assertEqual([c.content for c in result.candidates], list(records))

    def test_authoritative_policy_separates_conditions_and_incompatible_versions(self):
        records = (record("a", "same", metadata={"region": "north"}),
                   record("b", "same", metadata={"region": "south"}),
                   record("c", "same", "obsolete", {"region": "south"}),
                   record("d", "same", metadata={"region": "south"}))
        observed = []

        def policy(left, right, *, scope, remaining):
            observed.append(scope)
            if {left.content.identity.document_id, right.content.identity.document_id} == {"b", "d"}:
                return approved(left, right, scope=scope, remaining=remaining)
            return None

        result = self.query(records, config=r.RetrievalConfig(body_dedup=True), prover=policy)
        self.assertEqual([c.content.identity.document_id for c in result.candidates], ["a", "b", "c"])
        self.assertTrue(all(scope is result.scope for scope in observed))
        self.assertEqual(result.scope.snapshots, {"kb": "published"})

    def test_proof_failure_is_visible_and_strict_rejects_fallback(self):
        def broken(*args, **kwargs):
            raise RuntimeError("private backend error")

        records = (record("a", "same"), record("b", "same"))
        result = self.query(records, config=r.RetrievalConfig(body_dedup=True), prover=broken)
        self.assertEqual(len(result.candidates), 2)
        step = next(s for s in result.steps if s.name == "dedup")
        self.assertEqual((step.status, step.reason), ("failed", "compatibility_proof_failed"))
        strict = self.query(records, config=r.RetrievalConfig(body_dedup=True, postprocess_strict=True), prover=broken)
        self.assertEqual(strict.candidates, ())
        self.assertEqual(len(strict.working_pool), 2)
        self.assertEqual(strict.status, "complete")
        self.assertEqual(strict.routes[0].status, "success")
        failed = next(s for s in strict.steps if s.name == "dedup")
        self.assertEqual((failed.status, failed.reason), ("failed", "compatibility_proof_failed"))

    def test_faq_answer_dedup_preserves_questions_sources_and_versions_without_document_merge(self):
        faqs = tuple(r.FAQRecord(r.FAQIdentity("kb", item, version), question, (), answer,
                                 {}, {"uri": item})
                     for item, version, question, answer in (
                         ("faq-a", "v1", "First question?", " same\r\nanswer "),
                         ("faq-b", "v2", "Second question?", "same\nanswer")))
        result = self.query((*faqs, record("doc", "same\nanswer")),
                            config=r.RetrievalConfig(body_dedup=True), prover=approved)
        self.assertEqual(len(result.candidates), 2)
        merged = result.candidates[0]
        self.assertEqual(merged.content, faqs[0])
        self.assertEqual(set(merged.represented_identities), {item.identity for item in faqs})
        self.assertEqual(merged.sources, tuple(item.source for item in faqs))
        self.assertEqual([q.question for t in merged.traces for q in t.matched_questions],
                         [item.standard_question for item in faqs])
        self.assertEqual(result.candidates[1].content.identity.document_id, "doc")

    def test_prover_receives_remaining_root_budget_after_route_time(self):
        instant = [100.0]
        observed = []

        def spend_route_time(remaining):
            instant[0] += 6

        def proof(left, right, *, scope, remaining):
            observed.append(remaining.remaining())
            return approved(left, right, scope=scope, remaining=remaining)

        result = self.query((record("a", "same"), record("b", "same")),
                            config=r.RetrievalConfig(body_dedup=True, total_timeout=10, route_timeout=9),
                            prover=proof, clock=lambda: instant[0], on_search=spend_route_time)
        self.assertEqual(observed, [4])
        self.assertEqual(len(result.candidates), 1)

    def test_uncooperative_prover_cannot_hold_query_or_publish_late_results(self):
        scheduler_module = importlib.import_module("app.modules.4_retrievalAndFusion.scheduler")
        for strict in (False, True):
            with self.subTest(strict=strict):
                scheduler = scheduler_module.BoundedScheduler(1)
                release, entered, finished = threading.Event(), threading.Event(), threading.Event()
                instant = [100.0]

                def stalled(*args, **kwargs):
                    entered.set()
                    instant[0] += 10
                    try:
                        release.wait(2)
                        return r.BodyDedupProof("applicable", "version-compatible")
                    finally:
                        finished.set()

                try:
                    started = time.monotonic()
                    result = self.query((record("a", "same"), record("b", "same")),
                                        config=r.RetrievalConfig(body_dedup=True, total_timeout=10,
                                                                 max_concurrency=1, postprocess_strict=strict),
                                        prover=stalled, scheduler=scheduler, clock=lambda: instant[0])
                    self.assertTrue(entered.is_set())
                    self.assertLess(time.monotonic() - started, 1)
                    self.assertEqual(len(result.candidates), 0 if strict else 2)
                    self.assertEqual(len(result.working_pool), 2)
                    self.assertEqual(result.routes[0].status, "success")
                    step = next(s for s in result.steps if s.name == "dedup")
                    self.assertEqual((step.status, step.reason), ("failed", "dedup_timeout"))
                    release.set()
                    self.assertTrue(finished.wait(1))
                    self.assertEqual(len(result.working_pool), 2)
                finally:
                    release.set()
                    scheduler.close()

    def test_dedup_configuration_requires_booleans(self):
        for field in ("body_dedup", "postprocess_strict"):
            with self.assertRaises(r.RetrievalContractError):
                r.RetrievalConfig(**{field: "false"})
