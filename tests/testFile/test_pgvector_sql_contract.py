import importlib
import unittest


indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


class FakeCursor:
    def __init__(self):
        self.rowcount = 1
        self.statements = []
        self._results = []
        self._last = None

    def execute(self, statement, params=None):
        self.statements.append((" ".join(statement.split()), params))
        normalized = " ".join(statement.split())
        if "SELECT dimensions FROM embedding_schemes" in normalized:
            self._last = (3,)
        elif "SELECT count(*), count(*) FILTER" in normalized:
            self._last = (2, 0, 0)
        elif "SELECT document_id, document_version, chunk_id FROM indexed_chunks" in normalized:
            self._results = [("doc", "v1", "a"), ("doc", "v1", "b")]
        elif "AS score FROM indexed_chunks" in normalized:
            self._last = ("doc", "v1", "a", 1.0)
        else:
            self._last = None

    def fetchone(self):
        return self._last

    def fetchall(self):
        rows, self._results = self._results, []
        return rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.commits += 1
        return False

    def close(self):
        pass


class PgVectorSqlContractTests(unittest.TestCase):
    def setUp(self):
        self.cursor = FakeCursor()
        self.connection = FakeConnection(self.cursor)
        self.store = indexing.PostgresVectorStore("unused", connect=lambda _: self.connection)
        self.adapter = indexing.DeterministicEmbeddingAdapter(3)
        self.scheme = indexing.IndexSchemeVersion(self.adapter.metadata)

    def test_activation_checks_manifest_representative_and_similarity_threshold(self):
        report = self.store.validate_and_activate(
            self.scheme, expected_count=2, representative_vector=(1, 0, 0),
            expected_keys=[("doc", "v1", "a"), ("doc", "v1", "b")],
            representative_key=("doc", "v1", "a"), threshold=0.9,
        )
        self.assertTrue(report["identities_valid"])
        self.assertTrue(report["representative_retrieval"])
        statements = [query for query, _ in self.cursor.statements]
        self.assertTrue(any("AS score FROM indexed_chunks" in query for query in statements))

    def test_activation_rejects_wrong_identity_set(self):
        with self.assertRaises(ValueError):
            self.store.validate_and_activate(
                self.scheme, expected_count=2, representative_vector=(1, 0, 0),
                expected_keys=[("doc", "v1", "missing"), ("doc", "v1", "b")],
            )

    def test_activation_rejects_low_similarity_and_wrong_representative(self):
        self.cursor._last = None
        original_execute = self.cursor.execute

        def low_score(statement, params=None):
            original_execute(statement, params)
            if "AS score FROM indexed_chunks" in " ".join(statement.split()):
                self.cursor._last = ("doc", "v1", "b", 0.2)
        self.cursor.execute = low_score
        with self.assertRaises(ValueError):
            self.store.validate_and_activate(
                self.scheme, expected_count=2, representative_vector=(1, 0, 0),
                expected_keys=[("doc", "v1", "a"), ("doc", "v1", "b")],
                representative_key=("doc", "v1", "a"), threshold=0.9,
            )
