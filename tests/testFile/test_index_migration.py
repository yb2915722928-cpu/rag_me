import importlib
import unittest


indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


class IndexMigrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = indexing.InMemoryIndexRegistry()
        self.old = indexing.IndexSchemeVersion(indexing.EmbeddingMetadata(
            "test", "model-a", "v1", 3, "cosine", "unit", "chunks-v1",
        ))
        self.new = indexing.IndexSchemeVersion(indexing.EmbeddingMetadata(
            "test", "model-b", "v2", 3, "cosine", "unit", "chunks-v2",
        ))
        self.registry.register(self.old)
        self.registry.seed(self.old, ["a", "b"], [[1, 0, 0], [0, 1, 0]])
        self.registry.activate(self.old, lambda report: report.valid)

    def test_failed_validation_keeps_old_active_and_success_switches_retaining_old(self):
        self.registry.register(self.new)
        self.registry.seed(self.new, ["a"], [[1, 0, 0]])
        with self.assertRaises(indexing.IndexValidationError):
            self.registry.activate(self.new, lambda report: report.valid)
        self.assertEqual(self.registry.active_scheme, self.old)
        self.registry.seed(self.new, ["b"], [[0, 1, 0]])
        self.registry.activate(self.new, lambda report: report.valid)
        self.assertEqual(self.registry.active_scheme, self.new)
        self.assertIn(self.old.identity, self.registry.schemes)

    def test_active_version_cannot_be_deleted_and_query_scheme_is_explicit(self):
        self.assertEqual(self.registry.query_scheme(), self.old)
        with self.assertRaises(indexing.ActiveSchemeDeletionError):
            self.registry.delete(self.old)
        self.registry.register(self.new)
        self.registry.seed(self.new, ["a", "b"], [[1, 0, 0], [0, 1, 0]])
        self.registry.activate(self.new, lambda report: report.valid)
        self.registry.delete(self.old)
        self.assertNotIn(self.old.identity, self.registry.schemes)


if __name__ == "__main__":
    unittest.main()
