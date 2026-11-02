"""FAQ BM25 configuration and result contracts; no database work at import time."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import TYPE_CHECKING

from app.models.embedding import canonical_json
from .bm25 import BM25Analyzer

if TYPE_CHECKING:
    from .faq_contracts import FAQRecord, MatchedQuestion


@dataclass(frozen=True)
class FAQBM25Analyzer(BM25Analyzer):
    """Use the document release/tokenizers with a distinct question corpus identity."""

    @property
    def definition(self) -> dict:
        return {**super().definition, "corpus": "faq-questions"}


@dataclass(frozen=True)
class FAQBM25Candidate:
    content: FAQRecord
    snapshot_id: str
    raw_score: float
    analyzer_fingerprint: str
    matched_questions: tuple[MatchedQuestion, ...] = ()
    metric: str = "bm25"

    @property
    def scheme_identity(self) -> str:
        return "faq-bm25:" + self.analyzer_fingerprint


@dataclass(frozen=True)
class FAQBM25QueryResult:
    status: str
    candidates: tuple[FAQBM25Candidate, ...] = ()
    error: str | None = None
    algorithm: str = "pg_search-bm25"
    limitations: tuple[str, ...] = (
        "All text hits are materialized before eligibility and item ranking; performance is unverified.",
        "FAQ question corpus scores are independent of documents and other KB snapshots, not cross-corpus calibrated.",
    )


def faq_corpus_names(knowledge_base_id: str, snapshot_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(canonical_json([knowledge_base_id, snapshot_id]).encode()).hexdigest()[:40]
    return "bm25_faq_" + digest, "bm25_faq_idx_" + digest
