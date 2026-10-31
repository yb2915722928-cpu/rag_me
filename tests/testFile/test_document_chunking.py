import copy
import importlib
import unittest


handoff = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff"
)
chunking = importlib.import_module("app.modules.2_documentChunking")


class DocumentChunkingTests(unittest.TestCase):
    def make_document(self, *, status="success", units=None, body="abcdefghij"):
        units = units if units is not None else [
            handoff.ContentUnit(
                "u1", "paragraph", body, ["s1"], handoff.BodySpan(0, len(body)), "exact",
                metadata={"structure_path": ["Title"]},
            )
        ]
        return handoff.Document(
            "d1", body, "text", status, business_id="biz", version="v1",
            sources=[handoff.Source("s1", "text", {"path": "memory"})], units=units,
        )

    def test_character_chunks_keep_identity_order_and_exact_span(self):
        doc = self.make_document()
        before = copy.deepcopy(doc)
        result = chunking.chunk_document(doc, config=chunking.ChunkingConfig(size=4))
        self.assertEqual([item.text for item in result.chunks], ["abcd", "efgh", "ij"])
        self.assertEqual(result.chunks[0].body_span, (0, 4))
        self.assertEqual(result.chunks[0].alignment, "exact")
        self.assertEqual(result.chunks[0].business_id, "biz")
        self.assertEqual(doc, before)

    def test_token_counter_is_injected_and_missing_is_rejected(self):
        doc = self.make_document()
        with self.assertRaises(chunking.InvalidChunkingConfiguration):
            chunking.chunk_document(doc, config=chunking.ChunkingConfig(count_mode="tokens"))
        result = chunking.chunk_document(
            doc, config=chunking.ChunkingConfig(size=2, count_mode="tokens", token_counter=lambda value: len(value.split()))
        )
        self.assertTrue(result.chunks)
        self.assertEqual(result.chunks[0].count_mode, "tokens")

    def test_unmapped_does_not_invent_span(self):
        unit = handoff.ContentUnit("u1", "service", "opaque", ["s1"], None, "unmapped")
        result = chunking.chunk_document(self.make_document(body="", units=[unit]))
        self.assertEqual(result.chunks[0].body_span, None)
        self.assertEqual(result.chunks[0].alignment, "unmapped")

    def test_protected_table_is_not_split_and_reports_budget(self):
        units = [handoff.ContentUnit(
            "row", "table_row", "a | b | c", ["s1"], None, "unmapped",
            metadata={"table_id": "t1", "row_index": 1},
        )]
        result = chunking.chunk_document(self.make_document(body="", units=units), config=chunking.ChunkingConfig(size=2))
        self.assertEqual(result.chunks[0].text, "a | b | c")
        self.assertEqual(result.chunks[0].diagnostics[0]["code"], "PROTECTED_UNIT_OVER_BUDGET")

    def test_parent_child_relationships_are_bidirectional(self):
        doc = self.make_document(body="abcdefgh", units=[
            handoff.ContentUnit("u1", "paragraph", "abcd", ["s1"], handoff.BodySpan(0, 4), "exact"),
            handoff.ContentUnit("u2", "paragraph", "efgh", ["s1"], handoff.BodySpan(4, 8), "exact"),
        ])
        result = chunking.chunk_document(doc, config=chunking.ChunkingConfig(size=4, parent_child=True, parent_size=8))
        children = result.chunks[:2]
        parent = result.chunks[-1]
        self.assertEqual(parent.child_chunk_ids, tuple(item.chunk_id for item in children))
        self.assertTrue(all(item.parent_chunk_id == parent.chunk_id for item in children))

    def test_failed_document_does_not_create_content(self):
        result = chunking.chunk_document(self.make_document(status="failed"))
        self.assertEqual(result.chunks, ())
        self.assertEqual(result.diagnostics[0]["code"], "DOCUMENT_NOT_CHUNKED")

    def test_invalid_exact_span_does_not_guess_duplicate_text(self):
        doc = self.make_document(body="xxabcabc", units=[
            handoff.ContentUnit("u1", "paragraph", "abc", ["s1"], handoff.BodySpan(2, 5), "exact"),
            handoff.ContentUnit("u2", "paragraph", "abc", ["s1"], handoff.BodySpan(5, 8), "exact"),
        ])
        result = chunking.chunk_document(doc, config=chunking.ChunkingConfig(size=3))
        self.assertEqual([item.body_span for item in result.chunks], [(2, 5), (5, 8)])
        self.assertTrue(all(item.alignment == "exact" for item in result.chunks))

    def test_cross_source_units_are_not_combined(self):
        doc = self.make_document(body="abcdef", units=[
            handoff.ContentUnit("u1", "paragraph", "abc", ["s1"], handoff.BodySpan(0, 3), "exact"),
            handoff.ContentUnit("u2", "paragraph", "def", ["s2"], handoff.BodySpan(3, 6), "exact"),
        ])
        doc.sources.append(handoff.Source("s2", "text", {"path": "other"}))
        result = chunking.chunk_document(doc, config=chunking.ChunkingConfig(size=20))
        self.assertEqual([item.text for item in result.chunks], ["abc", "def"])

    def test_context_projection_marks_mapping_as_document(self):
        result = chunking.chunk_document(self.make_document(), config=chunking.ChunkingConfig(size=20, context_projection=True))
        self.assertEqual(result.chunks[0].alignment, "document")
        self.assertIsNone(result.chunks[0].body_span)
        self.assertTrue(any(item["code"] == "CONTEXT_PROJECTED" for item in result.chunks[0].diagnostics))

    def test_handoff_diagnostics_are_propagated(self):
        diagnostic = handoff.Diagnostic("warning", "UPSTREAM_WARN", "check this")
        doc = self.make_document()
        doc.diagnostics.append(diagnostic)
        result = chunking.chunk_document(doc)
        self.assertEqual(result.diagnostics[0]["code"], "UPSTREAM_WARN")


if __name__ == "__main__":
    unittest.main()
