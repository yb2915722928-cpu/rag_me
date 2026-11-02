"""Real PostgreSQL semantic parity; opt-in test code, NOT RUN for #84."""
from datetime import datetime, timezone
import importlib
import json
import os

import unittest

filters = importlib.import_module("app.modules.4_retrievalAndFusion.typed_filters")


class TypedFilterPostgresTests(unittest.TestCase):
    def _make_pg_connection(self):
        dsn = os.environ.get("RAG_RETRIEVAL_TEST_DSN")
        if not dsn:
            self.skipTest("set RAG_RETRIEVAL_TEST_DSN to a disposable PostgreSQL database")
        import psycopg
        connection = psycopg.connect(dsn)
        self.addCleanup(connection.close)
        return connection

    def test_sql_and_memory_agree_on_public_typed_filter_semantics(self):
        for condition, expected in [
            ({"field": "n", "op": "range", "lower": 10, "upper": 20}, [3]),
            ({"field": "n", "op": "missing"}, [0]),
            ({"field": "n", "op": "is_null"}, [1]),
            ({"field": "n", "op": "exists"}, [1, 2, 3, 4]),
            ({"field": "n", "op": "in", "value": [0, 20]}, [2, 4]),
            ({"field": "flag", "op": "eq", "value": False}, [2]),
            ({"field": "tags", "op": "contains", "value": "AX-100"}, [3, 4]),
            ({"field": "tags", "op": "eq", "value": ["USB-C", "AX-100"]}, [3]),
            ({"field": "tags", "op": "eq", "value": []}, [2]),
            ({"field": "times", "op": "contains", "value": {"now": True}}, [3]),
            ({"field": "times", "op": "eq", "value": ["2026-11-02T10:00:00Z"]}, [3]),
            ({"field": "time", "op": "range", "lower": "2026-11-02T09:00:00Z", "upper": {"now": True}}, [2]),
            ({"and": [{"or": [{"field": "n", "op": "eq", "value": 0},
                               {"field": "n", "op": "eq", "value": 20}]},
                      {"field": "tags", "op": "contains", "value": "AX-100"}]}, [4]),
        ]:
            with self.subTest(condition=condition, expected=expected):
                try:
                    pg_connection = self._make_pg_connection()
                    rows = [
                        {},
                        {"n": None, "flag": None, "tags": None, "times": None, "time": None},
                        {"n": 0, "flag": False, "tags": [], "time": "2026-11-02T17:00:00+08:00"},
                        {"n": 10, "flag": True, "tags": ["AX-100", "USB-C", "AX-100"],
                         "times": ["2026-11-02T18:00:00+08:00"], "time": "2026-11-02T18:00:00+08:00"},
                        {"n": 20, "flag": True, "tags": ["AX-100"]},
                    ]
                    plan = filters.compile_filter(condition, {"n": "number", "flag": "boolean", "tags": "set[string]",
                                                              "times": "set[datetime]", "time": "datetime"},
                                                  now=datetime(2026, 11, 2, 10, tzinfo=timezone.utc))
                    predicate, params = plan.sql("c.metadata")
                    with pg_connection.cursor() as cursor:
                        cursor.execute("SELECT c.ordinality - 1 FROM jsonb_array_elements(%s::jsonb) "
                                       "WITH ORDINALITY AS c(metadata, ordinality) WHERE " + predicate + " ORDER BY c.ordinality",
                                       [json.dumps(rows), *params])
                        assert [row[0] for row in cursor.fetchall()] == expected
                    assert [index for index, row in enumerate(rows) if plan.matches(row)] == expected
                finally:
                    self.doCleanups()
