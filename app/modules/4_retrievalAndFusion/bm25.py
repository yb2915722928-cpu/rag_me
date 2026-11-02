"""Pinned pg_search document analysis and physical corpus SQL.

Based on pg_search v0.26.4 (727a888fd2801f013d765b1936c6e8eb3a3edf15).
SQL and compatibility are source-derived, NOT verified against a running server.
Each knowledge-base snapshot owns one immutable table and one ParadeDB index;
its BM25 statistics count chunks, never other knowledge bases or FAQ questions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import ContentRecord


@dataclass(frozen=True)
class BM25Candidate:
    content: ContentRecord
    snapshot_id: str
    raw_score: float
    analyzer_fingerprint: str
    metric: str = "bm25"

    @property
    def scheme_identity(self) -> str:
        """Route configuration identity; BM25 has no embedding scheme."""
        return "bm25:" + self.analyzer_fingerprint


@dataclass(frozen=True)
class BM25QueryResult:
    status: str
    candidates: tuple[BM25Candidate, ...] = ()
    error: str | None = None
    algorithm: str = "pg_search-bm25"
    limitations: tuple[str, ...] = (
        "Full text hits are materialized before authorization/filter/top-k; performance is unverified.",
        "Raw BM25 scores use independent snapshot corpora and are not calibrated across knowledge bases.",
    )


POSTGRES_VERSION_NUM = 170011
EXTENSION_VERSIONS = {"vector": "0.8.6", "pg_search": "0.26.4"}
MODEL_PATTERN = r"[A-Za-z0-9]+([._+-][A-Za-z0-9]+)*"


@dataclass(frozen=True)
class BM25Analyzer:
    """Immutable analysis definition; changes require a new snapshot.

    No synonym, traditional/simplified conversion, stemming or case rewrite.
    Dictionary identity is the built-in dictionary shipped with the pinned tag;
    arbitrary user dictionaries are deliberately not advertised as supported.
    """
    jieba_search_mode: bool = True
    jieba_lowercase: bool = False
    model_pattern: str = MODEL_PATTERN
    k1: float = 1.2
    b: float = 0.75

    def __post_init__(self):
        if type(self.jieba_search_mode) is not bool or type(self.jieba_lowercase) is not bool:
            raise ValueError("Jieba options must be boolean")
        if self.jieba_lowercase:
            raise ValueError("document BM25 preserves case; lowercase rewriting is unsupported")
        if self.model_pattern != MODEL_PATTERN:
            raise ValueError("only the pinned case-preserving model tokenizer is supported")
        for name, value in (("k1", self.k1), ("b", self.b)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.k1 <= 0 or not 0 <= self.b <= 1:
            raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")

    @property
    def definition(self) -> dict:
        return {"options": asdict(self), "postgres": POSTGRES_VERSION_NUM,
                "extensions": dict(EXTENSION_VERSIONS),
                "tag_commit": "727a888fd2801f013d765b1936c6e8eb3a3edf15",
                "dictionary": "pg_search-0.26.4-builtin-jieba",
                "fields": {"body": "jieba", "body_models": "regex_pattern"},
                "trim": True, "model_lowercase": False, "corpus": "document-chunks"}

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.definition, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def corpus_names(knowledge_base_id: str, snapshot_id: str) -> tuple[str, str]:
    """Hash complete identities to bounded SQL identifiers; never interpolate IDs."""
    payload = json.dumps([knowledge_base_id, snapshot_id], ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]
    return "bm25_doc_" + digest, "bm25_idx_" + digest


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def create_index_sql(namespace: str, table: str, index: str, analyzer: BM25Analyzer) -> str:
    """Only validated configuration reaches DDL; no caller query text is SQL."""
    mode = str(analyzer.jieba_search_mode).lower()
    # The model pattern is pinned and has no SQL quote; numerics are validated.
    return (f"CREATE INDEX {quote_identifier(index)} ON {namespace}.{quote_identifier(table)} "
            "USING paradedb (id, "
            f"(body::pdb.jieba('search_mode={mode}', 'trim=true', 'lowercase=false', "
            f"'k1={analyzer.k1}', 'b={analyzer.b}')), "
            f"(body_models::pdb.regex_pattern('{analyzer.model_pattern}', 'lowercase=false', "
            f"'k1={analyzer.k1}', 'b={analyzer.b}'))) WITH (key_field='id')")


def text_match(query: str, exact_terms: tuple[str, ...]) -> tuple[str, list]:
    """pg_search uses the indexed analyzer on RHS text; exact terms bypass it."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("BM25 query must be non-empty text")
    if not isinstance(exact_terms, tuple) or any(not isinstance(t, str) or not t for t in exact_terms):
        raise ValueError("exact_terms must contain non-empty final tokens")
    if exact_terms:
        return "t.body_models &&& %s::text[]", [list(exact_terms)]
    return "(t.body ||| %s::text OR t.body_models ||| %s::text)", [query, query]
