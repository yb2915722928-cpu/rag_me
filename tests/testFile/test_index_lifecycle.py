import importlib
import unittest


indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


class IndexLifecycleTests(unittest.TestCase):
    def test_lifecycle_rejects_invalid_transitions_and_marks_deleted(self):
        item = indexing.IndexItemState("doc", "v1", "chunk", "scheme", "pending")
        item = item.transition("embedded")
        item = item.transition("stored")
        with self.assertRaises(indexing.InvalidLifecycleTransition):
            item.transition("pending")
        deleted = item.transition("deleted")
        self.assertEqual(deleted.status, "deleted")
        self.assertFalse(deleted.searchable)

    def test_failure_preserves_diagnostics_and_retry_identity(self):
        identity = indexing.LogicalIndexIdentity("doc", "v1", "chunk", "scheme")
        failed = indexing.IndexItemState.from_failure(identity, "EMBEDDING_FAILED", "timeout")
        self.assertEqual(failed.retry_count, 0)
        retried = failed.retry()
        self.assertEqual(retried.retry_count, 1)
        self.assertEqual(retried.identity, identity)
        self.assertEqual(retried.status, "pending")


if __name__ == "__main__":
    unittest.main()
