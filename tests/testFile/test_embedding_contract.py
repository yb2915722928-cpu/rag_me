import importlib
import unittest
from dataclasses import asdict

from app.models.embedding import scheme_from_metadata

embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")


class EmbeddingContractTests(unittest.TestCase):
    def setUp(self):
        self.adapter = embedding.DeterministicEmbeddingAdapter(3)

    def test_scheme_identity_includes_all_semantic_configuration(self):
        metadata = self.adapter.metadata
        scheme = embedding.IndexSchemeVersion(metadata)
        for changes in (
            {"model_revision": "v2"}, {"chunking_policy": "fixed:v2"},
            {"normalization": "none"},
            {"query_role": embedding.EmbeddingRoleConfig("query", "other", "query:", "v2")},
            {"document_role": embedding.EmbeddingRoleConfig("document", "other", "passage:")},
        ):
            with self.subTest(changes=changes):
                self.assertNotEqual(scheme.identity, embedding.IndexSchemeVersion(metadata.with_changes(**changes)).identity)
        self.assertEqual(scheme, scheme_from_metadata(asdict(metadata)))
        self.assertEqual(scheme.identity, scheme_from_metadata(asdict(metadata)).identity)

    def test_legacy_metadata_cannot_be_used_for_new_encoding(self):
        adapter = embedding.DeterministicEmbeddingAdapter(3)
        adapter.metadata = embedding.EmbeddingMetadata("test", "legacy", "v1", 3)
        self.assertFalse(adapter.metadata.verifiable)
        with self.assertRaises(embedding.EmbeddingContractError):
            adapter.validate_scheme(embedding.IndexSchemeVersion(adapter.metadata))
        with self.assertRaises(embedding.EmbeddingContractError):
            adapter.embed_role(["alpha"], "query")

    def test_roles_apply_only_their_declared_instruction(self):
        adapter = self.adapter
        adapter.metadata = adapter.metadata.with_changes(
            document_role=embedding.EmbeddingRoleConfig("document", "encoder", "passage: "),
            query_role=embedding.EmbeddingRoleConfig("query", "encoder", "query: "),
        )
        self.assertEqual(adapter.embed_role(["alpha"], "document"), adapter.embed(["passage: alpha"]))
        self.assertEqual(adapter.embed_role(["alpha"], "query"), adapter.embed(["query: alpha"]))
        with self.assertRaises(embedding.EmbeddingContractError):
            adapter.embed_role(["alpha"], "unspecified")
        adapter.metadata = adapter.metadata.with_changes(query_role=embedding.EmbeddingRoleConfig("query", "different-endpoint"))
        with self.assertRaises(embedding.EmbeddingContractError):
            adapter.embed_role(["alpha"], "query")

    def test_incompatible_scheme_rejected_before_encoding(self):
        with self.assertRaises(embedding.EmbeddingContractError):
            self.adapter.validate_scheme(embedding.IndexSchemeVersion(self.adapter.metadata.with_changes(model_revision="v2")))
        with self.assertRaises(embedding.EmbeddingContractError):
            self.adapter.metadata.with_changes(metric="dot")

    def test_fingerprint_is_reproducible_and_does_not_rewrite_text(self):
        fingerprint = embedding.content_fingerprint
        metadata = self.adapter.metadata
        self.assertEqual(fingerprint("alpha", metadata, "document"), fingerprint("alpha", metadata, "document"))
        for text in (" alpha", "alpha ", "Alpha", "a\u0301", "á"):
            self.assertNotEqual(fingerprint("alpha", metadata, "document"), fingerprint(text, metadata, "document"))
        self.assertNotEqual(fingerprint("alpha", metadata, "document"), fingerprint("alpha", metadata, "query"))
        self.assertNotEqual(fingerprint("alpha", metadata, "document"), fingerprint("alpha", metadata.with_changes(document_role=embedding.EmbeddingRoleConfig("document", "changed")), "document"))

    def test_deterministic_adapter_returns_valid_repeatable_vectors(self):
        first = self.adapter.embed(["alpha", "beta"])
        self.assertEqual(first, self.adapter.embed(["alpha", "beta"]))
        self.assertEqual([len(vector) for vector in first], [3, 3])
        self.assertAlmostEqual(sum(value * value for value in first[0]) ** 0.5, 1)


if __name__ == "__main__":
    unittest.main()
