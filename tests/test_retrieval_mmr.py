"""MMR behavior at the postprocessing seam; authored only, not executed.

The public query integration is added once the #86 service is available.
"""
from dataclasses import replace
import importlib

import unittest

contracts = importlib.import_module("app.modules.4_retrievalAndFusion.contracts")
fusion = importlib.import_module("app.modules.4_retrievalAndFusion.fusion_contracts")
mmr = importlib.import_module("app.modules.4_retrievalAndFusion.mmr")
body = importlib.import_module("app.modules.4_retrievalAndFusion.body_embeddings")
embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")


class Budget:
    def check(self):
        pass

    def remaining(self):
        return 10.0


def candidate(key, text, score):
    identity = contracts.EvidenceIdentity("kb", key, "v1", "chunk", "v1")
    return fusion.FusedCandidate(contracts.ContentRecord(identity, text, {"file": key}), score, ())


class Encoder:
    def __init__(self, vectors):
        self.scheme = embedding.IndexSchemeVersion(embedding.DeterministicEmbeddingAdapter(2).metadata)
        self.vectors = vectors

    def encode(self, texts, *, remaining):
        remaining.check()
        return tuple(body.BodyVector.for_text(text, self.scheme, self.vectors[text]) for text in texts)


class MMRTests(unittest.TestCase):
    def test_default_disabled_and_explicit_mmr_diversifies_actual_bodies(self):
        pool = (candidate("a", "parent full body", 10),
                candidate("b", "near duplicate parent", 9),
                candidate("c", "FAQ answer", 8), candidate("d", "other", 0))
        encoder = Encoder({"parent full body": (1, 0), "near duplicate parent": (1, 0),
                           "FAQ answer": (0, 1), "other": (-1, 0)})
        unchanged, step = mmr.select_mmr(pool, encoder=encoder, remaining=Budget(), limit=2)
        assert unchanged == pool
        assert step.status == "skipped"
        selected, step = mmr.select_mmr(pool, encoder=encoder, remaining=Budget(), limit=2,
                                        config=mmr.MMRConfig(enabled=True))
        assert selected == (pool[0], pool[2])
        assert selected[0] is pool[0]
        assert step == fusion.PostprocessStep("mmr", "complete")

    def test_lambda_boundaries_first_relevance_and_stable_identity_ties(self):
        for weight, expected in [(0, ("a", "c", "b")), (1, ("a", "b", "c"))]:
            with self.subTest(weight=weight, expected=expected):
                pool = (candidate("b", "b", 10), candidate("a", "a", 10), candidate("c", "c", 1))
                encoder = Encoder({"a": (1, 0), "b": (1, 0), "c": (0, 1)})
                selected, _ = mmr.select_mmr(pool, encoder=encoder, remaining=Budget(), limit=20,
                                            config=mmr.MMRConfig(True, weight))
                assert tuple(item.content.identity.document_id for item in selected) == expected

    def test_negative_cosine_is_zero_penalty_not_a_bonus_and_equal_scores_are_one(self):
        pool = tuple(candidate(key, key, 0) for key in ("c", "b", "a"))
        encoder = Encoder({"a": (1, 0), "b": (0, 1), "c": (-1, 0)})
        selected, _ = mmr.select_mmr(pool, encoder=encoder, remaining=Budget(), limit=2,
                                    config=mmr.MMRConfig(True, 0))
        assert tuple(item.content.text for item in selected) == ("a", "b")

    def test_any_invalid_pool_vector_rolls_back_whole_step_even_outside_final_limit(self):
        for invalid in [(), (0, 0), (1,), (float("nan"), 0),
                                             (float("inf"), 0), (True, 0), ("1", "0")]:
            with self.subTest(invalid=invalid):
                pool = (candidate("a", "a", 2), candidate("b", "b", 1), candidate("c", "c", 0))
                encoder = Encoder({"a": (1, 0), "b": (0, 1), "c": invalid})
                selected, step = mmr.select_mmr(pool, encoder=encoder, remaining=Budget(), limit=1,
                                              config=mmr.MMRConfig(True))
                assert selected == pool
                assert step == fusion.PostprocessStep("mmr", "partial", "mmr_invalid_vector")
                with self.assertRaises(mmr.MMRFailure) as caught:
                    mmr.select_mmr(pool, encoder=encoder, remaining=Budget(), limit=1,
                                   config=mmr.MMRConfig(True), postprocess_strict=True)
                assert caught.exception.step.status == "failed"

    def test_missing_vector_and_wrong_body_never_yield_partial_selection(self):
        pool = (candidate("a", "answer", 2), candidate("b", "parent", 1))

        class WrongBodyEncoder(Encoder):
            def encode(self, texts, *, remaining):
                return (body.BodyVector.for_text("question", self.scheme, (1, 0)),
                        body.BodyVector.for_text("child", self.scheme, (0, 1)))

        class MissingEncoder(Encoder):
            def encode(self, texts, *, remaining):
                return (body.BodyVector.for_text("answer", self.scheme, (1, 0)),)

        for encoder in (WrongBodyEncoder({}), MissingEncoder({})):
            selected, step = mmr.select_mmr(pool, encoder=encoder, remaining=Budget(), limit=1,
                                          config=mmr.MMRConfig(True))
            assert selected == pool
            assert step.reason == "mmr_invalid_vector"

    def test_timeout_is_safe_and_strict_failure_preserves_recall_inputs(self):
        pool = (candidate("a", "restricted body", 2),)

        class TimeoutEncoder(Encoder):
            def encode(self, texts, *, remaining):
                raise TimeoutError("provider secret and restricted body")

        selected, step = mmr.select_mmr(pool, encoder=TimeoutEncoder({}), remaining=Budget(), limit=1,
                                      config=mmr.MMRConfig(True))
        assert selected == pool
        assert step == fusion.PostprocessStep("mmr", "partial", "mmr_timeout")

    def test_candidate_provenance_is_preserved_without_expanding_pool(self):
        first = candidate("a", "answer", 2)
        child = candidate("child", "matched child text", 1).content
        first = replace(first, represented_identities=(first.content.identity, child.identity),
                        sources=({"file": "answer"}, {"file": "child"}), matched_children=(child,))
        pool = (first, candidate("b", "other answer", 1))
        selected, _ = mmr.select_mmr(pool, encoder=Encoder({"answer": (1, 0), "other answer": (0, 1)}),
                                    remaining=Budget(), limit=1, config=mmr.MMRConfig(True))
        assert selected == (first,)
        assert selected[0] is first
        assert selected[0].matched_children == (child,)

    def test_deadline_expiring_after_encoding_discards_all_mmr_output(self):
        class ExpiringBudget(Budget):
            expired = False

            def check(self):
                if self.expired:
                    raise TimeoutError

        class LateEncoder(Encoder):
            def encode(self, texts, *, remaining):
                vectors = super().encode(texts, remaining=remaining)
                remaining.expired = True
                return vectors

        pool = (candidate("a", "a", 2), candidate("b", "b", 1))
        selected, step = mmr.select_mmr(pool, encoder=LateEncoder({"a": (1, 0), "b": (0, 1)}),
                                      remaining=ExpiringBudget(), limit=1, config=mmr.MMRConfig(True))
        assert selected == pool
        assert step.reason == "mmr_timeout"

    def test_invalid_lambda_is_a_configuration_error(self):
        for value in [-0.1, 1.1, float("nan"), float("inf"), True]:
            with self.subTest(value=value):
                with self.assertRaises(contracts.RetrievalContractError):
                    mmr.MMRConfig(True, value)
