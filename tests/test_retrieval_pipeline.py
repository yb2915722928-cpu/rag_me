"""#94 public query behavior; authored only, NOT EXECUTED.

External authority/search/encoding ports are controlled. Fusion, parent expansion,
body deduplication and MMR always run through the real public service.
"""
import pytest

from retrieval_pipeline_cases import FEATURE_CASES, RRF_FIRST_SCORE
from retrieval_pipeline_support import (
    r, BodyEncoder, assert_provenance, compatible, config_for,
    fixture_parts, make_routes, query,
)


@pytest.mark.parametrize("case", FEATURE_CASES, ids=lambda case: case.case_id)
def test_public_query_all_24_feature_combinations(case):
    documents, faq, authority, routes = fixture_parts()
    encoder = BodyEncoder()
    result = query(r.RetrievalService(authority, routes=routes, mmr_encoder=encoder), config=config_for(case))
    assert result.status == "complete"
    assert {route.method for route in result.routes} == {"vector", "bm25", "faq_vector", "faq_bm25"}
    assert all(route.status == "success" for route in result.routes)
    assert [(step.name, step.status) for step in result.steps] == [
        ("parent", "complete" if case.parent_expansion else "skipped"),
        ("dedup", "complete" if case.body_dedup else "skipped"),
        ("mmr", "complete" if case.mmr else "skipped")]
    assert_provenance(result, documents, faq, case)
    if case.mmr:
        assert set(encoder.inputs) == {item.content.text for item in result.working_pool}
        assert faq.answer in encoder.inputs
        assert not set(faq.questions).intersection(encoder.inputs)
        if case.parent_expansion:
            assert documents["parent"].text in encoder.inputs
            assert documents["child-a"].text not in encoder.inputs
    else:
        assert encoder.inputs == []
    first = next(item for item in result.working_pool if documents["child-a"].identity in item.represented_identities)
    # Independent hand-worked values for the two document paths (10,9,8,0).
    # Vector scores are .1 times lexical scores; per-path normalization cancels scale.
    expected = {("rrf", None): RRF_FIRST_SCORE,
                ("weighted", "min_max"): 2.,
                ("weighted", "l2"): 1.2777531299998799}[case.fusion, case.normalization]
    assert first.score == pytest.approx(expected)


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("stage", ["parent", "dedup", "mmr"])
def test_strict_and_default_failures_preserve_successful_route_diagnostics(stage, strict):
    documents, faq, authority, routes = fixture_parts()
    encoder = BodyEncoder(failure=TimeoutError("private provider body")) if stage == "mmr" else BodyEncoder()
    if stage == "parent":
        authority.denied.add(documents["parent"].identity)
    def broken_proof(*args, **options):
        raise RuntimeError("private policy body")
    result = query(r.RetrievalService(authority, routes=routes, mmr_encoder=encoder),
                   config=r.RetrievalConfig(parent_expansion=True, body_dedup=True, mmr=True,
                                            postprocess_strict=strict, final_top_k=2),
                   prover=broken_proof if stage == "dedup" else compatible)
    assert result.status == "complete"
    assert all(route.status == "success" for route in result.routes)
    step = next(step for step in result.steps if step.name == stage)
    # Dedup reports the failed proof step even when default mode retains its
    # incoming pool; parent/MMR explicitly report a partial step on fallback.
    assert step.status == ("failed" if strict or stage == "dedup" else "partial")
    assert step.reason
    assert "private" not in repr(result.steps)
    assert len(result.working_pool) >= 2
    if strict:
        assert result.candidates == ()
        following = result.steps[("parent", "dedup", "mmr").index(stage) + 1:]
        assert all(step.reason == "prior_stage_failed" for step in following)
    else:
        assert len(result.candidates) == 2


def test_unknown_compatibility_keeps_equal_bodies_and_mmr_failure_rolls_back_whole_pool():
    documents, faq, authority, routes = fixture_parts()
    service = r.RetrievalService(authority, routes=routes, mmr_encoder=BodyEncoder(failure=ValueError("secret")))
    result = query(service, prover=None,
                   config=r.RetrievalConfig(parent_expansion=True, body_dedup=True, mmr=True, final_top_k=4))
    assert len(result.working_pool) == 4
    assert result.candidates == result.working_pool
    assert {item.content.identity for item in result.candidates}.issuperset(
        {documents["parent"].identity, documents["duplicate"].identity})
    assert result.steps[-1].status == "partial"


@pytest.mark.parametrize("fusion,normalization", [("rrf", "minmax"), ("weighted", "minmax"), ("weighted", "l2")])
def test_failed_path_does_not_redistribute_weights(fusion, normalization):
    documents, faq, authority, _ = fixture_parts()
    routes = make_routes((documents["child-a"],), faq, failed=("vector",), scores=(10.,))
    result = query(r.RetrievalService(authority, routes=routes), config=r.RetrievalConfig(
        fusion_strategy=fusion, normalization=normalization, route_weights={"kb-a:bm25": 2., "kb-a:vector": 9.}))
    assert result.status == "partial"
    assert next(route for route in result.routes if route.method == "vector").status == "failed"
    candidate = next(item for item in result.candidates if item.content.identity == documents["child-a"].identity)
    assert len(candidate.traces) == 1
    assert candidate.traces[0].weight == 2.
    assert candidate.score == pytest.approx(2 / 61 if fusion == "rrf" else 2.)
    assert "credential" not in repr(result)


