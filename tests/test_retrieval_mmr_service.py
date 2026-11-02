"""Public query MMR integration cases; authored only, not executed."""
import importlib

import pytest

from test_retrieval_fusion import PublishedStore, content
from test_retrieval_body_embeddings import Provider, Repository

r = importlib.import_module("app.modules.4_retrievalAndFusion")


def published_service(*, provider=None):
    records = (content("a", text="full parent body"),
               content("b", text="similar parent body"), content("c", text="FAQ answer"))
    store = PublishedStore()
    store.ingest(records)
    store.publish(store.prepare("kb", "s1", [record.identity for record in records]))
    budgets = []

    def search(query, *, scope, top_k, exact_terms, remaining):
        budgets.append(remaining)
        return r.RouteResult("v", "kb", "vector", "success", tuple(
            r.RouteHit(record, scope.snapshots["kb"], 3 - index, "cosine_similarity", "recall-scheme")
            for index, record in enumerate(records)))

    provider = Provider() if provider is None else provider
    encoder = r.Module3BodyEncoder(provider, Repository())
    service = r.RetrievalService(store, routes=(r.RetrievalRoute("v", "kb", "vector", search),),
                                 mmr_encoder=encoder)
    return service, provider, budgets


def query(service, **config):
    return service.query("USB-C", knowledge_base_ids=("kb",),
                         authorization=r.AuthorizationScope(("kb",)),
                         config=r.RetrievalConfig(final_top_k=2, **config))


def test_public_default_is_disabled_and_does_not_encode():
    service, provider, _ = published_service()
    result = query(service)
    assert [item.content.identity.chunk_id for item in result.candidates] == ["a", "b"]
    assert provider.inputs == []
    assert result.steps[-1] == r.PostprocessStep("mmr", "skipped", "disabled")


def test_public_mmr_diversifies_actual_bodies_and_preserves_root_budget_and_diagnostics():
    service, provider, budgets = published_service()
    result = query(service, mmr=True, mmr_lambda=0.0)
    assert [item.content.identity.chunk_id for item in result.candidates] == ["a", "c"]
    assert len(result.working_pool) == 3
    assert result.status == "complete"
    assert result.routes[0].status == "success"
    assert result.steps[-1] == r.PostprocessStep("mmr", "complete")
    assert provider.inputs == [(("full parent body", "similar parent body", "FAQ answer"), "document")]
    assert provider.budgets[0] is budgets[0]
    assert all(candidate.traces[0].scheme_identity == "recall-scheme" for candidate in result.candidates)


@pytest.mark.parametrize("strict", [False, True])
def test_public_failed_mmr_rolls_back_or_returns_empty_without_rewriting_recall(strict):
    class InvalidProvider(Provider):
        def embed_role(self, texts, role, *, remaining=None):
            return [(0.0, 0.0) for text in texts]

    service, _, _ = published_service(provider=InvalidProvider())
    result = query(service, mmr=True, postprocess_strict=strict)
    assert result.status == "complete"
    assert result.routes[0].status == "success"
    assert len(result.working_pool) == 3
    assert [item.content.identity.chunk_id for item in result.candidates] == ([] if strict else ["a", "b"])
    assert result.steps[-1].status == ("failed" if strict else "partial")


@pytest.mark.parametrize("settings", [{"mmr": 1}, {"mmr_lambda": -0.1}, {"mmr_lambda": 1.1},
                                       {"mmr_lambda": float("nan")}, {"mmr_lambda": True}])
def test_public_mmr_options_are_validated(settings):
    with pytest.raises(r.RetrievalContractError):
        r.RetrievalConfig(**settings)
