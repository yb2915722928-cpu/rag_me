import importlib
import unittest


embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")


class EmbeddingContractTests(unittest.TestCase):
    def test_scheme_identity_includes_all_semantic_configuration(self):
        metadata = embedding.EmbeddingMetadata(
            provider="test", model="hash", model_revision="v1", dimensions=3,
            metric="cosine", normalization="unit", chunking_policy="fixed:v2",
        )
        scheme = embedding.IndexSchemeVersion(metadata)
        self.assertEqual(scheme.identity, "test/hash@v1:3:cosine:unit:fixed:v2")
        self.assertEqual(scheme, embedding.IndexSchemeVersion(metadata))
        self.assertNotEqual(
            scheme,
            embedding.IndexSchemeVersion(metadata.with_changes(model_revision="v2")),
        )

    def test_adapter_rejects_incompatible_vector_metadata_before_encoding(self):
        adapter = embedding.DeterministicEmbeddingAdapter(dimensions=3, normalization="unit")
        with self.assertRaises(embedding.EmbeddingContractError):
            embedding.IndexSchemeVersion(embedding.EmbeddingMetadata(
                provider="test", model="hash", model_revision="v1", dimensions=3,
                metric="dot", normalization="unit", chunking_policy="fixed:v1",
            ))
        with self.assertRaises(embedding.EmbeddingContractError):
            adapter.validate_scheme(embedding.IndexSchemeVersion(embedding.EmbeddingMetadata(
                provider="test", model="hash", model_revision="v1", dimensions=3,
                metric="cosine", normalization="none", chunking_policy="fixed:v1",
            )))

    def test_deterministic_adapter_returns_declared_dimension_and_repeatable_vectors(self):
        adapter = embedding.DeterministicEmbeddingAdapter(dimensions=3)
        first = adapter.embed(["alpha", "beta"])
        second = adapter.embed(["alpha", "beta"])
        self.assertEqual(first, second)
        self.assertEqual([len(vector) for vector in first], [3, 3])
        self.assertAlmostEqual(sum(value * value for value in first[0]) ** 0.5, 1.0)


if __name__ == "__main__":
    unittest.main()