@pytest.mark.parametrize("failed,status,route_status", [(False, "complete", "empty"), (True, "incomplete", "failed")])
def test_empty_is_distinct_from_every_route_failed(failed, status, route_status):
    documents, faq, authority, _ = fixture_parts()
    methods = ("vector", "bm25", "faq_vector", "faq_bm25")
    routes = make_routes((documents["child-a"],), faq, failed=methods if failed else (), empty=() if failed else methods)
    result = query(r.RetrievalService(authority, routes=routes))
    assert result.status == status
    assert result.candidates == ()
    assert all(route.status == route_status for route in result.routes)


def test_runtime_pin_failure_has_no_scope_and_never_becomes_successful_empty():
    _, _, authority, routes = fixture_parts()
    authority.pin_error = RuntimeError("private connection string")
    result = query(r.RetrievalService(authority, routes=routes))
    assert result.status == "incomplete"
    assert result.scope is None
    assert result.candidates == ()
    assert all(route.status == "not_executed" for route in result.routes)
    assert "private" not in repr(result)


def test_root_cancellation_during_mmr_returns_without_accepting_late_vectors():
    import importlib
    import threading
    from concurrent.futures import ThreadPoolExecutor
    deadline = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")
    scheduling = importlib.import_module("app.modules.4_retrievalAndFusion.scheduler")
    documents, faq, authority, routes = fixture_parts()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    class HeldEncoder(BodyEncoder):
        def encode(self, texts, *, remaining):
            # Compute legitimate vectors before holding the external response.
            values = super().encode(texts, remaining=remaining)
            started.set()
            if not release.wait(5):
                raise TimeoutError("fixture release missing")
            finished.set()
            return values
    root = deadline.Deadline(30)
    workers = scheduling.BoundedScheduler(1)
    caller = ThreadPoolExecutor(max_workers=1)
    try:
        service = r.RetrievalService(authority, routes=routes, mmr_encoder=HeldEncoder(), scheduler=workers)
        future = caller.submit(query, service, remaining=root,
            config=r.RetrievalConfig(parent_expansion=True, body_dedup=True, mmr=True,
                                     postprocess_strict=True, max_concurrency=1, final_top_k=2))
        assert started.wait(2)
        root.cancel()
        result = future.result(timeout=2)
        assert result.candidates == ()
        assert all(route.status == "success" for route in result.routes)
        assert result.steps[-1].status == "failed"
        before = (result.candidates, result.working_pool, result.steps)
        release.set()
        assert finished.wait(2)
        assert (result.candidates, result.working_pool, result.steps) == before
    finally:
        release.set()
        caller.shutdown(wait=True)
        workers.close()


def test_mmr_changes_second_result_using_answer_not_question_vector():
    documents, faq, authority, _ = fixture_parts()
    # Three close scores and one zero anchor make the independent selection
    # unambiguous at lambda=.7: a=.7, duplicate=.33, diverse=.56 after first a.
    ordered = (documents["child-a"], documents["duplicate"], documents["diverse"], documents["child-b"])
    routes = make_routes(ordered, faq, empty=("faq_vector", "faq_bm25"), scores=(10., 9., 8., 0.))
    service = r.RetrievalService(authority, routes=routes, mmr_encoder=BodyEncoder())
    plain = query(service, config=r.RetrievalConfig(fusion_strategy="weighted", final_top_k=2))
    diversified = query(service, config=r.RetrievalConfig(fusion_strategy="weighted", mmr=True, final_top_k=2))
    assert [item.content for item in plain.candidates] == [ordered[0], ordered[1]]
    assert [item.content for item in diversified.candidates] == [ordered[0], ordered[2]]
    assert diversified.working_pool == plain.working_pool


def test_faq_answer_geometry_overrides_identical_question_geometry():
    documents, faq, authority, _ = fixture_parts()
    # Two document scores=2, FAQ=1.8, anchor=0. After first document:
    # duplicate=.4 versus orthogonal FAQ=.63. Using its question yields .33.
    docs = (documents["child-a"], documents["duplicate"], documents["diverse"])
    routes = make_routes(docs, faq, scores=(10., 10., 0.))
    encoder = BodyEncoder({docs[0].text: (1, 0), docs[1].text: (1, 0), docs[2].text: (1, 0),
                           faq.answer: (0, 1), **{question: (1, 0) for question in faq.questions}})
    result = query(r.RetrievalService(authority, routes=routes, mmr_encoder=encoder),
                   config=r.RetrievalConfig(fusion_strategy="weighted", mmr=True, final_top_k=2,
                       route_weights={"kb-a:faq_vector": .9, "kb-a:faq_bm25": .9}))
    assert [item.content for item in result.candidates] == [docs[0], faq]
    assert set(encoder.inputs) == {item.text for item in docs} | {faq.answer}
