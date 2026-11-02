"""Shared encoding budget propagation for retrieval; authored, NOT RUN (#87)."""
import importlib
import unittest

embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")
budgets = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")


class EncodingBudgetTests(unittest.TestCase):
    def test_deterministic_query_encoding_accepts_original_budget(self):
        adapter = embedding.DeterministicEmbeddingAdapter(4)
        remaining = budgets.Deadline(5)
        result = embedding.embed_texts(["query"], adapter, role="query", remaining=remaining)
        self.assertEqual(result.items[0].status, "embedded")

    def test_expired_budget_never_calls_provider(self):
        remaining = budgets.Deadline(5)
        remaining.cancel()
        with self.assertRaises(budgets.DeadlineExceeded):
            embedding.embed_texts(["query"], embedding.DeterministicEmbeddingAdapter(4),
                                  role="query", remaining=remaining)

    def test_provider_receives_same_budget_and_unsupported_provider_fails(self):
        class Provider(embedding.DeterministicEmbeddingAdapter):
            def embed_role(self, texts, role, *, remaining=None):
                self.seen = remaining
                return super().embed_role(texts, role, remaining=remaining)
        adapter = Provider(4)
        remaining = budgets.Deadline(5)
        embedding.embed_texts(["query"], adapter, role="query", remaining=remaining)
        self.assertIs(adapter.seen, remaining)
        adapter.supports_deadline = False
        with self.assertRaisesRegex(ValueError, "deadline"):
            embedding.embed_texts(["query"], adapter, role="query", remaining=remaining)
