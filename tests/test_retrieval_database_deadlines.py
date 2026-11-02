"""Database deadline boundary and opt-in real SQL tests; NOT RUN (#87)."""
import importlib
import os
import unittest

budget = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")
database = importlib.import_module("app.modules.4_retrievalAndFusion.database_deadline")


class DatabaseBudgetTests(unittest.TestCase):
    def test_each_statement_uses_remaining_budget_and_expired_work_is_rejected(self):
        instant = [0.0]
        remaining = budget.Deadline(5, clock=lambda: instant[0])
        class Cursor:
            def __init__(self):
                self.statements = []
            def execute(self, sql, parameters=None):
                self.statements.append((sql, parameters))
        raw = Cursor()
        cursor = database.DeadlineCursor(raw, remaining)
        cursor.execute("SELECT 1")
        instant[0] = 4.0
        cursor.execute("SELECT 2")
        self.assertEqual(raw.statements[0][1], ("5000",))
        self.assertEqual(raw.statements[2][1], ("1000",))
        instant[0] = 5.0
        with self.assertRaises(budget.DeadlineExceeded):
            cursor.execute("SELECT 3")
        self.assertEqual(len(raw.statements), 4)

    def test_durable_request_repository_uses_retrieval_connection_and_sql_budget(self):
        from app.models.db.pgvector import PostgresVectorStore
        calls = []
        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def execute(self, sql, parameters=None):
                calls.append((sql, parameters))
            def fetchone(self):
                return None
        class Connection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def cursor(self):
                return Cursor()
            def close(self):
                pass
        options = []
        def connect(dsn, **kwargs):
            options.append(kwargs)
            return Connection()
        store = PostgresVectorStore("unused", connect=connect)
        with budget.deadline_scope(budget.Deadline(3, clock=lambda: 0)):
            with self.assertRaises(KeyError):
                store.get_attempt("missing")
        self.assertEqual(options, [{"connect_timeout": 3}])
        self.assertIn("statement_timeout", calls[0][0])
        self.assertEqual(calls[0][1], ("3000",))
        self.assertIn("embedding_request_attempts", calls[1][0])


@unittest.skipUnless(os.environ.get("RETRIEVAL_TEST_DSN"), "requires explicitly provisioned PostgreSQL")
class RealDatabaseDeadlineTests(unittest.TestCase):
    def test_actual_statement_timeout_interrupts_sleep(self):
        import psycopg
        remaining = budget.Deadline(.1)
        with psycopg.connect(os.environ["RETRIEVAL_TEST_DSN"]) as connection:
            with connection.cursor() as raw:
                cursor = database.DeadlineCursor(raw, remaining)
                with self.assertRaises(psycopg.errors.QueryCanceled):
                    cursor.execute("SELECT pg_sleep(2)")
