"""FAQ contract behavior. Authored test-first; execution deliberately deferred."""
import importlib
import unittest

faq = importlib.import_module("app.modules.4_retrievalAndFusion.faq_contracts")
r = importlib.import_module("app.modules.4_retrievalAndFusion.contracts")


class FAQContractTests(unittest.TestCase):
    def test_faq_identity_roundtrips_without_document_fields(self):
        identity = faq.FAQIdentity("kb", "reset", "v1")
        self.assertEqual(faq.FAQIdentity.from_key(identity.key), identity)
        self.assertEqual(identity.parts, ("faq", "kb", "reset", "v1"))
        self.assertFalse(hasattr(identity, "document_id"))
        with self.assertRaises(r.RetrievalContractError):
            faq.FAQIdentity.from_key(r.EvidenceIdentity("kb", "reset", "v1", "q", "c1").key)

    def test_answer_is_evidence_and_questions_are_distinct_recall_inputs(self):
        record = faq.FAQRecord(faq.FAQIdentity("kb", "reset", "v1"),
                               "How to reset?", ("Reset steps?", "How to reset?", "Reset steps?"),
                               "Hold the reset button.", {"product": "AX-100"}, {"uri": "faq/reset"})
        self.assertEqual(record.questions, ("How to reset?", "Reset steps?"))
        self.assertEqual(record.text, "Hold the reset button.")
        self.assertEqual(record.metadata, {"product": "AX-100"})
        self.assertIsNone(record.parent)

    def test_faq_only_grants_do_not_grant_documents(self):
        scope = r.AuthorizationScope(("kb",), faq_item_ids={"kb": ("reset",)})
        self.assertEqual(scope.faq_item_ids["kb"], ("reset",))
        self.assertEqual(scope.document_ids["kb"], ())
        both = r.AuthorizationScope(("kb",), {"kb": ("manual",)}, {"kb": ("reset",)})
        self.assertEqual(both.document_ids["kb"], ("manual",))
        with self.assertRaises(r.RetrievalContractError):
            r.AuthorizationScope(("kb",), faq_item_ids={"other": ("reset",)})

    def test_required_content_is_rejected_before_ingest(self):
        for field, value in (("standard_question", ""), ("answer", " "),
                             ("source", {}), ("conditions", None), ("similar_questions", ("",))):
            args = dict(identity=faq.FAQIdentity("kb", "reset", "v1"),
                        standard_question="Reset?", similar_questions=(), answer="Hold button.",
                        conditions={}, source={"uri": "faq/reset"})
            args[field] = value
            with self.assertRaises(r.RetrievalContractError):
                faq.FAQRecord(**args)
