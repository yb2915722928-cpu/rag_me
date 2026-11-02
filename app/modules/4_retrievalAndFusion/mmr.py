"""All-or-nothing MMR over the actual final evidence bodies.

This step only selects existing candidates: it never reads new evidence, changes
recall status, or substitutes child/question vectors for delivered bodies.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import RetrievalContractError
from .body_embeddings import BodyEncodingError, BodyVector


@dataclass(frozen=True)
class MMRConfig:
    enabled: bool = False
    lambda_mult: float = 0.7

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise RetrievalContractError("mmr enabled must be boolean")
        if (isinstance(self.lambda_mult, bool) or not isinstance(self.lambda_mult, (int, float))
                or not math.isfinite(self.lambda_mult) or not 0 <= self.lambda_mult <= 1):
            raise RetrievalContractError("mmr lambda must be finite and within [0, 1]")


class MMRFailure(RetrievalContractError):
    """Strict postprocessing failure, with a safe public step rather than provider text."""

    def __init__(self, step):
        self.step = step
        super().__init__(step.reason)


def select_mmr(pool, *, encoder, remaining, limit, config=None, postprocess_strict=False):
    """Return (selected candidates, PostprocessStep); fallback preserves the whole pool.

    ``remaining`` is the same request Deadline received by earlier stages, not a
    freshly started timeout. Final truncation stays the caller's responsibility.
    """
    from .fusion_contracts import PostprocessStep

    config = config or MMRConfig()
    original = tuple(pool)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise RetrievalContractError("mmr limit must be a nonnegative integer")
    if not isinstance(postprocess_strict, bool):
        raise RetrievalContractError("postprocess_strict must be boolean")
    if not config.enabled:
        return original, PostprocessStep("mmr", "skipped", "disabled")
    if not original or limit == 0:
        return (), PostprocessStep("mmr", "complete")
    try:
        remaining.check()
        if encoder is None:
            raise BodyEncodingError("mmr_encoder_unavailable")
        scores = [candidate.score for candidate in original]
        if any(isinstance(score, bool) or not isinstance(score, (int, float))
               or not math.isfinite(score) for score in scores):
            raise BodyEncodingError("mmr_invalid_relevance")
        texts = tuple(candidate.content.text for candidate in original)
        encoded = tuple(encoder.encode(texts, remaining=remaining))
        remaining.check()
        if len(encoded) != len(original):
            raise BodyEncodingError("mmr_invalid_vector")
        vectors = []
        for text, entry in zip(texts, encoded):
            remaining.check()
            if not isinstance(entry, BodyVector) or not entry.matches(text, encoder.scheme):
                raise BodyEncodingError("mmr_invalid_vector")
            vectors.append(entry.unit_vector(encoder.scheme))
        low, high = min(scores), max(scores)
        # Scaling first prevents overflow for finite but widely separated scores.
        scale = max(abs(low), abs(high)) or 1.0
        relevance = ([1.0] * len(scores) if high == low else
                     [(score / scale - low / scale) / (high / scale - low / scale) for score in scores])
        identities = [candidate.content.identity.parts for candidate in original]
        pending = set(range(len(original)))
        first = min(pending, key=lambda index: (-relevance[index], identities[index]))
        chosen = [first]
        pending.remove(first)
        penalties = [0.0] * len(original)
        while pending and len(chosen) < min(limit, len(original)):
            remaining.check()
            last = chosen[-1]
            for index in pending:
                remaining.check()
                cosine = math.fsum(a * b for a, b in zip(vectors[index], vectors[last]))
                penalties[index] = max(penalties[index], min(1.0, max(0.0, cosine)))
            next_index = min(pending, key=lambda index: (
                -(config.lambda_mult * relevance[index] - (1 - config.lambda_mult) * penalties[index]),
                identities[index]))
            chosen.append(next_index)
            pending.remove(next_index)
        remaining.check()
        return tuple(original[index] for index in chosen), PostprocessStep("mmr", "complete")
    except Exception as error:
        safe_codes = {"mmr_invalid_vector", "mmr_invalid_relevance", "mmr_encoder_unavailable",
                      "mmr_encoding_unresolved", "mmr_encoding_failed"}
        reason = ("mmr_timeout" if isinstance(error, TimeoutError) else
                  error.code if isinstance(error, BodyEncodingError) and error.code in safe_codes
                  else "mmr_encoding_failed")
        step = PostprocessStep("mmr", "failed" if postprocess_strict else "partial", reason)
        if postprocess_strict:
            raise MMRFailure(step) from None
        return original, step
