"""FAQ BM25 public behavior specifications. AUTHORED ONLY, NOT RUN.

Requires an explicit disposable RETRIEVAL_BM25_TEST_DSN with the pinned stack.
No fixture provisions extensions or starts services.
"""
import importlib
import os
import uuid

import pytest


def api():
    return importlib.import_module("app.modules.4_retrievalAndFusion")


@pytest.fixture
def store():
    dsn = os.environ.get("RETRIEVAL_BM25_TEST_DSN")
    if not dsn:
        pytest.skip("requires explicit real PostgreSQL/pg_search database")
    psycopg = pytest.importorskip("psycopg")
    value = api().PostgresFAQBM25RetrievalStore(dsn, schema="test_faq_bm25_" + uuid.uuid4().hex)
    try:
        value.migrate()
        yield value
    finally:
        from psycopg import sql
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(value.schema)))


def faq(item, question="AX-100 如何设置", similar=(), *, kb="kb", version="v1", **conditions):
    m = api()
    return m.FAQRecord(m.FAQIdentity(kb, item, version), question, similar,
                       "维护好的答案：" + item, conditions, {"uri": "faq://" + item})


def publish(store, records, *, kb="kb", snapshot="s1", documents=(), **options):
    store.ingest(documents)
    store.ingest_faq(records)
    store.prepare(kb, snapshot, [d.identity for d in documents], faq_identities=[r.identity for r in records],
                  required_indexes=("content", "bm25", "faq", "faq_bm25"), **options)
    store.publish(kb, snapshot)
    return store.pin((kb,), authorization=api().AuthorizationScope((kb,)))


def test_question_matches_group_into_items_before_top_k_and_return_answer(store):
    first = faq("first", similar=("AX-100 设置方式", "AX-100 设置方法", "AX-100 如何设置"))
    second = faq("second", "AX-100 安装")
    scope = publish(store, [first, second])
    result = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=2,
                                   exact_terms=("AX-100",))
    assert result.status == "success"
    assert {c.content.identity for c in result.candidates} == {first.identity, second.identity}
    hit = next(c for c in result.candidates if c.content.identity == first.identity)
    assert hit.content == first
    assert hit.content.text == first.answer
    assert {q.question for q in hit.matched_questions} == set(first.questions)
    assert hit.raw_score == max(q.raw_score for q in hit.matched_questions)
    assert hit.snapshot_id == "s1"
    assert store.read(first.identity, scope=scope) == first
    empty = store.search_faq_bm25("missing", knowledge_base_id="kb", scope=scope, exact_terms=("ZXY987",))
    assert empty.status == "empty"
    assert empty.candidates == ()


@pytest.mark.parametrize("condition,expected", [
    ({"field": "optional", "op": "missing"}, {"missing"}),
    ({"field": "optional", "op": "is_null"}, {"null"}),
    ({"field": "optional", "op": "exists"}, {"null", "value"}),
    ({"or": [{"field": "optional", "op": "is_null"},
              {"field": "optional", "op": "in", "value": ["yes"]}]}, {"null", "value"}),
    ({"field": "effective", "op": "lte", "value": {"now": True}}, {"value"}),
])
def test_faq_conditions_preserve_null_missing_or_and_fixed_time(store, condition, expected):
    records = [faq("missing"), faq("null", optional=None),
               faq("value", optional="yes", effective="2000-01-01T00:00:00+00:00")]
    publish(store, records, field_types={"optional": "string", "effective": "datetime"})
    scope = store.pin(("kb",), authorization=api().AuthorizationScope(("kb",)), conditions=condition)
    result = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=scope)
    assert result.status == "success"
    assert {h.content.identity.item_id for h in result.candidates} == expected
    assert all(store.read(h.content.identity, scope=scope) == h.content for h in result.candidates)


