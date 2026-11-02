"""Optional, explicitly directed score normalization for weighted fusion.

Normalized scores are relative retrieval signals, never probabilities. Distance
is negated before normalization so that larger directed scores always rank first.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .contracts import RetrievalContractError


class NormalizationError(RetrievalContractError):
    """A route cannot contribute because its score contract is invalid."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NormalizedScores:
    values: tuple[float, ...]
    diagnostics: tuple[str, ...] = ()


def normalize_scores(scores: Iterable[float], *, metric: str,
                     strategy: str = "minmax") -> NormalizedScores:
    """Normalize one route's unique evidence scores, preserving their order."""
    if strategy not in ("minmax", "l2"):
        raise RetrievalContractError("normalization must be minmax or l2")
    similarities = ("similarity", "cosine_similarity", "bm25")
    distances = ("distance", "cosine_distance")
    if metric not in similarities + distances:
        raise NormalizationError("unknown_metric")
    values = tuple(scores)
    for score in values:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise NormalizationError("invalid_score")
        try:
            finite = math.isfinite(score)
        except OverflowError:
            finite = False
        if not finite:
            raise NormalizationError("invalid_score")
    values = tuple(float(score) for score in values)
    directed = tuple(-score for score in values) if metric in distances else values
    if not directed:
        return NormalizedScores(())
    if strategy == "l2":
        scale = max(abs(score) for score in directed)
        if scale == 0:
            return NormalizedScores((0.0,) * len(directed))
        scaled = tuple(score / scale for score in directed)
        norm = math.sqrt(math.fsum(score * score for score in scaled))
        return NormalizedScores(tuple(score / norm for score in scaled))
    low, high = min(directed), max(directed)
    if low == high:
        return NormalizedScores((1.0,) * len(directed), ("no_discrimination",))
    span = high - low
    if math.isfinite(span):
        return NormalizedScores(tuple((score - low) / span for score in directed))
    # Opposite signed finite extrema can overflow subtraction. Scale only in
    # that case, keeping precision for close non-equal values on normal routes.
    scale = max(abs(low), abs(high))
    scaled_low, scaled_high = low / scale, high / scale
    return NormalizedScores(tuple((score / scale - scaled_low) / (scaled_high - scaled_low)
                                  for score in directed))
