"""#86 public dual-route specifications, authored only and NOT EXECUTED.

Opt in with RETRIEVAL_FUSION_TEST_DSN pointing at a disposable PostgreSQL instance
with the pinned pgvector and pg_search extensions. No external embedding API is
needed: document/query encoding uses module3's deterministic adapter.
"""
import importlib
import os
import uuid

import pytest

r = importlib.import_module("app.modules.4_retrievalAndFusion")
indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


@pytest.fixture
def backend():
    dsn = os.environ.get("RETRIEVAL_FUSION_TEST_DSN")
    if not dsn:
        pytest.skip("requires explicit disposable PostgreSQL/pgvector/pg_search database")
    psycopg = pytest.importorskip("psycopg")
    schema = "test_fusion_" + uuid.uuid4().hex
    encoder = indexing.DeterministicEmbeddingAdapter(3)
    store = r.PostgresBM25RetrievalStore(dsn, schema=schema, adapter_for_scheme=lambda scheme: encoder)
    try:
        store.migrate()
        yield store, encoder
    finally:
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                from psycopg import sql
                cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def record(kb="kb", document="manual", version="v1", **metadata):
    return r.ContentRecord(r.EvidenceIdentity(kb, document, version, "chunk", "c1"),
                           "AX-100 USB-C 中文说明", {"uri": "manual://" + document}, metadata)


def prepare(store, encoder, kb, snapshot, records):
    indexed = store.index_documents(records, encoder)
    assert all(item.status == "stored" for item in indexed.items)
    store.prepare(kb, snapshot, [row.identity for row in records],
                  required_indexes=("content", "vector", "bm25"),
                  vector_scheme=indexing.IndexSchemeVersion(encoder.metadata),
                  field_types={"visibility": "string"})


def query(store, *, kbs=("kb",), authorization=None, **options):
    return r.RetrievalService(store).query("AX-100", knowledge_base_ids=kbs,
        authorization=authorization if authorization is not None else r.AuthorizationScope(kbs), **options)


def test_real_public_chain_merges_two_routes_and_retains_provenance(backend):
    store, encoder = backend
    source = record()
    prepare(store, encoder, "kb", "s1", [source])
    store.publish("kb", "s1")
    result = query(store)
    assert result.status == "complete"
    assert [route.status for route in result.routes] == ["success", "success"]
    assert len(result.candidates) == len(result.working_pool) == 1
    candidate = result.candidates[0]
    assert candidate.content == source
    assert candidate.score == pytest.approx(0.03278688524590164)
    assert candidate.represented_identities == (source.identity,)
    assert candidate.sources == (source.source,)
    assert {trace.metric for trace in candidate.traces} == {"cosine_similarity", "bm25"}
    assert {trace.route_id for trace in candidate.traces} == {"kb:vector", "kb:bm25"}
    assert {trace.scheme_identity for trace in candidate.traces} == {
        indexing.IndexSchemeVersion(encoder.metadata).identity, "bm25:" + r.BM25Analyzer().fingerprint}
    assert all(trace.identity == source.identity and trace.snapshot_id == "s1" and trace.rank == 1
               for trace in candidate.traces)
    scope = result.scope
    vector = store.search_vector("AX-100", knowledge_base_id="kb", scope=scope, top_k=50)
    lexical = store.search_bm25("AX-100", knowledge_base_id="kb", scope=scope, top_k=50)
    assert {trace.metric: trace.raw_score for trace in candidate.traces} == {
        "cosine_similarity": vector.candidates[0].raw_score, "bm25": lexical.candidates[0].raw_score}
    assert store.read(candidate.content.identity, scope=scope) == source


def test_real_multiple_kbs_preserve_identity_and_pool_before_final_cut(backend):
    store, encoder = backend
    records = [record(kb) for kb in ("left", "right")]
    for source in records:
        kb = source.identity.knowledge_base_id
        prepare(store, encoder, kb, "s1", [source])
        store.publish(kb, "s1")
    result = query(store, kbs=("right", "left"), config=r.RetrievalConfig(final_top_k=1))
    assert result.status == "complete"
    assert len(result.routes) == 4
    assert [item.content.identity for item in result.working_pool] == sorted(row.identity for row in records)
    assert len(result.candidates) == 1
    assert all(len(item.traces) == 2 for item in result.working_pool)
    assert all(trace.knowledge_base_id == item.content.identity.knowledge_base_id
               for item in result.working_pool for trace in item.traces)


def test_real_public_query_filters_and_authorization_precede_route_top_k(backend):
    store, encoder = backend
    allowed = record(document="allowed", visibility="public")
    denied = record(document="denied", visibility="private")
    prepare(store, encoder, "kb", "s1", [allowed, denied])
    store.publish("kb", "s1")
    result = query(store, conditions={"field": "visibility", "op": "eq", "value": "public"},
                   authorization=r.AuthorizationScope(("kb",), {"kb": ("allowed",)}),
                   config=r.RetrievalConfig(route_top_k=1), exact_terms=("AX-100",))
    assert result.status == "complete"
    assert [item.content for item in result.candidates] == [allowed]
    assert all([hit.content for hit in route.candidates] == [allowed] for route in result.routes)
    empty = query(store, authorization=r.AuthorizationScope(("kb",), {"kb": ()}))
    assert empty.status == "complete"
    assert empty.candidates == ()
    assert all(route.status == "empty" for route in empty.routes)


def test_real_historical_snapshot_and_route_failure_remain_explicit(backend):
    store, encoder = backend
    old, new = record(), record(version="v2")
    prepare(store, encoder, "kb", "s1", [old])
    store.publish("kb", "s1")
    prepare(store, encoder, "kb", "s2", [new])
    store.publish("kb", "s2")
    historical = query(store, snapshot_ids={"kb": "s1"})
    current = query(store)
    assert historical.candidates[0].content == old
    assert current.candidates[0].content == new
    assert all(trace.snapshot_id == "s1" for trace in historical.candidates[0].traces)

    def unavailable(scheme):
        raise RuntimeError("embedding endpoint unavailable")

    store.adapter_for_scheme = unavailable
    partial = query(store)
    assert partial.status == "partial"
    assert [(route.method, route.status) for route in partial.routes] == [("vector", "failed"), ("bm25", "success")]
    assert partial.candidates[0].content == new
    assert partial.candidates[0].score == pytest.approx(0.01639344262295082)
    assert len(partial.candidates[0].traces) == 1
    # A published content-only snapshot has neither retrieval resource. This is
    # incomplete retrieval, not a successful query that happened to find no hits.
    store.prepare("kb", "content-only", [new.identity], required_indexes=("content",))
    store.publish("kb", "content-only")
    failed = query(store)
    assert failed.status == "incomplete"
    assert failed.candidates == ()
    assert all(route.status == "failed" and route.candidates == () for route in failed.routes)
