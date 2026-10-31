import importlib
import unittest


embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")


class FailingAdapter(embedding.DeterministicEmbeddingAdapter):
    def embed(self, texts):
        if "bad" in texts:
            raise RuntimeError("temporary failure")
        return super().embed(texts)


class MalformedVectorAdapter(embedding.DeterministicEmbeddingAdapter):
    def embed(self, texts):
        vectors = super().embed(texts)
        vectors[1] = (float("nan"),) * self.metadata.dimensions
        return vectors


class EmbeddingBatchingTests(unittest.TestCase):
    def test_batches_obey_item_and_token_limits_in_input_order(self):
        adapter = embedding.DeterministicEmbeddingAdapter(dimensions=3, token_counter=str.split)
        result = embedding.embed_texts(["a b", "c", "d e f", "g"], adapter, max_batch_size=3, max_tokens=3)
        self.assertEqual([item.key for item in result.items], ["0", "1", "2", "3"])
        self.assertEqual([item.status for item in result.items], ["embedded"] * 4)
        self.assertEqual(result.items[0].vector, adapter.embed(["a b"])[0])

    def test_failed_batch_preserves_success_and_retry_is_idempotent_by_identity(self):
        adapter = FailingAdapter(dimensions=3, token_counter=str.split)
        result = embedding.embed_texts(["ok", "bad", "fine"], adapter, max_batch_size=1)
        self.assertEqual([item.status for item in result.items], ["embedded", "failed", "embedded"])
        self.assertEqual(result.items[1].error_code, "EMBEDDING_FAILED")
        retried = embedding.retry_failed(result, adapter, keys={"1"})
        self.assertEqual([item.status for item in retried.items], ["embedded", "failed", "embedded"])
        fixed = embedding.retry_failed(result, embedding.DeterministicEmbeddingAdapter(3), keys={"1"})
        self.assertEqual([item.status for item in fixed.items], ["embedded"] * 3)
        self.assertEqual(len({item.key for item in fixed.items}), 3)
        self.assertEqual(fixed.items[1].retry_count, 1)

    def test_malformed_vector_fails_only_its_own_item(self):
        result = embedding.embed_texts(["good", "bad", "also good"], MalformedVectorAdapter(3))
        self.assertEqual([item.status for item in result.items], ["embedded", "failed", "embedded"])
        self.assertEqual(result.items[1].error_code, "EMBEDDING_FAILED")

    def test_empty_input_and_single_oversized_input_are_explicit(self):
        adapter = embedding.DeterministicEmbeddingAdapter(dimensions=3, token_counter=str.split)
        self.assertEqual(embedding.embed_texts([], adapter).items, ())
        result = embedding.embed_texts(["one two"], adapter, max_tokens=1)
        self.assertEqual(result.items[0].status, "failed")
        self.assertEqual(result.items[0].error_code, "ITEM_EXCEEDS_TOKEN_BUDGET")
        retried = embedding.retry_failed(result, adapter, keys={"0"}, max_tokens=1)
        self.assertEqual(retried.items[0].retry_count, 0)
        self.assertEqual(retried.items[0].error_code, "ITEM_EXCEEDS_TOKEN_BUDGET")
