"""Real PostgreSQL/pgvector/pg_search + module3 public pipeline; NOT EXECUTED.

Explicit RETRIEVAL_PIPELINE_TEST_DSN must name a disposable database with the
pinned extensions preinstalled. Both retrieval and module3 receipts use random
schemas, removed in fixture teardown. No server/model is provisioned here.
"""
from dataclasses import replace
import os
import uuid

import unittest

from retrieval_pipeline_cases import FEATURE_CASES, PINNED_NOW, document_corpus
from retrieval_pipeline_support import r, embedding, body, compatible, config_for, faq_record, query


class ObservedProvider(embedding.DeterministicEmbeddingAdapter):
    """Deterministic external provider, actual module3 API and PG receipts."""
    def __init__(self):
        super().__init__(3)
        self.inputs = []
        self.fail = False

    def embed_role(self, texts, role, *, remaining=None):
        self.inputs.append((tuple(texts), role))
        if self.fail:
            raise TimeoutError("private provider URL and payload")
        return super().embed_role(texts, role, remaining=remaining)


def publish(store, provider, *, kb="kb-a", snapshot="s1", version="v1", do_publish=True):
    documents = document_corpus(r, knowledge_base_id=kb, version=version)
    faq = faq_record(kb, version)
    store.ingest(documents.values())
    indexed = [documents[name] for name in ("child-a", "child-b", "duplicate", "diverse")]
    result = store.index_documents(indexed, provider)
    assert all(item.status == "stored" for item in result.items)
    faq_result = store.index_faq([faq], provider)
    assert all(item.status == "stored" for item in faq_result.items)
    scheme = embedding.IndexSchemeVersion(provider.metadata)
    store.prepare(kb, snapshot, [row.identity for row in documents.values()], faq_identities=[faq.identity],
        required_indexes=("content", "vector", "bm25", "faq", "faq_vector", "faq_bm25"),
        vector_scheme=scheme, faq_vector_scheme=scheme,
        vector_identities=[row.identity for row in indexed], bm25_identities=[row.identity for row in indexed],
        field_types={"product": "string", "edition": "string", "tags": "set[string]", "effective": "datetime"})
    if do_publish:
        store.publish(kb, snapshot)
    return documents, faq


def service_for(store, provider):
    return r.RetrievalService(store, mmr_encoder=body.Module3BodyEncoder(provider, store.request_repository))


