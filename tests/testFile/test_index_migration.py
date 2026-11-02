import importlib
import unittest


indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


class IndexMigrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = indexing.InMemoryIndexRegistry()
        base = indexing.DeterministicEmbeddingAdapter(3).metadata
        self.old = indexing.IndexSchemeVersion(base.with_changes(model="model-a", chunking_policy="chunks-v1"))
        self.new = indexing.IndexSchemeVersion(base.with_changes(model="model-b", model_revision="v2", chunking_policy="chunks-v2"))
        self.registry.register(self.old)
        self.registry.seed(self.old, ["a", "b"], [[1, 0, 0], [0, 1, 0]])
        self.registry.activate(self.old, lambda report: report.valid, expected_keys={"a", "b"}, representative_vector=[1, 0, 0])

    def test_failed_validation_keeps_old_active_and_success_switches_retaining_old(self):
        self.registry.register(self.new)
        self.registry.seed(self.new, ["a"], [[1, 0, 0]])
        with self.assertRaises(indexing.IndexValidationError):
            self.registry.activate(self.new, lambda report: report.valid, expected_keys={"a", "b"}, representative_vector=[1, 0, 0])
        self.assertEqual(self.registry.active_scheme, self.old)
        self.registry.seed(self.new, ["b"], [[0, 1, 0]])
        self.registry.activate(self.new, lambda report: report.valid, expected_keys={"a", "b"}, representative_vector=[1, 0, 0])
        self.assertEqual(self.registry.active_scheme, self.new)
        self.assertIn(self.old.identity, self.registry.schemes)

    def test_active_version_cannot_be_deleted_and_query_scheme_is_explicit(self):
        self.assertEqual(self.registry.query_scheme(), self.old)
        with self.assertRaises(indexing.ActiveSchemeDeletionError):
            self.registry.delete(self.old)
        self.registry.register(self.new)
        self.registry.seed(self.new, ["a", "b"], [[1, 0, 0], [0, 1, 0]])
        self.registry.activate(self.new, lambda report: report.valid, expected_keys={"a", "b"}, representative_vector=[1, 0, 0])
        self.registry.delete(self.old)
        self.assertNotIn(self.old.identity, self.registry.schemes)

    def test_validation_checks_expected_identity_set_and_representative_key(self):
        self.registry.register(self.new)
        self.registry.seed(self.new, ["wrong-a", "wrong-b"], [[1, 0, 0], [0, 1, 0]])
        with self.assertRaises(indexing.IndexValidationError):
            self.registry.activate(self.new, lambda report: report.valid, expected_keys={"a", "b"}, representative_vector=[1, 0, 0])

    def test_initial_activation_requires_identity_manifest(self):
        registry = indexing.InMemoryIndexRegistry()
        registry.register(self.new)
        registry.seed(self.new, ["unexpected"], [[1, 0, 0]])
        with self.assertRaises(indexing.IndexValidationError):
            registry.activate(self.new)
        registry.activate(self.new, expected_keys={"unexpected"}, representative_vector=[1, 0, 0])

    def test_invalid_vectors_are_rejected_during_build(self):
        self.registry.register(self.new)
        with self.assertRaises(indexing.EmbeddingContractError):
            self.registry.seed(self.new, ["a"], [[0, 0, 0]])
