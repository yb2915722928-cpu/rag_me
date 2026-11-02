"""Public ingest/index/prepare/publish/query against real pgvector; NOT RUN.

Requires a disposable database with pgvector >= 0.8.0 already available.
Only the external encoder is deterministic; persistence and ranking are real.
"""
from dataclasses import replace
import importlib
import os
import uuid

import unittest

retrieval = importlib.import_module("app.modules.4_retrievalAndFusion")
indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


def record(kb, document="same", version="v1", chunk="same", revision="c1", **metadata):
    return retrieval.ContentRecord(retrieval.EvidenceIdentity(kb, document, version, chunk, revision),
                                    "candidate " + document, {"uri": "source://" + kb}, metadata)


def publish(store, kb, snapshot, records, adapter, fields=None):
    store.ingest(records)
    result = store.index_documents(records, adapter)
    assert all(item.status == "stored" for item in result.items)
    store.prepare(kb, snapshot, [row.identity for row in records], required_indexes=("content", "vector"),
                  field_types=fields or {}, vector_scheme=indexing.IndexSchemeVersion(adapter.metadata))
    store.publish(kb, snapshot)


class FilteredVectorPostgresTests(unittest.TestCase):
    def _make_store(self):
        dsn = os.environ.get("RAG_RETRIEVAL_TEST_DSN")
        if not dsn:
            self.skipTest("set RAG_RETRIEVAL_TEST_DSN to a disposable pgvector database")
        import psycopg
        from psycopg import sql
        instance = retrieval.PostgresVectorRetrievalStore(dsn, schema="r84_" + uuid.uuid4().hex[:20])
        def cleanup():
            with psycopg.connect(dsn) as connection:
                connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(instance.schema)))
        self.addCleanup(cleanup)
        instance.migrate()
        return instance

    def test_public_chain_preserves_identity_source_and_pinned_versions(self):
        store = self._make_store()
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        a, b = record("a"), record("b")
        publish(store, "a", "s1", [a], adapter)
        publish(store, "b", "s1", [b], adapter)
        auth = retrieval.AuthorizationScope(("a", "b"))
        old_scope = store.pin(("a", "b"), authorization=auth)
        new = record("a", version="v2", revision="c2")
        publish(store, "a", "s2", [new], adapter)
        for kb, expected in (("a", a), ("b", b)):
            result = store.query("candidate same", adapter, knowledge_base_id=kb, scope=old_scope)
            assert result.status == "success"
            assert [hit.content.identity for hit in result.candidates] == [expected.identity]
            hit = result.candidates[0]
            assert hit.content.source == expected.source
            assert hit.content.text == expected.text
            assert hit.scheme_identity == indexing.IndexSchemeVersion(adapter.metadata).identity
            assert hit.metric == "cosine_similarity"
            assert -1.000001 <= hit.raw_score <= 1.000001
            assert hit.snapshot_id == "s1"
        current = store.pin(("a",), authorization=auth)
        def resolve_adapter(scheme):
            assert scheme.identity == indexing.IndexSchemeVersion(adapter.metadata).identity
            return adapter
        routed = retrieval.PostgresVectorRetrievalStore(store.dsn, schema=store.schema, adapter_for_scheme=resolve_adapter)
        result = routed.search_vector("candidate same", knowledge_base_id="a", scope=current, top_k=10)
        assert result.candidates[0].content.identity == new.identity

    def test_exact_filter_is_applied_before_top_k_and_parent_safe_read(self):
        store = self._make_store()
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        parent = record("kb", document="parent", allowed=False)
        # The permitted candidate sorts below the many excluded exact textual matches.
        denied = [replace(record("kb", document="same" + str(i), allowed=False), text="candidate same") for i in range(50)]
        selected = record("kb", document="rare", allowed=True)
        publish(store, "kb", "s", [parent, *denied, selected], adapter, {"allowed": "boolean"})
        scope = store.pin(("kb",), authorization=retrieval.AuthorizationScope(("kb",)),
                          conditions={"field": "allowed", "op": "eq", "value": True})
        result = store.query("candidate same", adapter, knowledge_base_id="kb", scope=scope, limit=1, candidate_limit=1)
        assert result.status == "success"
        assert [hit.content.identity for hit in result.candidates] == [selected.identity]
        assert store.read(parent.identity, scope=scope) is None
        assert store.read(selected.identity, scope=scope) == selected
        assert result.algorithm == "exact"

    def test_missing_vectors_cannot_publish_and_empty_results_are_not_failure(self):
        store = self._make_store()
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        row = record("kb", allowed=False)
        store.ingest([row])
        with self.assertRaises(retrieval.SnapshotNotReady):
            store.prepare("kb", "incomplete", [row.identity], required_indexes=("vector",),
                          vector_scheme=indexing.IndexSchemeVersion(adapter.metadata))
        with self.assertRaises(retrieval.SnapshotNotReady):
            store.publish("kb", "incomplete")
        publish(store, "kb", "ready", [row], adapter, {"allowed": "boolean"})
        scope = store.pin(("kb",), authorization=retrieval.AuthorizationScope(("kb",)),
                          conditions={"field": "allowed", "op": "eq", "value": True})
        result = store.query("candidate same", adapter, knowledge_base_id="kb", scope=scope)
        assert result.status == "empty"
        assert result.candidates == ()
        with self.assertRaises(ValueError):
            store.pin(("kb",), authorization=retrieval.AuthorizationScope(("kb",)),
                      conditions={"field": "not_declared", "op": "eq", "value": True})

    def test_unindexed_parent_can_be_read_with_same_pinned_filter(self):
        store = self._make_store()
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        parent = record("kb", chunk="parent", allowed=True)
        child = replace(record("kb", chunk="child", allowed=True), parent=parent.identity)
        store.ingest([parent, child])
        assert store.index_documents([child], adapter).items[0].status == "stored"
        store.prepare("kb", "s", [parent.identity, child.identity], required_indexes=("vector",),
                      vector_scheme=indexing.IndexSchemeVersion(adapter.metadata),
                      vector_identities=[child.identity], field_types={"allowed": "boolean"})
        store.publish("kb", "s")
        condition = {"field": "allowed", "op": "eq", "value": True}
        scope = store.pin(("kb",), authorization=retrieval.AuthorizationScope(("kb",)), conditions=condition)
        condition["value"] = False  # caller mutation cannot change a pinned query's meaning
        result = store.query("candidate", adapter, knowledge_base_id="kb", scope=scope)
        assert [hit.content.identity for hit in result.candidates] == [child.identity]
        assert store.read(result.candidates[0].content.parent, scope=scope) == parent

    def test_ann_reports_candidate_budget_and_approximation(self):
        store = self._make_store()
        from app.models.db.pgvector import PhysicalIndexConfig
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        row = record("kb")
        store.ingest([row])
        assert store.index_documents([row], adapter).items[0].status == "stored"
        store.prepare("kb", "s", [row.identity], required_indexes=("vector",),
                      vector_scheme=indexing.IndexSchemeVersion(adapter.metadata),
                      vector_config=PhysicalIndexConfig("hnsw"))
        store.publish("kb", "s")
        scope = store.pin(("kb",), authorization=retrieval.AuthorizationScope(("kb",)))
        result = store.query("candidate", adapter, knowledge_base_id="kb", scope=scope, limit=5, candidate_limit=10)
        assert result.status == "success"
        assert result.algorithm == "hnsw"
        assert result.candidate_limit == 10
        assert result.exhaustive is False
        assert result.limitations
        assert result.shortfall == 4

    def test_backend_filter_failure_returns_no_candidates(self):
        store = self._make_store()
        # Deliberately revoke a required resource after pinning to model runtime failure.
        # Public query must report the failure rather than masquerade as an empty hit set.
        import psycopg
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        row = record("kb")
        publish(store, "kb", "s", [row], adapter)
        scope = store.pin(("kb",), authorization=retrieval.AuthorizationScope(("kb",)))
        with psycopg.connect(store.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE "' + store.schema + '".content RENAME COLUMN metadata TO unavailable_metadata')
        result = store.query("candidate", adapter, knowledge_base_id="kb", scope=scope)
        assert result.status == "failed"
        assert result.candidates == ()
        assert result.error

    def test_document_authorization_cannot_be_widened_by_or_condition(self):
        store = self._make_store()
        adapter = indexing.DeterministicEmbeddingAdapter(3)
        a, b = record("kb", document="a", n=1), record("kb", document="b", n=2)
        publish(store, "kb", "s", [a, b], adapter, {"n": "number"})
        scope = store.pin(("kb",), authorization=retrieval.AuthorizationScope(("kb",), {"kb": ("a",)}),
                          conditions={"or": [{"field": "n", "op": "eq", "value": 1},
                                             {"field": "n", "op": "eq", "value": 2}]})
        result = store.query("candidate", adapter, knowledge_base_id="kb", scope=scope)
        assert [hit.content.identity for hit in result.candidates] == [a.identity]
