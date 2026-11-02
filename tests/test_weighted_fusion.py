"""Weighted fusion behavior; authored test-first, deliberately NOT RUN for #90."""
import importlib
import unittest

weighted = importlib.import_module("app.modules.4_retrievalAndFusion.weighted_fusion")


class ScoreNormalizationTests(unittest.TestCase):
    def test_minmax_preserves_similarity_and_reverses_distance_direction(self):
        similarity = weighted.normalize_scores((2.0, 3.0, 6.0), metric="similarity")
        distance = weighted.normalize_scores((2.0, 3.0, 6.0), metric="distance")
        self.assertEqual(similarity.values, (0.0, 0.25, 1.0))
        self.assertEqual(distance.values, (1.0, 0.75, 0.0))
        self.assertEqual(similarity.diagnostics, ())
        self.assertEqual(distance.diagnostics, ())
        for metric in ("cosine_similarity", "bm25"):
            self.assertEqual(weighted.normalize_scores((2.0, 3.0, 6.0), metric=metric).values,
                             (0.0, 0.25, 1.0))
        self.assertEqual(weighted.normalize_scores((0.0, 0.5, 2.0), metric="cosine_distance").values,
                         (1.0, 0.75, 0.0))

    def test_singletons_and_equal_scores_have_explicit_no_discrimination(self):
        for scores in ((7.0,), (2.0, 2.0), (0.0, 0.0)):
            for metric in ("similarity", "distance"):
                with self.subTest(scores=scores, metric=metric):
                    result = weighted.normalize_scores(scores, metric=metric)
                    self.assertEqual(result.values, (1.0,) * len(scores))
                    self.assertEqual(result.diagnostics, ("no_discrimination",))
        self.assertEqual(weighted.normalize_scores((), metric="similarity").values, ())

    def test_l2_preserves_signed_direction_and_zero_vector_is_zero(self):
        self.assertEqual(weighted.normalize_scores((3.0, 4.0), metric="similarity", strategy="l2").values,
                         (0.6, 0.8))
        self.assertEqual(weighted.normalize_scores((3.0, 4.0), metric="distance", strategy="l2").values,
                         (-0.6, -0.8))
        self.assertEqual(weighted.normalize_scores((0.0, 0.0), metric="similarity", strategy="l2").values,
                         (0.0, 0.0))
        self.assertEqual(weighted.normalize_scores((-3.0, 4.0), metric="similarity", strategy="l2").values,
                         (-0.6, 0.8))

    def test_invalid_measurements_and_configuration_are_rejected_explicitly(self):
        for metric in (None, "", "cosine", "unknown"):
            with self.subTest(metric=metric):
                with self.assertRaisesRegex(weighted.NormalizationError, "unknown_metric"):
                    weighted.normalize_scores((1.0,), metric=metric)
        for bad in (float("nan"), float("inf"), -float("inf"), "1", None, True):
            with self.subTest(score=bad):
                with self.assertRaisesRegex(weighted.NormalizationError, "invalid_score"):
                    weighted.normalize_scores((1.0, bad), metric="similarity")
        with self.assertRaisesRegex(ValueError, "normalization"):
            weighted.normalize_scores((1.0,), metric="similarity", strategy="probability")

    def test_extreme_finite_scores_do_not_overflow_normalization(self):
        result = weighted.normalize_scores((-1e308, 0.0, 1e308), metric="similarity")
        self.assertEqual(result.values, (0.0, 0.5, 1.0))
        result = weighted.normalize_scores((1e308, 1e308), metric="similarity", strategy="l2")
        for value in result.values:
            self.assertAlmostEqual(value, 0.7071067811865475)
