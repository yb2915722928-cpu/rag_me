import importlib
import unittest


indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


class FakeStore:
    def __init__(self):
        self.rows = {}

    def upsert(self, scheme, chunk, vector):
        self.rows[(scheme.identity, chunk.document_id, chunk.version, chunk.chunk_id)] = (chunk, tuple(vector))

    def search(self, scheme, vector, limit=10):
        def score(row):
            values = row[1]
            return sum(left * right for left, right in zip(values, vector))
        rows = sorted((row for key, row in self.rows.items() if key[0] == scheme.identity), key=score, reverse=True)[:limit]
        return [indexing.SearchHit(row[0], score(row), scheme.identity) for row in rows]


class EmbeddingIntegrationTests(unittest.TestCase):
    def test_chunk_to_embedding_to_same_scheme_search_preserves_chunk_context(self):
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        store = FakeStore()
        chunk = indexing.ChunkRecord("c1", "doc", "v1", "alpha", {
            "source_ids": ["src"], "structure_path": ["Heading"], "body_span": [0, 5],
        })
        result = indexing.index_chunks([chunk], adapter, store)
        self.assertEqual(result[0].status, "stored")
        hits = indexing.search_chunks("alpha", adapter, store)
        self.assertEqual(hits[0].chunk.chunk_id, "c1")
        self.assertEqual(hits[0].chunk.metadata["structure_path"], ["Heading"])


if __name__ == "__main__":
    unittest.main()