def test_authorization_and_typed_filters_precede_item_limit(store):
    denied = [faq(f"denied-{n}", "AX-100 AX-100", price=99, tags=["private"]) for n in range(80)]
    allowed = faq("allowed", price=2, tags=["public"])
    publish(store, [*denied, allowed], field_types={"price": "number", "tags": "set[string]"})
    scope = store.pin(("kb",), authorization=api().AuthorizationScope(("kb",), faq_item_ids={"kb": ("allowed",)}),
                      conditions={"and": [{"field": "price", "op": "range", "lower": 1, "upper": 3},
                                           {"field": "tags", "op": "contains", "value": "public"}]})
    result = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=1)
    assert result.status == "success"
    assert [h.content for h in result.candidates] == [allowed]
    document_only = store.pin(("kb",), authorization=api().AuthorizationScope(("kb",), {"kb": ("manual",)}))
    assert store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=document_only).status == "empty"
    with pytest.raises(api().RetrievalContractError):
        store.pin(("kb",), authorization=api().AuthorizationScope(("kb",)),
                  conditions={"field": "unknown", "op": "eq", "value": "x"})


def test_faq_scores_are_independent_of_documents_other_kbs_and_new_snapshots(store):
    records = [faq("one"), faq("two", "其他说明")]
    old = publish(store, records)
    before = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=old)
    documents = [api().ContentRecord(api().EvidenceIdentity("kb", f"d-{n}", "v1", "c", "v1"),
                                    "AX-100", {"uri": "manual://noise"}, {}) for n in range(40)]
    current = publish(store, records, snapshot="s2", documents=documents)
    publish(store, [faq(str(n), kb="other") for n in range(40)], kb="other")
    after = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=current)
    pinned = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=old)
    assert before.status == after.status == pinned.status == "success"
    assert [(c.content, c.raw_score) for c in before.candidates] == [(c.content, c.raw_score) for c in after.candidates]
    assert before.candidates == pinned.candidates


def test_analyzer_and_versions_are_frozen_and_failed_prepare_keeps_old_publication(store):
    analyzer = importlib.import_module("app.modules.4_retrievalAndFusion.faq_bm25").FAQBM25Analyzer
    first = faq("one", release="old")
    old = publish(store, [first], field_types={"release": "string"})
    with pytest.raises(api().ContentConflict):
        store.prepare("kb", "s1", (), faq_identities=[first.identity],
                      required_indexes=("content", "bm25", "faq", "faq_bm25"),
                      field_types={"release": "string"}, faq_bm25_analyzer=analyzer(k1=1.5))
    missing = faq("missing")
    with pytest.raises(api().SnapshotNotReady):
        store.prepare("kb", "bad", (), faq_identities=[missing.identity])
    assert store.pin(("kb",), authorization=api().AuthorizationScope(("kb",))).snapshots["kb"] == "s1"
    second = faq("one", version="v2", release="new")
    new = publish(store, [second], snapshot="s2", field_types={"release": "string"}, faq_bm25_analyzer=analyzer(k1=1.5))
    old_result = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=old)
    new_result = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=new)
    assert old_result.candidates[0].content == first
    assert new_result.candidates[0].content == second
    assert old_result.candidates[0].analyzer_fingerprint != new_result.candidates[0].analyzer_fingerprint
    assert store.read(first.identity, scope=new) is None


def test_case_preserving_exact_models_and_answer_is_not_question_corpus(store):
    exact = faq("exact", "中文设备 USB-C AX-100 v2.1")
    longer = faq("longer", "中文设备 USB-C AX-100X v2.1")
    lower = faq("lower", "中文设备 usb-c ax-100 v2.1")
    answer_only = api().FAQRecord(api().FAQIdentity("kb", "answer", "v1"), "怎样操作", (),
                                 "USB-C AX-100 v2.1", {}, {"uri": "faq://answer"})
    scope = publish(store, [exact, longer, lower, answer_only])
    result = store.search_faq_bm25("USB-C AX-100 v2.1", knowledge_base_id="kb", scope=scope,
                                  exact_terms=("USB-C", "AX-100", "v2.1"))
    assert result.status == "success"
    assert [h.content for h in result.candidates] == [exact]


