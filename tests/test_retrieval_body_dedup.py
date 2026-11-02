"""Body deduplication public processing seam; authored, never executed for #92.

The query seam is added after the #86 dependency is integrated. These tests
exercise delivered candidates, provenance and status, never private helpers.
"""
import importlib
import unittest
from datetime import datetime, timezone
from dataclasses import replace

contracts = importlib.import_module("app.modules.4_retrievalAndFusion.contracts")
fusion = importlib.import_module("app.modules.4_retrievalAndFusion.fusion_contracts")
dedup = importlib.import_module("app.modules.4_retrievalAndFusion.body_dedup")
# Real #88 contract; intentionally no copied stand-in while that dependency waits.
faq = importlib.import_module("app.modules.4_retrievalAndFusion.faq_contracts")


def candidate(document, text="same answer", score=1.0, version="2026", metadata=None):
    identity = contracts.EvidenceIdentity("kb", document, version, "body", "1")
    content = contracts.ContentRecord(identity, text, {"uri": document}, metadata or {})
    trace = fusion.ScoreTrace("kb:vector", "kb", "vector", 1, 0.8, "cosine", "scheme",
                              identity, "snapshot", 1.0, score)
    return fusion.FusedCandidate(content, score, (trace,))


def approved(left, right, *, scope, remaining):
    # A fixture policy supplies explicit authoritative attestations, not inferred
    # equality of metadata or revision strings.
    return dedup.BodyDedupProof("policy:AX-100/all-regions", "release:equivalent-rules")


