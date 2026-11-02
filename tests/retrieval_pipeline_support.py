"""External ports and public-result assertions for #94; authored, not executed."""
import importlib
from retrieval_pipeline_cases import PINNED_NOW, QUERY, document_corpus

r = importlib.import_module("app.modules.4_retrievalAndFusion")
embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")
body = importlib.import_module("app.modules.4_retrievalAndFusion.body_embeddings")
dedup = importlib.import_module("app.modules.4_retrievalAndFusion.body_dedup")


def config_for(case, **overrides):
    values = dict(parent_expansion=case.parent_expansion, body_dedup=case.body_dedup,
                  mmr=case.mmr, fusion_strategy=case.fusion,
                  normalization="minmax" if case.normalization in (None, "min_max") else "l2",
                  final_top_k=2, pool_size=100)
    values.update(overrides)
    return r.RetrievalConfig(**values)


def faq_record(kb="kb-a", version="v1"):
    return r.FAQRecord(r.FAQIdentity(kb, "recovery-faq", version),
                       "AX-100 如何恢复设备", ("AX-100 怎么恢复", "AX-100 恢复步骤"),
                       "连接 USB-C，按 AX-100 完整恢复说明操作。",
                       {"product": "AX-100", "edition": version}, {"uri": f"faq://{kb}/{version}"})


def compatible(left, right, *, scope, remaining):
    """Fixture authority explicitly attests only the curated manual family."""
    remaining.check()
    identities = (left.content.identity, *left.represented_identities,
                  right.content.identity, *right.represented_identities)
    if all(isinstance(i, r.EvidenceIdentity) and i.document_id == "manual"
           and i.document_version == "v1" and i.knowledge_base_id in scope.snapshots for i in identities):
        return dedup.BodyDedupProof("fixture:manual-applicability", "fixture:manual-v1-compatibility")
    return None


class BodyEncoder:
    """Only external vector generation is controlled; real MMR selects results."""
    def __init__(self, vectors=None, failure=None):
        self.scheme = embedding.IndexSchemeVersion(embedding.DeterministicEmbeddingAdapter(2).metadata)
        self.vectors = vectors or {}
        self.inputs = []
        self.failure = failure

    def encode(self, texts, *, remaining):
        remaining.check()
        self.inputs.extend(texts)
        if self.failure:
            raise self.failure
        return tuple(body.BodyVector.for_text(text, self.scheme,
                     self.vectors.get(text, (0, 1) if "售后" in text or "连接" in text else (1, 0)))
                     for text in texts)


class AuthorityPort:
    """In-memory external authority; no fusion or postprocessing implementation."""
    def __init__(self, documents, faqs):
        self.records = {item.identity: item for item in (*documents, *faqs)}
        self.snapshot = "s1"
        self.denied = set()
        self.pin_error = None

    def pin(self, knowledge_base_ids, *, authorization, conditions=None, snapshot_ids=None, remaining=None):
        remaining.check()
        if self.pin_error:
            raise self.pin_error
        return r.ReadScope({kb: (snapshot_ids or {}).get(kb, self.snapshot) for kb in knowledge_base_ids},
                           authorization, conditions, PINNED_NOW)

    def read(self, identity, *, scope, remaining):
        remaining.check()
        return None if identity in self.denied else self.records.get(identity)


def make_routes(documents, faq, *, failed=(), empty=(), scores=(10., 9., 8., 0.)):
    routes = []
    kb = faq.identity.knowledge_base_id
    for method in ("vector", "bm25", "faq_vector", "faq_bm25"):
        route_id = f"{kb}:{method}"
        def search(query, *, scope, top_k, exact_terms, remaining, method=method, route_id=route_id):
            remaining.check()
            if method in failed:
                raise RuntimeError("private endpoint credential must not escape")
            if method in empty:
                return r.RouteResult(route_id, kb, method, "empty")
            metric = "cosine_similarity" if "vector" in method else "bm25"
            if method.startswith("faq"):
                questions = tuple(r.MatchedQuestion(q, 1. - n / 10) for n, q in enumerate(faq.questions))
                hits = (r.RouteHit(faq, scope.snapshots[kb], 1., metric, "fixture-scheme", questions),)
            else:
                hits = tuple(r.RouteHit(item, scope.snapshots[kb], score if metric == "bm25" else score / 10,
                                       metric, "fixture-scheme") for item, score in zip(documents, scores))
            return r.RouteResult(route_id, kb, method, "success", hits[:top_k])
        routes.append(r.RetrievalRoute(route_id, kb, method, search))
    return tuple(routes)


def fixture_parts():
    documents = document_corpus(r)
    faq = faq_record()
    authority = AuthorityPort(tuple(documents.values()), (faq,))
    routes = make_routes(tuple(documents[name] for name in ("child-a", "child-b", "duplicate", "diverse")), faq)
    return documents, faq, authority, routes


def query(service, *, config=None, prover=compatible, **options):
    return service.query(QUERY, knowledge_base_ids=("kb-a",), authorization=r.AuthorizationScope(("kb-a",)),
                         config=config, body_dedup_prover=prover, **options)


def assert_provenance(result, documents, faq, case):
    """Set-based input/output conservation, not an implementation of ranking."""
    pool = result.working_pool
    expected = {documents[name].identity for name in ("child-a", "child-b", "duplicate", "diverse")}
    expected.add(faq.identity)
    observed = {trace.identity for item in pool for trace in item.traces}
    assert observed == expected
    assert documents["grandparent"].identity not in {item.content.identity for item in pool}
    assert len(pool) == (3 if case.parent_expansion and case.body_dedup else 4 if case.parent_expansion else 5)
    assert len(result.candidates) == 2
    assert len({item.content.identity for item in result.candidates}) == 2
    assert all(item in pool for item in result.candidates)
    faq_hit = next(item for item in pool if item.content.identity == faq.identity)
    assert faq_hit.content.text == faq.answer
    assert len(faq_hit.traces) == 2
    assert {trace.method for trace in faq_hit.traces} == {"faq_vector", "faq_bm25"}
    assert all({q.question for q in trace.matched_questions} == set(faq.questions) for trace in faq_hit.traces)
    for item in pool:
        assert all(trace.snapshot_id == result.scope.snapshots[trace.knowledge_base_id] for trace in item.traces)
        assert item.content.source in item.sources
        assert item.content.identity in item.represented_identities
    if case.parent_expansion:
        parent = next(item for item in pool if item.content.identity == documents["parent"].identity)
        assert set(child.identity for child in parent.matched_children) == {
            documents["child-a"].identity, documents["child-b"].identity}
        assert parent.content.text == documents["parent"].text
        for name in ("child-a", "child-b"):
            assert documents[name].source in parent.sources
        if case.body_dedup:
            assert documents["duplicate"].identity in parent.represented_identities
            assert documents["duplicate"].source in parent.sources
            assert len(parent.traces) == 6
        else:
            assert len(parent.traces) == 4
    else:
        assert all(not item.matched_children for item in pool)
    if not case.mmr:
        assert result.candidates == pool[:2]