def test_public_ingest_publish_query_fuses_four_routes_once_per_item(store):
    indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")
    encoder = indexing.DeterministicEmbeddingAdapter(3)
    store.adapter_for_scheme = lambda scheme: encoder
    entry = faq("one", "USB-C AX-100 v2.1 设置", ("USB-C AX-100 v2.1 安装", "USB-C AX-100 v2.1 使用"), product="AX-100")
    doc = api().ContentRecord(api().EvidenceIdentity("kb", "manual", "v1", "chunk", "c1"),
                              "USB-C AX-100 v2.1 中文说明", {"uri": "manual://one"}, {"product": "AX-100"})
    store.index_documents([doc], encoder)
    store.index_faq([entry], encoder)
    scheme = indexing.IndexSchemeVersion(encoder.metadata)
    store.prepare("kb", "mixed", [doc.identity], faq_identities=[entry.identity],
                  required_indexes=("vector", "bm25", "faq_vector", "faq_bm25"),
                  vector_scheme=scheme, faq_vector_scheme=scheme, field_types={"product": "string"})
    store.publish("kb", "mixed")
    service = api().RetrievalService(store)
    result = service.query("AX-100", knowledge_base_ids=("kb",), authorization=api().AuthorizationScope(("kb",)),
                           conditions=api().Eq("product", "AX-100"), exact_terms=("USB-C", "AX-100", "v2.1"))
    assert result.status == "complete"
    assert {route.method for route in result.routes} == {"vector", "bm25", "faq_vector", "faq_bm25"}
    assert all(route.status == "success" for route in result.routes)
    assert {hit.content.identity for hit in result.candidates} == {entry.identity, doc.identity}
    hit = next(hit for hit in result.candidates if hit.content.identity == entry.identity)
    assert hit.content == entry
    assert {trace.method for trace in hit.traces} == {"faq_vector", "faq_bm25"}
    assert len(hit.traces) == 2
    assert hit.score == pytest.approx(2 / 61)
    for trace in hit.traces:
        assert trace.rank == 1
        assert trace.snapshot_id == "mixed"
        assert {q.question for q in trace.matched_questions} == set(entry.questions)
        assert trace.raw_score == max(q.raw_score for q in trace.matched_questions)
    empty = service.query("AX-100", knowledge_base_ids=("kb",), authorization=api().AuthorizationScope(("kb",)),
                          conditions=api().Eq("product", "OTHER"))
    assert empty.status == "complete"
    assert empty.candidates == ()
    assert all(route.status == "empty" for route in empty.routes)
    # Query text matches, but both lexical adapters must honor absent exact tokens.
    exact_empty = service.query("AX-100", knowledge_base_ids=("kb",), authorization=api().AuthorizationScope(("kb",)),
                                exact_terms=("ABSENT-MODEL",))
    assert {route.method for route in exact_empty.routes if route.status == "empty"} == {"bm25", "faq_bm25"}
    faq_only = service.query("AX-100", knowledge_base_ids=("kb",),
                             authorization=api().AuthorizationScope(("kb",), faq_item_ids={"kb": ("one",)}))
    assert {hit.content.identity for hit in faq_only.candidates} == {entry.identity}
    docs_only = service.query("AX-100", knowledge_base_ids=("kb",),
                              authorization=api().AuthorizationScope(("kb",), {"kb": ("manual",)}))
    assert {hit.content.identity for hit in docs_only.candidates} == {doc.identity}


def test_missing_real_faq_index_blocks_publish_and_fails_without_candidates(store):
    import psycopg
    from psycopg import sql
    records = [faq("one")]
    old = publish(store, records)
    store.prepare("kb", "s2", (), faq_identities=[records[0].identity])
    # External physical-index loss is fault injection; assertions use public APIs.
    with psycopg.connect(store.dsn) as connection:
        rows = connection.execute("SELECT idx.relname FROM pg_class idx JOIN pg_namespace n ON n.oid=idx.relnamespace "
                                  "JOIN pg_am am ON am.oid=idx.relam WHERE n.nspname=%s AND am.amname='paradedb' "
                                  "AND idx.relname LIKE 'bm25_faq_idx_%%'", (store.schema,)).fetchall()
        for (name,) in rows:
            connection.execute(sql.SQL("DROP INDEX {}.{}").format(sql.Identifier(store.schema), sql.Identifier(name)))
    with pytest.raises(api().SnapshotNotReady):
        store.publish("kb", "s2")
    assert store.pin(("kb",), authorization=api().AuthorizationScope(("kb",))).snapshots["kb"] == "s1"
    result = store.search_faq_bm25("AX-100", knowledge_base_id="kb", scope=old)
    assert result.status == "failed"
    assert result.candidates == ()