class BodyDedupTests(unittest.TestCase):
    def setUp(self):
        self.scope = contracts.ReadScope(
            {"kb": "snapshot"}, contracts.AuthorizationScope(("kb",)), None,
            datetime(2026, 11, 2, tzinfo=timezone.utc),
        )

    def process(self, pool, **kwargs):
        return dedup.process_body_dedup(pool, scope=self.scope, **kwargs)

    def test_default_off_preserves_same_text_from_different_sources(self):
        pool = (candidate("a"), candidate("b"))
        result, step = self.process(pool, prover=approved)
        self.assertEqual(result, pool)
        self.assertEqual((step.name, step.status), ("dedup", "skipped"))

    def test_equal_body_empty_metadata_and_same_version_do_not_prove_compatibility(self):
        pool = (candidate("a"), candidate("b"))
        for prover in (None, lambda *args, **kwargs: None):
            with self.subTest(prover=prover):
                result, step = self.process(pool, enabled=True, prover=prover)
                self.assertEqual(result, pool)
                self.assertEqual(step.status, "complete")

    def test_only_crlf_and_edge_whitespace_are_normalized(self):
        pool = (candidate("a", "  USB-C\r\nAX-100 \t", 4),
                candidate("b", "USB-C\nAX-100", 3),
                candidate("c", "USB-C  AX-100", 2),
                candidate("d", "usb-c\nAX-100", 1),
                candidate("e", "USB-C\rAX-100", 0.5))
        result, step = self.process(pool, enabled=True, prover=approved)
        self.assertEqual([item.content.identity.document_id for item in result], ["a", "c", "d", "e"])
        self.assertEqual(result[0].content.text, "  USB-C\r\nAX-100 \t")
        self.assertEqual(result[0].score, 4)
        self.assertEqual(result[0].represented_identities, (pool[0].content.identity, pool[1].content.identity))
        self.assertEqual(result[0].sources, ({"uri": "a"}, {"uri": "b"}))
        self.assertEqual(result[0].traces, pool[0].traces + pool[1].traces)
        self.assertEqual(step.status, "complete")

    def test_declined_group_does_not_hide_another_compatible_group(self):
        pool = (candidate("a", metadata={"region": "north"}),
                candidate("b", metadata={"region": "south"}),
                candidate("c", metadata={"region": "south"}))

        def policy(left, right, **kwargs):
            # Explicit fixture decision, not a generic metadata equivalence rule.
            if {left.content.identity.document_id, right.content.identity.document_id} == {"b", "c"}:
                return approved(left, right, **kwargs)
            return None

        result, _ = self.process(pool, enabled=True, prover=policy)
        self.assertEqual([x.content.identity.document_id for x in result], ["a", "b"])
        self.assertEqual(result[1].represented_identities, (pool[1].content.identity, pool[2].content.identity))

    def test_compatibility_is_checked_against_every_original_group_member(self):
        pool = (candidate("a"), candidate("b"), candidate("c"))

        def policy(left, right, **kwargs):
            if {left.content.identity.document_id, right.content.identity.document_id} == {"b", "c"}:
                return None
            return approved(left, right, **kwargs)

        result, _ = self.process(pool, enabled=True, prover=policy)
        self.assertEqual([x.content.identity.document_id for x in result], ["a", "c"])
        self.assertEqual(len(result[0].represented_identities), 2)

    def test_distinct_versions_are_retained_unless_policy_proves_their_semantics(self):
        pool = (candidate("a", version="old"), candidate("b", version="current"))
        unknown, _ = self.process(pool, enabled=True)
        self.assertEqual(len(unknown), 2)
        result, _ = self.process(pool, enabled=True, prover=approved)
        self.assertEqual({i.document_version for i in result[0].represented_identities}, {"old", "current"})

    def test_whole_pool_is_processed_before_final_selection_and_never_padded(self):
        pool = (candidate("a", score=9), candidate("b", score=8),
                candidate("c", text="second answer", score=7),
                candidate("d", text="third answer", score=6),
                candidate("e", score=1))
        result, _ = self.process(pool, enabled=True, prover=approved)
        self.assertEqual([x.content.identity.document_id for x in result[:3]], ["a", "c", "d"])
        self.assertEqual(len(result[:20]), 3)
        # The last same-body candidate is still represented even though final K=3.
        self.assertEqual(result[0].represented_identities,
                         (pool[0].content.identity, pool[1].content.identity, pool[4].content.identity))

    def test_representative_is_highest_score_then_complete_identity_independent_of_input_order(self):
        a, b, c = candidate("a", score=4), candidate("b", score=4), candidate("c", score=2)
        forward, _ = self.process((b, c, a), enabled=True, prover=approved)
        reverse, _ = self.process((a, c, b), enabled=True, prover=approved)
        self.assertEqual(forward, reverse)
        self.assertEqual(forward[0].content.identity, a.content.identity)
        self.assertEqual(forward[0].score, 4)

    def test_parent_bodies_keep_complete_children_sources_and_traces(self):
        a, b = candidate("parent-a", score=5), candidate("parent-b", score=3)
        child_a = replace(candidate("parent-a", text="child snippet").content,
                          identity=contracts.EvidenceIdentity("kb", "parent-a", "2026", "child", "2"),
                          source={"uri": "parent-a", "page": 2}, parent=a.content.identity)
        child_b = replace(candidate("parent-b", text="other child").content,
                          identity=contracts.EvidenceIdentity("kb", "parent-b", "2026", "child", "3"),
                          source={"uri": "parent-b", "page": 8}, parent=b.content.identity)
        a = replace(a, represented_identities=(a.content.identity, child_a.identity),
                    sources=(a.content.source, child_a.source), matched_children=(child_a,))
        b = replace(b, represented_identities=(b.content.identity, child_b.identity),
                    sources=(b.content.source, child_b.source), matched_children=(child_b,))
        received = []

        def policy(left, right, *, scope, remaining):
            received.append((left, right, scope))
            return approved(left, right, scope=scope, remaining=remaining)

        result, _ = self.process((a, b), enabled=True, prover=policy)
        self.assertEqual(received, [(a, b, self.scope)])
        self.assertEqual(result[0].matched_children, (child_a, child_b))
        self.assertEqual(set(result[0].represented_identities),
                         {a.content.identity, child_a.identity, b.content.identity, child_b.identity})
        self.assertEqual(result[0].sources, (a.content.source, child_a.source, b.content.source, child_b.source))
        self.assertEqual(result[0].traces, a.traces + b.traces)
        self.assertEqual(result[0].content, a.content)

    def test_faq_answer_dedup_keeps_versions_and_never_crosses_document_type(self):
        document = candidate("manual", text="USB-C answer", score=4)
        first = faq.FAQRecord(faq.FAQIdentity("kb", "faq-a", "v1"), "Question A", (),
                              " USB-C answer\r\n", {"region": "all"}, {"uri": "faq-a"})
        second = faq.FAQRecord(faq.FAQIdentity("kb", "faq-b", "v2"), "Question B", (),
                               "USB-C answer", {"region": "all"}, {"uri": "faq-b"})
        a = fusion.FusedCandidate(first, 3, ())
        b = fusion.FusedCandidate(second, 2, ())
        result, step = self.process((document, a, b), enabled=True, prover=approved)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], document)
        self.assertEqual(result[1].represented_identities, (first.identity, second.identity))
        self.assertEqual(result[1].sources, (first.source, second.source))
        self.assertEqual(result[1].content.text, " USB-C answer\r\n")
        self.assertEqual(step.status, "complete")

    def test_empty_pool_completes_without_inventing_candidates(self):
        result, step = self.process((), enabled=True, prover=approved)
        self.assertEqual(result, ())
        self.assertEqual(step.status, "complete")

    def test_proof_requires_both_explicit_nonempty_attestations(self):
        for applicability, versions in (("", "versions"), ("conditions", " ")):
            with self.assertRaises(contracts.RetrievalContractError):
                dedup.BodyDedupProof(applicability, versions)

    def test_bad_proof_or_adapter_failure_rolls_back_all_groups_with_safe_reason(self):
        pool = (candidate("a"), candidate("b"), candidate("c"))

        def fails_after_one_merge(left, right, **kwargs):
            if right.content.identity.document_id == "c":
                raise ValueError("private database credentials must not leak")
            return approved(left, right, **kwargs)

        for policy in (fails_after_one_merge, lambda *args, **kwargs: True):
            result, step = self.process(pool, enabled=True, prover=policy)
            self.assertEqual(result, pool)
            self.assertEqual((step.status, step.reason), ("failed", "compatibility_proof_failed"))

    def test_shared_budget_covers_policy_work_and_late_proof_is_discarded(self):
        pool = (candidate("a"), candidate("b"))

        class Budget:
            expired = False

            def remaining(self):
                return 0 if self.expired else 1

            def check(self):
                if self.expired:
                    raise TimeoutError("deadline")

        budget = Budget()

        def slow_policy(left, right, *, scope, remaining):
            self.assertIs(remaining, budget)
            self.assertIs(scope, self.scope)
            budget.expired = True
            return approved(left, right, scope=scope, remaining=remaining)

        result, step = self.process(pool, enabled=True, prover=slow_policy, remaining=budget)
        self.assertEqual(result, pool)
        self.assertEqual((step.status, step.reason), ("failed", "deadline_exhausted"))
        result, step = self.process(pool, enabled=True, remaining=budget)
        self.assertEqual(result, pool)
        self.assertEqual(step.status, "failed")
