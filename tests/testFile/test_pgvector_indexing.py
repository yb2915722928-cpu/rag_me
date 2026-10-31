import importlib
import os
import unittest


indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "set TEST_DATABASE_URL for PostgreSQL/pgvector integration tests")
class PgVectorIndexingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = indexing.PostgresVectorStore(os.environ["TEST_DATABASE_URL"])
        cls.store.migrate(dimensions=3)

    def test_same_scheme_cosine_retrieval_is_idempotent_and_persists_chunk(self):
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        scheme = indexing.IndexSchemeVersion(adapter.metadata)
        chunk = indexing.ChunkRecord(
            chunk_id="chunk-1", document_id="doc-1", document_version="v1",
            text="alpha", metadata={"source_ids": ["source-1"]},
        )
        self.store.upsert(scheme, chunk, adapter.embed([chunk.text])[0])
        self.store.upsert(scheme, chunk, adapter.embed([chunk.text])[0])
        found = self.store.search(scheme, adapter.embed(["alpha"])[0], limit=5)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].chunk.text, "alpha")
        self.assertEqual(found[0].chunk.metadata["source_ids"], ["source-1"])

    def test_dimension_mismatch_is_rejected_before_database_write(self):
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        scheme = indexing.IndexSchemeVersion(adapter.metadata)
        chunk = indexing.ChunkRecord("chunk-2", "doc-1", "v1", "beta", {})
        with self.assertRaises(indexing.EmbeddingContractError):
            self.store.upsert(scheme, chunk, (1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