class PipelinePostgresTests(unittest.TestCase):
    def _make_backend(self):
        dsn = os.environ.get("RETRIEVAL_PIPELINE_TEST_DSN")
        if not dsn:
            self.skipTest("requires explicit disposable PostgreSQL 17.11/vector 0.8.6/pg_search 0.26.4")
        import psycopg
        from psycopg import sql
        suffix = uuid.uuid4().hex
        schema, receipts = "pipeline_" + suffix, "receipts_" + suffix
        def connect(value, **options):
            return psycopg.connect(value, options=f"-c search_path={receipts},public", **options)
        def cleanup():
            with psycopg.connect(dsn) as connection:
                for name in (schema, receipts):
                    connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        self.addCleanup(cleanup)
        with psycopg.connect(dsn) as connection:
            self.assertEqual(connection.execute("SHOW server_version_num").fetchone()[0], "170011")
            versions = dict(connection.execute("SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pg_search')").fetchall())
            self.assertEqual(versions, {"vector": "0.8.6", "pg_search": "0.26.4"})
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(receipts)))
        provider = ObservedProvider()
        store = r.PostgresFAQBM25RetrievalStore(dsn, schema=schema, connect=connect,
            adapter_for_scheme=lambda scheme: provider, clock=lambda: PINNED_NOW)
        store.migrate()
        return store, provider

    def test_real_public_lifecycle_all_24_combinations(self):
        for case in FEATURE_CASES:
            with self.subTest(case=case.case_id):
                try:
                    backend = self._make_backend()
                    store, provider = backend
                    documents, faq = publish(store, provider)
                    # Clear observation, not persisted receipts: MMR must obtain bodies through
                    # the real module3 path; vector retrieval may additionally encode the query.
                    provider.inputs.clear()
                    result = query(service_for(store, provider), config=config_for(case), conditions=r.Eq("product", "AX-100"))
                    assert result.status == "complete"
                    assert len(result.routes) == 4
                    assert all(route.status == "success" for route in result.routes)
                    assert {route.method for route in result.routes} == {"vector", "bm25", "faq_vector", "faq_bm25"}
                    assert result.scope.snapshots == {"kb-a": "s1"}
                    assert result.scope.now == PINNED_NOW
                    pool = result.working_pool
                    assert len(pool) == (3 if case.parent_expansion and case.body_dedup else 4 if case.parent_expansion else 5)
                    assert len(result.candidates) == 2
                    assert all(item in pool for item in result.candidates)
                    represented = {trace.identity for item in pool for trace in item.traces}
                    assert represented == {documents[name].identity for name in ("child-a", "child-b", "duplicate", "diverse")} | {faq.identity}
                    assert documents["grandparent"].identity not in {item.content.identity for item in pool}
                    for item in pool:
                        assert store.read(item.content.identity, scope=result.scope) == item.content
                        assert all(trace.snapshot_id == "s1" for trace in item.traces)
                        assert item.content.source in item.sources
                    faq_hit = next(item for item in pool if item.content.identity == faq.identity)
                    assert faq_hit.content.text == faq.answer
                    assert len(faq_hit.traces) == 2
                    assert all({question.question for question in trace.matched_questions} == set(faq.questions)
                               for trace in faq_hit.traces)
                    if case.parent_expansion:
                        parent_group = next(item for item in pool if documents["parent"].identity in item.represented_identities)
                        assert {child.identity for child in parent_group.matched_children} == {
                            documents["child-a"].identity, documents["child-b"].identity}
                        assert documents["parent"].source in parent_group.sources
                        if case.body_dedup:
                            assert documents["duplicate"].identity in parent_group.represented_identities
                    assert [(step.name, step.status) for step in result.steps] == [
                        ("parent", "complete" if case.parent_expansion else "skipped"),
                        ("dedup", "complete" if case.body_dedup else "skipped"),
                        ("mmr", "complete" if case.mmr else "skipped")]
                    if case.mmr:
                        encoded_bodies = {text for texts, role in provider.inputs if role == "document" for text in texts}
                        assert encoded_bodies == {item.content.text for item in pool}
                        assert faq.answer in encoded_bodies
                        assert not encoded_bodies.intersection(faq.questions)
                        # Recreate both encoder and service. Successful body vectors must survive
                        # in real PostgreSQL receipts; query-role calls may happen again.
                        provider.inputs.clear()
                        repeated = query(service_for(store, provider), config=config_for(case), conditions=r.Eq("product", "AX-100"))
                        assert repeated.candidates == result.candidates
                        assert not any(role == "document" for _, role in provider.inputs)
                    else:
                        assert result.candidates == pool[:2]
                finally:
                    self.doCleanups()

    def test_real_auth_filter_before_top_k_and_empty_not_failure(self):
        backend = self._make_backend()
        store, provider = backend
        documents, faq = publish(store, provider)
        service = service_for(store, provider)
        denied = service.query("AX-100", knowledge_base_ids=("kb-a",),
            authorization=r.AuthorizationScope(("kb-a",), {"kb-a": ()}, faq_item_ids={"kb-a": ()}),
            config=r.RetrievalConfig(route_top_k=1, parent_expansion=True, body_dedup=True, mmr=True),
            body_dedup_prover=compatible)
        assert denied.status == "complete"
        assert denied.candidates == ()
        assert all(route.status == "empty" for route in denied.routes)
        filtered = query(service, conditions={"and": [{"field": "product", "op": "eq", "value": "AX-100"},
            {"field": "effective", "op": "lte", "value": {"now": True}}]},
            config=r.RetrievalConfig(parent_expansion=True, route_top_k=1))
        assert filtered.status == "complete"
        assert all(item.content.identity != faq.identity for item in filtered.candidates)
        assert all(item.content.metadata["product"] == "AX-100" for item in filtered.candidates)
        with self.assertRaises((r.RetrievalContractError, r.FilterValidationError)):
            query(service, conditions={"field": "unknown", "op": "eq", "value": "x"})

    def test_real_retained_history_failed_prepare_and_multikb_identity(self):
        backend = self._make_backend()
        store, provider = backend
        old, old_faq = publish(store, provider)
        new, new_faq = publish(store, provider, snapshot="s2", version="v2")
        service = service_for(store, provider)
        historical = query(service, snapshot_ids={"kb-a": "s1"}, config=r.RetrievalConfig(parent_expansion=True))
        current = query(service, config=r.RetrievalConfig(parent_expansion=True))
        assert {trace.snapshot_id for item in historical.working_pool for trace in item.traces} == {"s1"}
        assert {trace.snapshot_id for item in current.working_pool for trace in item.traces} == {"s2"}
        assert old_faq.identity in {item.content.identity for item in historical.working_pool}
        assert new_faq.identity in {item.content.identity for item in current.working_pool}
        missing = r.EvidenceIdentity("kb-a", "missing", "v3", "chunk", "c1")
        with self.assertRaises(r.SnapshotNotReady):
            store.prepare("kb-a", "broken", [missing], required_indexes=("content",))
        assert query(service).scope.snapshots == {"kb-a": "s2"}
        publish(store, provider, kb="kb-b")
        combined = service.query("AX-100", knowledge_base_ids=("kb-a", "kb-b"),
            authorization=r.AuthorizationScope(("kb-a", "kb-b")), config=r.RetrievalConfig(parent_expansion=True))
        assert len(combined.routes) == 8
        assert combined.status == "complete"
        assert {item.content.identity.knowledge_base_id for item in combined.working_pool} == {"kb-a", "kb-b"}
        assert all(len({trace.knowledge_base_id for trace in item.traces}) == 1 for item in combined.working_pool)

    def test_real_route_failure_combines_with_mmr_failure_and_strict_mode(self):
        backend = self._make_backend()
        store, provider = backend
        publish(store, provider)
        def unavailable(scheme):
            raise RuntimeError("private vector endpoint")
        store.adapter_for_scheme = unavailable
        provider.fail = True
        provider.inputs.clear()
        for strict in (False, True):
            result = query(service_for(store, provider), config=r.RetrievalConfig(
                parent_expansion=True, body_dedup=True, mmr=True, postprocess_strict=strict, final_top_k=2))
            assert result.status == "partial"
            assert {route.method for route in result.routes if route.status == "failed"} == {"vector", "faq_vector"}
            assert {route.method for route in result.routes if route.status == "success"} == {"bm25", "faq_bm25"}
            assert result.steps[-1].status == ("failed" if strict else "partial")
            assert result.candidates == (() if strict else result.working_pool[:2])
            assert "private" not in repr(result.steps)
        # Unknown module3 outcome is durable, so the second query must not re-submit.
        assert sum(role == "document" for _, role in provider.inputs) == 1

    def test_real_parent_business_filter_retains_child_or_reports_strict_failure(self):
        for strict in [False, True]:
            with self.subTest(strict=strict):
                try:
                    backend = self._make_backend()
                    store, provider = backend
                    parent = r.ContentRecord(r.EvidenceIdentity("kb-a", "manual", "v1", "parent", "c1"),
                        "restricted parent AX-100", {"uri": "manual://parent"}, {"visibility": "private"})
                    child = r.ContentRecord(r.EvidenceIdentity("kb-a", "manual", "v1", "child", "c1"),
                        "allowed child AX-100", {"uri": "manual://child"}, {"visibility": "public"}, parent.identity)
                    faq = faq_record()
                    faq = replace(faq, conditions={"visibility": "public"})
                    store.ingest([parent, child])
                    store.index_documents([child], provider)
                    store.index_faq([faq], provider)
                    scheme = embedding.IndexSchemeVersion(provider.metadata)
                    store.prepare("kb-a", "s1", [parent.identity, child.identity], faq_identities=[faq.identity],
                        required_indexes=("vector", "bm25", "faq_vector", "faq_bm25"),
                        vector_scheme=scheme, faq_vector_scheme=scheme, vector_identities=[child.identity],
                        bm25_identities=[child.identity], field_types={"visibility": "string"})
                    store.publish("kb-a", "s1")
                    result = query(service_for(store, provider), conditions=r.Eq("visibility", "public"),
                        config=r.RetrievalConfig(parent_expansion=True, body_dedup=True, mmr=True, postprocess_strict=strict))
                    assert result.status == "complete"
                    assert all(route.status == "success" for route in result.routes)
                    assert result.steps[0].status == ("failed" if strict else "partial")
                    assert "restricted parent" not in repr(result)
                    assert parent.identity not in {item.content.identity for item in result.working_pool}
                    assert child.identity in {item.content.identity for item in result.working_pool}
                    if strict:
                        assert result.candidates == ()
                    else:
                        assert result.candidates
                finally:
                    self.doCleanups()

    def test_real_provider_transport_timeout_is_not_generic_failed_route(self):
        backend = self._make_backend()
        store, provider = backend
        publish(store, provider)
        provider.fail = True
        result = query(service_for(store, provider))
        assert result.status == "partial"
        assert {route.method for route in result.routes if route.status == "timeout"} == {"vector", "faq_vector"}
        assert {route.method for route in result.routes if route.status == "success"} == {"bm25", "faq_bm25"}
        assert all(route.candidates == () for route in result.routes if route.status == "timeout")

    def test_real_publish_during_query_keeps_documents_faq_and_parents_on_pinned_snapshot(self):
        backend = self._make_backend()
        store, provider = backend
        old, old_faq = publish(store, provider)
        new, new_faq = publish(store, provider, snapshot="s2", version="v2", do_publish=False)
        class PublishingAuthority:
            # External store wrapper switches publication only AFTER the real pin.
            # Real backend search/read methods receive that exact public ReadScope.
            def __getattr__(self, name):
                return getattr(store, name)
            def pin(self, *args, remaining, **options):
                remaining.check()
                # Store.pin reads the same budget from the service's deadline_scope;
                # its public signature does not accept a remaining keyword.
                scope = store.pin(*args, **options)
                store.publish("kb-a", "s2")
                remaining.check()
                return scope
        config = r.RetrievalConfig(parent_expansion=True, body_dedup=True, mmr=True, final_top_k=20)
        pinned = query(service_for(PublishingAuthority(), provider), config=config)
        current = query(service_for(store, provider), config=config)
        assert pinned.scope.snapshots == {"kb-a": "s1"}
        assert current.scope.snapshots == {"kb-a": "s2"}
        assert {trace.snapshot_id for item in pinned.working_pool for trace in item.traces} == {"s1"}
        assert old_faq.identity in {item.content.identity for item in pinned.working_pool}
        assert new_faq.identity in {item.content.identity for item in current.working_pool}
        assert old["parent"].identity in {identity for item in pinned.working_pool for identity in item.represented_identities}
        assert new["parent"].identity in {identity for item in current.working_pool for identity in item.represented_identities}

    def test_real_physical_index_loss_blocks_publish_and_reports_partial_query(self):
        backend = self._make_backend()
        store, provider = backend
        publish(store, provider)
        publish(store, provider, snapshot="s2", do_publish=False)
        import psycopg
        from psycopg import sql
        # External corruption is confined to this fixture's physical FAQ indexes.
        with psycopg.connect(store.dsn) as connection:
            indexes = connection.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_am a ON a.oid=c.relam WHERE n.nspname=%s AND a.amname='paradedb' "
                "AND c.relname LIKE 'bm25_faq_idx_%%'", (store.schema,)).fetchall()
            assert indexes
            for (name,) in indexes:
                connection.execute(sql.SQL("DROP INDEX {}.{}").format(sql.Identifier(store.schema), sql.Identifier(name)))
        with self.assertRaises(r.SnapshotNotReady):
            store.publish("kb-a", "s2")
        result = query(service_for(store, provider))
        assert result.scope.snapshots == {"kb-a": "s1"}
        assert result.status == "partial"
        assert next(route for route in result.routes if route.method == "faq_bm25").status == "failed"
        assert result.candidates
