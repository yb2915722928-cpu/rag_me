"""Direct parent stage behavior. Authored test-first; NOT RUN during implementation."""
import importlib
import unittest
from dataclasses import replace
from datetime import datetime, timezone

c = importlib.import_module("app.modules.4_retrievalAndFusion.contracts")
f = importlib.import_module("app.modules.4_retrievalAndFusion.fusion_contracts")
p = importlib.import_module("app.modules.4_retrievalAndFusion.parent_expansion")


class ScopedReader:
    """External authoritative-read boundary; no vector lookup is available."""
    def __init__(self, records):
        self.records = {record.identity: record for record in records}
        self.calls = []

    def read(self, identity, *, scope, remaining=None):
        self.calls.append((identity, scope, remaining))
        return self.records.get(identity)


def record(chunk, text, *, parent=None):
    return c.ContentRecord(c.EvidenceIdentity("kb", "manual", "v1", chunk, "c1"),
                           text, {"uri": "manual.pdf", "chunk": chunk}, parent=parent)


class DirectParentExpansionTests(unittest.TestCase):
    def setUp(self):
        self.scope = c.ReadScope({"kb": "s1"}, c.AuthorizationScope(("kb",)), None,
                                 datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.grandparent = record("grandparent", "Must never replace the direct parent")
        self.parent = record("parent", "The entire parent body, including unmatched text.",
                             parent=self.grandparent.identity)
        self.child = record("child", "Only a small matching fragment", parent=self.parent.identity)

    def test_explicit_expansion_reads_actual_direct_parent_without_vector(self):
        reader = ScopedReader([self.parent, self.grandparent])
        hit = f.FusedCandidate(self.child, .8, ())
        result = p.expand_parents((hit,), store=reader, scope=self.scope, enabled=True)
        self.assertEqual(result.step.status, "complete")
        self.assertEqual(len(result.candidates), 1)
        parent = result.candidates[0]
        self.assertEqual(parent.content, self.parent)
        self.assertEqual(parent.score, .8)
        self.assertEqual(parent.matched_children, (self.child,))
        self.assertEqual(set(parent.represented_identities), {self.parent.identity, self.child.identity})
        self.assertIn(self.parent.source, parent.sources)
        self.assertIn(self.child.source, parent.sources)
        self.assertEqual([call[0] for call in reader.calls], [self.parent.identity])
        self.assertIs(reader.calls[0][1], self.scope)

    def test_siblings_merge_with_max_score_and_working_pool_remains_available(self):
        sibling = record("sibling", "Second matching fragment", parent=self.parent.identity)
        other = record("other", "Additional evidence for final truncation")
        reader = ScopedReader([self.parent])
        hits = (f.FusedCandidate(self.child, .8, ()), f.FusedCandidate(sibling, .6, ()),
                f.FusedCandidate(other, .4, ()))
        result = p.expand_parents(hits, store=reader, scope=self.scope, enabled=True)
        self.assertEqual([hit.content.identity for hit in result.candidates],
                         [self.parent.identity, other.identity])
        self.assertEqual(result.candidates[0].score, .8)
        self.assertEqual(result.candidates[0].matched_children, (self.child, sibling))
        self.assertEqual(len(reader.calls), 1)
        self.assertIn(sibling.source, result.candidates[0].sources)

    def test_missing_or_filtered_parent_preserves_child_or_strictly_fails(self):
        hit = f.FusedCandidate(self.child, .8, ())
        for strict in (False, True):
            with self.subTest(strict=strict):
                result = p.expand_parents((hit,), store=ScopedReader([]), scope=self.scope,
                                          enabled=True, strict=strict)
                self.assertEqual(result.candidates, () if strict else (hit,))
                self.assertEqual(result.step.status, "failed" if strict else "partial")
                self.assertEqual(result.step.reason, "parent_unavailable")

    def test_wrong_full_identity_is_never_delivered(self):
        for field, value in (("knowledge_base_id", "other"), ("document_id", "other"),
                             ("document_version", "v2"), ("chunk_id", "wrong"),
                             ("chunk_version", "c2")):
            with self.subTest(field=field):
                wrong = replace(self.parent, identity=replace(self.parent.identity, **{field: value}), parent=None)
                reader = ScopedReader([])
                reader.records[self.parent.identity] = wrong
                hit = f.FusedCandidate(self.child, .8, ())
                result = p.expand_parents((hit,), store=reader, scope=self.scope, enabled=True)
                self.assertEqual(result.candidates, (hit,))
                self.assertEqual(result.step.reason, "parent_invalid_relation")

    def test_disabled_and_no_parent_have_explicit_skipped_status(self):
        reader = ScopedReader([])
        hit = f.FusedCandidate(self.child, .8, ())
        disabled = p.expand_parents((hit,), store=reader, scope=self.scope)
        self.assertEqual(disabled.candidates, (hit,))
        self.assertEqual((disabled.step.status, disabled.step.reason), ("skipped", "disabled"))
        orphan = f.FusedCandidate(record("root", "Root content"), .2, ())
        result = p.expand_parents((orphan,), store=reader, scope=self.scope, enabled=True)
        self.assertEqual((result.step.status, result.step.reason), ("skipped", "not_applicable"))
        self.assertEqual(reader.calls, [])

    def test_reader_errors_are_sanitized_and_not_confused_with_no_parent(self):
        class BrokenReader:
            def read(self, identity, *, scope, remaining=None):
                raise RuntimeError("secret body and connection string")
        hit = f.FusedCandidate(self.child, .8, ())
        result = p.expand_parents((hit,), store=BrokenReader(), scope=self.scope, enabled=True)
        self.assertEqual(result.candidates, (hit,))
        self.assertEqual((result.step.status, result.step.reason), ("partial", "parent_read_failed"))

    def test_expired_remaining_budget_stops_reads_without_creating_new_budget(self):
        class Expired:
            def check(self):
                raise TimeoutError("request deadline expired")
            def remaining(self):
                return 0
        reader = ScopedReader([self.parent])
        hit = f.FusedCandidate(self.child, .8, ())
        result = p.expand_parents((hit,), store=reader, scope=self.scope,
                                  enabled=True, remaining=Expired())
        self.assertEqual(result.candidates, (hit,))
        self.assertEqual(result.step.reason, "parent_budget_exhausted")
        self.assertEqual(reader.calls, [])

    def test_late_parent_is_rejected_and_same_budget_is_forwarded(self):
        class Budget:
            expired = False
            def check(self):
                if self.expired:
                    raise TimeoutError("expired")
            def remaining(self):
                return 0 if self.expired else .01
        budget = Budget()
        parent = self.parent
        seen = []
        class LateReader:
            def read(self, identity, *, scope, remaining=None):
                seen.append(remaining)
                remaining.expired = True
                return parent
        hit = f.FusedCandidate(self.child, .8, ())
        result = p.expand_parents((hit,), store=LateReader(), scope=self.scope,
                                  enabled=True, remaining=budget)
        self.assertEqual(seen, [budget])
        self.assertEqual(result.candidates, (hit,))
        self.assertEqual(result.step.reason, "parent_budget_exhausted")

    def test_scope_authorization_is_never_widened_by_child_hit(self):
        hit = f.FusedCandidate(self.child, .8, ())
        denied = replace(self.scope, authorization=c.AuthorizationScope(("kb",), {"kb": ()}))
        reader = ScopedReader([self.parent])
        result = p.expand_parents((hit,), store=reader, scope=denied, enabled=True, strict=True)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.step.reason, "parent_unavailable")
        self.assertEqual(reader.calls, [])

    def test_malformed_cross_document_relation_fails_before_read(self):
        # Corrupt external adapter data cannot bypass ContentRecord's invariant.
        malformed = record("corrupt", "compliant child")
        object.__setattr__(malformed, "parent", replace(self.parent.identity, document_version="v2"))
        hit = f.FusedCandidate(malformed, .8, ())
        reader = ScopedReader([self.parent])
        result = p.expand_parents((hit,), store=reader, scope=self.scope, enabled=True)
        self.assertEqual(result.candidates, (hit,))
        self.assertEqual(result.step.reason, "parent_invalid_relation")
        self.assertEqual(reader.calls, [])

    def test_equal_score_parents_have_stable_full_identity_order(self):
        second_parent = record("aaa", "A different parent")
        sibling = record("second-child", "A match", parent=second_parent.identity)
        reader = ScopedReader([self.parent, second_parent])
        hits = (f.FusedCandidate(self.child, .5, ()), f.FusedCandidate(sibling, .5, ()))
        first = p.expand_parents(hits, store=reader, scope=self.scope, enabled=True)
        second = p.expand_parents(reversed(hits), store=reader, scope=self.scope, enabled=True)
        self.assertEqual([hit.content.identity for hit in first.candidates],
                         [second_parent.identity, self.parent.identity])
        self.assertEqual([hit.content.identity for hit in first.candidates],
                         [hit.content.identity for hit in second.candidates])

    def test_merge_preserves_every_route_scheme_score_trace_without_rescoring(self):
        sibling = record("sibling", "Another hit", parent=self.parent.identity)
        vector = f.ScoreTrace("vector", "kb", "vector", 1, .93, "cosine",
                              "model-v1", self.child.identity, "s1", 2., .032)
        lexical = f.ScoreTrace("bm25", "kb", "bm25", 3, 7.5, "bm25",
                               None, sibling.identity, "s1", 1., .016)
        hits = (f.FusedCandidate(self.child, .032, (vector,)),
                f.FusedCandidate(sibling, .016, (lexical,)))
        result = p.expand_parents(hits, store=ScopedReader([self.parent]),
                                  scope=self.scope, enabled=True)
        self.assertEqual(result.candidates[0].traces, (vector, lexical))
        self.assertEqual(result.candidates[0].score, .032)
        self.assertEqual(result.candidates[0].matched_children, (self.child, sibling))

    def test_child_trace_from_other_snapshot_cannot_trigger_parent_read(self):
        trace = f.ScoreTrace("vector", "kb", "vector", 1, .9, "cosine",
                             "model-v1", self.child.identity, "new-snapshot", 1., .016)
        hit = f.FusedCandidate(self.child, .016, (trace,))
        reader = ScopedReader([self.parent])
        result = p.expand_parents((hit,), store=reader, scope=self.scope, enabled=True, strict=True)
        self.assertEqual(result.step.reason, "parent_scope_mismatch")
        self.assertEqual(result.candidates, ())
        self.assertEqual(reader.calls, [])

    def test_two_node_cycle_is_not_expanded(self):
        cyclic = replace(self.parent, parent=self.child.identity)
        hit = f.FusedCandidate(self.child, .8, ())
        result = p.expand_parents((hit,), store=ScopedReader([cyclic]), scope=self.scope, enabled=True)
        self.assertEqual(result.candidates, (hit,))
        self.assertEqual(result.step.reason, "parent_invalid_relation")
