"""Public query MMR integration cases; authored only, not executed."""
import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import unittest

from test_retrieval_fusion import PublishedStore, content
from test_retrieval_body_embeddings import Provider, Repository

r = importlib.import_module("app.modules.4_retrievalAndFusion")
deadlines = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")
schedulers = importlib.import_module("app.modules.4_retrievalAndFusion.scheduler")


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


def query(service, *, remaining=None, **config):
    return service.query("USB-C", knowledge_base_ids=("kb",),
                         authorization=r.AuthorizationScope(("kb",)), remaining=remaining,
                         config=r.RetrievalConfig(final_top_k=2, **config))


class PublicMMRTests(unittest.TestCase):
    def test_public_default_is_disabled_and_does_not_encode(self):
        service, provider, _ = published_service()
        result = query(service)
        assert [item.content.identity.chunk_id for item in result.candidates] == ["a", "b"]
        assert provider.inputs == []
        assert result.steps[-1] == r.PostprocessStep("mmr", "skipped", "disabled")

    def test_public_mmr_diversifies_actual_bodies_and_preserves_root_budget_and_diagnostics(self):
        service, provider, budgets = published_service()
        root = deadlines.Deadline(10)
        result = query(service, remaining=root, mmr=True, mmr_lambda=0.0)
        assert [item.content.identity.chunk_id for item in result.candidates] == ["a", "c"]
        assert len(result.working_pool) == 3
        assert result.status == "complete"
        assert result.routes[0].status == "success"
        assert result.steps[-1] == r.PostprocessStep("mmr", "complete")
        assert provider.inputs == [(("full parent body", "similar parent body", "FAQ answer"), "document")]
        assert provider.budgets[0] is root
        assert budgets[0] is not root  # Recall routes receive their per-route child budget.
        assert all(candidate.traces[0].scheme_identity == "recall-scheme" for candidate in result.candidates)

    def test_public_failed_mmr_rolls_back_or_returns_empty_without_rewriting_recall(self):
        for strict in [False, True]:
            with self.subTest(strict=strict):
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

    def test_public_mmr_options_are_validated(self):
        for settings in [{"mmr": 1}, {"mmr_lambda": -0.1}, {"mmr_lambda": 1.1},
                                               {"mmr_lambda": float("nan")}, {"mmr_lambda": True}]:
            with self.subTest(settings=settings):
                with self.assertRaises(r.RetrievalContractError):
                    r.RetrievalConfig(**settings)

    def test_uncooperative_encoder_is_bounded_and_late_result_cannot_change_public_result(self):
        for strict in [False, True]:
            with self.subTest(strict=strict):
                service, _, _ = published_service()
                entered, release, exited = threading.Event(), threading.Event(), threading.Event()
                root = deadlines.Deadline(30)

                class BlockingEncoder:
                    def encode(self, texts, *, remaining):
                        assert remaining is root
                        entered.set()
                        try:
                            release.wait()
                            return ()
                        finally:
                            exited.set()

                service.mmr_encoder = BlockingEncoder()
                scheduler = schedulers.BoundedScheduler(4)
                service.scheduler = scheduler
                caller = ThreadPoolExecutor(max_workers=1)
                try:
                    future = caller.submit(query, service, remaining=root, mmr=True, postprocess_strict=strict)
                    assert entered.wait(2)
                    root.cancel()
                    result = future.result(timeout=2)
                    assert not exited.is_set()
                    assert result.status == "complete"
                    assert len(result.working_pool) == 3
                    assert [item.content.identity.chunk_id for item in result.candidates] == ([] if strict else ["a", "b"])
                    assert result.steps[-1] == r.PostprocessStep("mmr", "failed" if strict else "partial", "mmr_timeout")
                    before = result
                    release.set()
                    assert exited.wait(1)
                    assert result == before
                finally:
                    release.set()
                    caller.shutdown(wait=True)
                    scheduler.close()

    def test_public_parent_dedup_mmr_uses_final_parent_and_faq_answer_with_durable_encoding(self):
        for failed_stage in [None, "parent", "dedup"]:
            with self.subTest(failed_stage=failed_stage):
                parent = content("parent", text="full parent body")
                child = replace(content("child", text="only child snippet"), parent=parent.identity)
                duplicate = content("duplicate", doc="other", text=parent.text)
                faq = r.FAQRecord(r.FAQIdentity("kb", "faq", "v1"), "FAQ question", ("similar question",),
                                  "FAQ answer", {}, {"uri": "faq"})
                store = PublishedStore()
                store.ingest((parent, child, duplicate, faq))
                store.publish(store.prepare("kb", "s1", (parent.identity, child.identity, duplicate.identity, faq.identity)))
                root = deadlines.Deadline(10)
                reads, proofs = [], []

                def read(identity, *, scope, remaining):
                    assert remaining is root
                    reads.append(identity)
                    return None if failed_stage == "parent" else store.records[identity]

                store.read = read

                def search(query, *, scope, top_k, exact_terms, remaining):
                    assert exact_terms == ("USB-C",)
                    return r.RouteResult("mixed", "kb", "vector", "success", tuple(
                        r.RouteHit(record, scope.snapshots["kb"], 3 - index, "cosine_similarity", "recall-scheme")
                        for index, record in enumerate((child, duplicate, faq))))

                def prove(left, right, *, scope, remaining):
                    assert remaining is root
                    proofs.append((left.content.text, right.content.text))
                    if failed_stage == "dedup":
                        raise TimeoutError("private proof failure")
                    return r.BodyDedupProof("same applicability", "equivalent versions")

                provider, repository = Provider(), Repository()
                service = r.RetrievalService(store, routes=(r.RetrievalRoute("mixed", "kb", "vector", search),),
                                             mmr_encoder=r.Module3BodyEncoder(provider, repository))
                options = dict(knowledge_base_ids=("kb",), authorization=r.AuthorizationScope(("kb",)),
                               exact_terms=("USB-C",), remaining=root, body_dedup_prover=prove,
                               config=r.RetrievalConfig(parent_expansion=True, body_dedup=True, mmr=True,
                                                        postprocess_strict=True, final_top_k=2))
                result = service.query("USB-C", **options)
                assert result.status == "complete"
                assert result.routes[0].status == "success"
                assert reads == [parent.identity]
                if failed_stage:
                    assert result.candidates == ()
                    assert len(result.working_pool) == 3
                    assert result.steps[-1] == r.PostprocessStep("mmr", "skipped", "prior_stage_failed")
                    assert provider.inputs == []
                    continue
                assert [step.status for step in result.steps] == ["complete", "complete", "complete"]
                assert proofs == [(parent.text, duplicate.text)]
                assert [item.content for item in result.candidates] == [parent, faq]
                assert provider.inputs == [((parent.text, faq.answer), "document")]
                assert provider.budgets == [root]
                assert child in result.candidates[0].matched_children
                assert duplicate.identity in result.candidates[0].represented_identities
                assert all(attempt.status == "succeeded" for attempt in repository.attempts.values())
                service.mmr_encoder = r.Module3BodyEncoder(provider, repository)
                repeated = service.query("USB-C", **options)
                assert repeated.candidates == result.candidates
                assert len(provider.inputs) == 1
