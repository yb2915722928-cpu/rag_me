"""Real PostgreSQL pin + shared budget regression; authored only, NOT RUN (#87)."""
import importlib
import os
import uuid

import unittest

r = importlib.import_module("app.modules.4_retrievalAndFusion")


class PinBudgetPostgresTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("RETRIEVAL_TEST_DSN"), "requires explicit disposable PostgreSQL")
    def test_public_query_pins_repeatable_read_before_budget_sql(self):
        import psycopg
        from psycopg import sql
        dsn = os.environ["RETRIEVAL_TEST_DSN"]
        schema = "deadline_" + uuid.uuid4().hex
        store = r.PostgresRetrievalStore(dsn, schema=schema)
        try:
            store.migrate()
            record = r.ContentRecord(r.EvidenceIdentity("kb", "doc", "v1", "chunk", "c1"),
                                     "budget pin", {"uri": "test://pin"}, {})
            store.ingest([record])
            store.prepare("kb", "s1", [record.identity])
            store.publish("kb", "s1")
            def route(query, *, scope, remaining, **kwargs):
                assert remaining.remaining() > 0
                assert store.read(record.identity, scope=scope) == record
                return r.RouteResult("kb:content", "kb", "content", "empty")
            result = r.RetrievalService(store, routes=[r.RetrievalRoute("kb:content", "kb", "content", route)]).query(
                "budget", knowledge_base_ids=["kb"], authorization=r.AuthorizationScope(("kb",)))
            assert result.status == "complete"
            assert dict(result.scope.snapshots) == {"kb": "s1"}
        finally:
            with psycopg.connect(dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
