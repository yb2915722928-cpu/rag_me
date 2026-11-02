"""Public handoff contract; authored test-first, not executed for #83."""
import importlib
import unittest
from dataclasses import replace

retrieval = importlib.import_module("app.modules.4_retrievalAndFusion")
chunking = importlib.import_module("app.modules.2_documentChunking.models")


class ContentHandoffTests(unittest.TestCase):
    def setUp(self):
        self.chunk = chunking.Chunk(
            "child", "manual", None, "upstream-only", "USB-C 使用说明", 0,
            source_ids=("page-3",), parent_chunk_id="parent",
            metadata={"product": "AX-100"}, requires_review=True, projected_context=True,
            strategy="parent_child", child_chunk_ids=("unresolved-child",),
        )
        self.parent = retrieval.EvidenceIdentity("kb", "manual", "2026", "parent", "p2")

    def test_explicit_revisions_and_source_survive_module3_handoff(self):
        record = retrieval.ContentRecord.from_chunk(
            self.chunk, knowledge_base_id="kb", document_version="2026",
            chunk_version="c2", parent=self.parent,
        )
        self.assertEqual(record.identity, retrieval.EvidenceIdentity("kb", "manual", "2026", "child", "c2"))
        self.assertEqual(record.parent, self.parent)
        self.assertEqual(record.source["source_ids"], ["page-3"])
        self.assertEqual(record.source["upstream_version"], "upstream-only")
        self.assertTrue(record.source["requires_review"])
        self.assertTrue(record.source["projected_context"])
        self.assertEqual(record.source["strategy"], "parent_child")
        self.assertEqual(record.source["child_chunk_ids"], ["unresolved-child"])
        indexed = record.to_chunk_record()
        self.assertEqual((indexed.document_version, indexed.chunk_version), ("2026", "c2"))
        self.assertEqual(indexed.metadata["knowledge_base_id"], "kb")
        self.assertEqual(indexed.text, "USB-C 使用说明")

    def test_missing_identity_and_unresolved_parent_are_rejected(self):
        for kwargs in ({"document_version": ""}, {"chunk_version": ""}, {"knowledge_base_id": ""}):
            arguments = dict(knowledge_base_id="kb", document_version="2026", chunk_version="c2", parent=self.parent)
            arguments.update(kwargs)
            with self.assertRaises(retrieval.RetrievalContractError):
                retrieval.ContentRecord.from_chunk(self.chunk, **arguments)
        with self.assertRaisesRegex(retrieval.RetrievalContractError, "parent"):
            retrieval.ContentRecord.from_chunk(self.chunk, knowledge_base_id="kb", document_version="2026", chunk_version="c2")
        with self.assertRaisesRegex(retrieval.RetrievalContractError, "parent"):
            retrieval.ContentRecord.from_chunk(self.chunk, knowledge_base_id="kb", document_version="2026", chunk_version="c2", parent=replace(self.parent, document_version="old"))

    def test_identity_is_not_index_scheme_and_payload_is_detached(self):
        metadata = {"product": "AX-100"}
        record = retrieval.ContentRecord(self.parent, "parent body", {"uri": "manual.pdf"}, metadata)
        metadata["product"] = "changed"
        self.assertEqual(record.metadata["product"], "AX-100")
        self.assertEqual(retrieval.EvidenceIdentity.from_key(record.identity.key), record.identity)
        with self.assertRaises(retrieval.RetrievalContractError):
            retrieval.ContentRecord(self.parent, "body", {})
