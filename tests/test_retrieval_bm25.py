"""Behavior specifications for the synchronous document BM25 interface.

Authored only: these tests have NOT been executed. Real PostgreSQL tests opt in
with RETRIEVAL_BM25_TEST_DSN and require the pinned extensions already installed.
The fixture creates an isolated schema; never point it at a production database.
"""
import importlib
import os
import uuid

import unittest

bm25 = importlib.import_module("app.modules.4_retrievalAndFusion.bm25")


def contracts():
    return importlib.import_module("app.modules.4_retrievalAndFusion.contracts")


def record(kb, document, text, **metadata):
    c = contracts()
    return c.ContentRecord(c.EvidenceIdentity(kb, document, "v1", "chunk", "c1"),
                           text, {"uri": "manual://" + document}, metadata)


def publish(store, kb, snapshot, records, **options):
    store.ingest(records)
    store.prepare(kb, snapshot, [r.identity for r in records],
                  required_indexes=("content", "bm25"), **options)
    store.publish(kb, snapshot)
    return store.pin((kb,), authorization=contracts().AuthorizationScope((kb,)))


class BM25Tests(unittest.TestCase):
    def _make_store(self):
        dsn = os.environ.get("RETRIEVAL_BM25_TEST_DSN")
        if not dsn:
            self.skipTest("requires explicit real PostgreSQL/pg_search test database")
        import psycopg
        from psycopg import sql
        module = importlib.import_module("app.modules.4_retrievalAndFusion")
        schema = "test_bm25_" + uuid.uuid4().hex
        value = module.PostgresBM25RetrievalStore(dsn, schema=schema)
        def cleanup():
            with psycopg.connect(dsn) as connection:
                connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        self.addCleanup(cleanup)
        value.migrate()
        return value

    def test_analyzer_preserves_case_and_freezes_its_configuration(self):
        config = bm25.BM25Analyzer()
        assert config.jieba_lowercase is False
        assert config.model_pattern == r"[A-Za-z0-9]+([._+-][A-Za-z0-9]+)*"
        assert config.fingerprint == bm25.BM25Analyzer().fingerprint
        assert config.fingerprint != bm25.BM25Analyzer(k1=1.5).fingerprint
        with self.assertRaises(ValueError):
            bm25.BM25Analyzer(k1=float("nan"))

    def test_same_store_builds_vector_and_bm25_before_one_publication(self):
        store = self._make_store()
        indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")
        encoder = indexing.DeterministicEmbeddingAdapter(3)
        source = record("kb", "manual", "AX-100 中文说明")
        result = store.index_documents([source], encoder)
        assert result.items[0].status == "stored"
        store.prepare("kb", "s1", [source.identity], required_indexes=("content", "vector", "bm25"),
                      vector_scheme=indexing.IndexSchemeVersion(encoder.metadata))
        store.publish("kb", "s1")
        scope = store.pin(("kb",), authorization=contracts().AuthorizationScope(("kb",)))
        vector = store.query("AX-100", encoder, knowledge_base_id="kb", scope=scope, limit=1)
        lexical = store.search_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=1)
        assert vector.status == lexical.status == "success"
        assert vector.candidates[0].content == lexical.candidates[0].content == source
        assert vector.candidates[0].snapshot_id == lexical.candidates[0].snapshot_id == "s1"

    def test_explicit_index_members_allow_unindexed_readable_parent(self):
        store = self._make_store()
        c = contracts()
        parent = record("kb", "manual", "AX-100 完整父块")
        child = c.ContentRecord(c.EvidenceIdentity("kb", "manual", "v1", "child", "c1"),
                                "AX-100 子块", {"uri": "manual://manual"}, {}, parent.identity)
        scope = publish(store, "kb", "s1", [parent, child], bm25_identities=[child.identity])
        result = store.search_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=10)
        assert result.status == "success"
        assert [hit.content.identity for hit in result.candidates] == [child.identity]
        assert store.read(parent.identity, scope=scope) == parent
        with self.assertRaises(c.ContentConflict):
            store.prepare("kb", "s1", [parent.identity, child.identity], required_indexes=("bm25",),
                          bm25_identities=[parent.identity, child.identity])

    def test_filters_and_document_authorization_apply_before_top_k(self):
        store = self._make_store()
        denied = [record("kb", f"noise-{i}", "AX-100 AX-100 AX-100", price=99, tags=["private"])
                  for i in range(80)]
        eligible = record("kb", "allowed", "AX-100 说明", price=2, tags=["public"])
        publish(store, "kb", "s1", [*denied, eligible],
                field_types={"price": "number", "tags": "set[string]"})
        scope = store.pin(("kb",), authorization=contracts().AuthorizationScope(("kb",), {"kb": ("allowed",)}),
                          conditions={"and": [{"field": "price", "op": "range", "lower": 1, "upper": 3},
                                               {"field": "tags", "op": "contains", "value": "public"}]})
        result = store.search_bm25("AX-100", knowledge_base_id="kb", scope=scope,
                                  top_k=1, exact_terms=("AX-100",))
        assert result.status == "success"
        assert [hit.content for hit in result.candidates] == [eligible]

    def test_typed_filters_keep_null_missing_boolean_or_and_fixed_time_semantics(self):
        for condition, expected in [
            ({"field": "optional", "op": "missing"}, {"missing"}),
            ({"field": "optional", "op": "is_null"}, {"null"}),
            ({"field": "optional", "op": "exists"}, {"null", "value"}),
            ({"or": [{"field": "optional", "op": "is_null"},
                      {"field": "optional", "op": "in", "value": ["yes"]}]}, {"null", "value"}),
            ({"field": "active", "op": "eq", "value": True}, {"value"}),
            ({"field": "effective", "op": "lte", "value": {"now": True}}, {"value"}),
        ]:
            with self.subTest(condition=condition, expected=expected):
                try:
                    store = self._make_store()
                    records = [record("kb", "missing", "AX-100"), record("kb", "null", "AX-100", optional=None),
                               record("kb", "value", "AX-100", optional="yes", active=True,
                                      effective="2000-01-01T00:00:00+00:00")]
                    fields = {"optional": "string", "active": "boolean", "effective": "datetime"}
                    publish(store, "kb", "s1", records, field_types=fields)
                    scope = store.pin(("kb",), authorization=contracts().AuthorizationScope(("kb",)), conditions=condition)
                    result = store.search_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=10)
                    assert result.status == "success"
                    assert {hit.content.identity.document_id for hit in result.candidates} == expected
                    assert all(store.read(hit.content.identity, scope=scope) == hit.content for hit in result.candidates)
                finally:
                    self.doCleanups()

    def test_other_knowledge_base_cannot_change_existing_corpus_scores(self):
        store = self._make_store()
        first = record("kb", "one", "AX-100 中文检索")
        scope = publish(store, "kb", "s1", [first, record("kb", "two", "其他说明")])
        before = store.search_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=10)
        publish(store, "other", "s1", [record("other", str(i), "AX-100") for i in range(40)])
        after = store.search_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=10)
        assert before.status == after.status == "success"
        assert before.candidates == after.candidates

    def test_analyzer_change_needs_new_snapshot_and_old_scope_stays_fixed(self):
        store = self._make_store()
        original = record("kb", "one", "AX-100 中文检索")
        old = publish(store, "kb", "s1", [original])
        with self.assertRaises(contracts().ContentConflict):
            store.prepare("kb", "s1", [original.identity], required_indexes=("bm25",),
                          bm25_analyzer=bm25.BM25Analyzer(k1=1.5))
        store.prepare("kb", "s2", [original.identity], required_indexes=("bm25",),
                      bm25_analyzer=bm25.BM25Analyzer(k1=1.5))
        store.publish("kb", "s2")
        assert old.snapshots["kb"] == "s1"
        old_hit = store.search_bm25("AX-100", knowledge_base_id="kb", scope=old, top_k=1)
        assert old_hit.status == "success"
        assert old_hit.candidates[0].snapshot_id == "s1"
        new = store.pin(("kb",), authorization=contracts().AuthorizationScope(("kb",)))
        assert new.snapshots["kb"] == "s2"

    def test_missing_physical_index_blocks_publication_and_fails_path(self):
        store = self._make_store()
        # Fault injection simulates external DDL loss; assertions stay at public seams.
        import psycopg
        from psycopg import sql
        original = record("kb", "one", "AX-100")
        old = publish(store, "kb", "s1", [original])
        store.prepare("kb", "s2", [original.identity], required_indexes=("bm25",))
        with psycopg.connect(store.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT idx.relname FROM pg_class idx JOIN pg_namespace n ON n.oid=idx.relnamespace "
                               "JOIN pg_am am ON am.oid=idx.relam WHERE n.nspname=%s AND am.amname='paradedb'",
                               (store.schema,))
                for (name,) in cursor.fetchall():
                    cursor.execute(sql.SQL("DROP INDEX {}.{}").format(sql.Identifier(store.schema), sql.Identifier(name)))
        with self.assertRaises(contracts().SnapshotNotReady):
            store.publish("kb", "s2")
        pinned = store.pin(("kb",), authorization=contracts().AuthorizationScope(("kb",)))
        assert pinned.snapshots["kb"] == "s1"
        result = store.search_bm25("AX-100", knowledge_base_id="kb", scope=old, top_k=1)
        assert result.status == "failed"
        assert result.candidates == ()
        with self.assertRaises(contracts().SnapshotNotReady):
            store.prepare("kb", "s1", [original.identity], required_indexes=("bm25",))

    def test_prepare_is_idempotent_and_failed_preparation_preserves_publication(self):
        store = self._make_store()
        original = record("kb", "one", "AX-100")
        publish(store, "kb", "s1", [original])
        store.prepare("kb", "s1", [original.identity], required_indexes=("bm25",))
        missing = record("kb", "missing", "unavailable")
        with self.assertRaises(contracts().SnapshotNotReady):
            store.prepare("kb", "s2", [missing.identity], required_indexes=("bm25",))
        assert store.pin(("kb",), authorization=contracts().AuthorizationScope(("kb",))).snapshots["kb"] == "s1"

    def test_unavailable_backend_reports_failed_path_without_candidates(self):
        from datetime import datetime, timezone
        module = importlib.import_module("app.modules.4_retrievalAndFusion")
        c = contracts()

        def unavailable(_dsn):
            raise OSError("database unavailable")

        adapter = module.PostgresBM25RetrievalStore("unused", connect=unavailable)
        now = datetime.now(timezone.utc)
        filters = importlib.import_module("app.modules.4_retrievalAndFusion.typed_filters")
        scope = c.ReadScope({"kb": "s1"}, c.AuthorizationScope(("kb",)), None, now,
                            {"kb": filters.compile_filter(None, {}, now=now)})
        result = adapter.search_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=2)
        assert result.status == "failed"
        assert result.candidates == ()
        assert result.error

    def test_unsupported_filter_is_rejected_before_search(self):
        store = self._make_store()
        publish(store, "kb", "s1", [record("kb", "one", "AX-100")])
        with self.assertRaises(contracts().RetrievalContractError):
            store.pin(("kb",), authorization=contracts().AuthorizationScope(("kb",)),
                      conditions={"field": "unknown", "op": "eq", "value": "x"})

    def test_exact_model_terms_do_not_fold_case_or_match_longer_model(self):
        store = self._make_store()
        originals = [record("kb", "exact", "中文设备 USB-C AX-100 v2.1"),
                     record("kb", "longer", "中文设备 USB-C AX-100X v2.1"),
                     record("kb", "case", "中文设备 usb-c ax-100 v2.1")]
        scope = publish(store, "kb", "s1", originals)
        result = store.search_bm25("USB-C AX-100 v2.1", knowledge_base_id="kb", scope=scope,
                                  top_k=10, exact_terms=("USB-C", "AX-100", "v2.1"))
        assert result.status == "success"
        assert [hit.content.identity.document_id for hit in result.candidates] == ["exact"]

    def test_ingest_publish_search_returns_authoritative_identity_source_and_score(self):
        store = self._make_store()
        source = record("kb", "manual", "中文检索说明 USB-C AX-100 v2.1")
        scope = publish(store, "kb", "s1", [source])
        result = store.search_bm25("中文检索", knowledge_base_id="kb", scope=scope, top_k=3)
        assert result.status == "success"
        assert len(result.candidates) == 1
        hit = result.candidates[0]
        assert hit.content == source
        assert hit.snapshot_id == "s1"
        assert hit.raw_score > 0
        assert store.read(hit.content.identity, scope=scope) == source
        empty = store.search_bm25("不可能存在的词ZXY987", knowledge_base_id="kb", scope=scope, top_k=3,
                                  exact_terms=("ZXY987",))
        assert empty.status == "empty"
        assert empty.candidates == ()
