"""Reusable #94 public-query scenarios; authored only, NOT RUN.

This is test input/oracle data, not a test runner or a replacement backend.
The public-query tests will consume it after #87/#89/#90/#91/#92/#93 are
integrated. No speculative service/FAQ constructor is imported here.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product


PINNED_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
QUERY = "USB-C AX-100 v2.1 如何恢复设备"


@dataclass(frozen=True)
class FeatureCase:
    parent_expansion: bool
    body_dedup: bool
    mmr: bool
    fusion: str
    normalization: str | None

    @property
    def case_id(self):
        strategy = self.fusion + ("-" + self.normalization if self.normalization else "")
        return (f"{strategy}-parent{int(self.parent_expansion)}"
                f"-dedup{int(self.body_dedup)}-mmr{int(self.mmr)}")


# All eight independent/combined feature settings, for each supported strategy.
# These names describe scenarios; wiring to RetrievalConfig waits for integration.
FEATURE_CASES = tuple(
    FeatureCase(parent, dedup, mmr, fusion, normalization)
    for parent, dedup, mmr in product((False, True), repeat=3)
    for fusion, normalization in (("rrf", None), ("weighted", "min_max"), ("weighted", "l2"))
)


@dataclass(frozen=True)
class BoundaryCase:
    case_id: str
    trigger: str
    expected: str


BOUNDARY_CASES = (
    BoundaryCase("defaults", "omit query config",
                 "route=50; pool=100; final=20; RRF k=60, weights=1; optional steps disabled; "
                 "overall=10s, route=5s, concurrency=4; MMR lambda=.7"),
    BoundaryCase("late-truncate", "top two children share a parent; a third distinct body remains in pool",
                 "merge parents before final K; fill from retained pool without copying evidence"),
    BoundaryCase("faq-contribution", "three matched questions belong to one FAQ in each FAQ route",
                 "one contribution per route/FAQ identity; retain all matched questions and answer"),
    BoundaryCase("proof-required", "equal normalized body but no trusted compatibility proof",
                 "retain both identities even when metadata happens to compare equal"),
    BoundaryCase("proof-compatible", "trusted caller proves applicability and version compatibility",
                 "merge exact normalized bodies, keep all identities/sources/contributions, take max score"),
    BoundaryCase("proof-incompatible", "same body with different applicability or incompatible version",
                 "retain separate evidence; FAQ/document stay separate by default"),
    BoundaryCase("body-for-mmr", "parent expansion and FAQ question recall precede MMR",
                 "encode actual parent full body and FAQ answer; never substitute child/question vectors"),
    BoundaryCase("stale-body-vector", "cached vector has wrong scheme or body fingerprint",
                 "re-encode in one caller-specified scheme within the original request budget"),
    BoundaryCase("mmr-incomplete", "one candidate cannot obtain a valid body vector",
                 "whole MMR step degrades to incoming order; no partial-pool MMR"),
    BoundaryCase("strict-postprocess", "explicitly requested step cannot complete and strict=True",
                 "visible failed step and safe reason; retain previously recorded route statuses"),
    BoundaryCase("parent-not-applicable", "ordinary evidence has no direct-parent relationship",
                 "not applicable, including strict mode; no fabricated parent or recursive expansion"),
    BoundaryCase("parent-denied", "child allowed but parent unauthorized, filtered, missing or wrong revision",
                 "retain eligible child in default mode; never expose parent text or sensitive errors"),
    BoundaryCase("scope-pin-failed", "snapshot pin fails at runtime after request validation",
                 "scope=None; routes not_executed; overall incomplete; no broadened retry"),
    BoundaryCase("snapshot-switch", "publish s2 after current request pins s1",
                 "documents, FAQ, parents and indexes remain on s1; next query sees s2"),
    BoundaryCase("failed-prepare", "new snapshot lacks a required physical index or authority member",
                 "publication rejected; old published pointer and next-query results preserved"),
    BoundaryCase("explicit-history", "query current publication then explicitly select retained s1",
                 "current excludes old versions; explicit history only reads requested s1"),
    BoundaryCase("partial-routes", "one KB/path fails while other paths complete",
                 "partial overall; successful routes contribute; failed weight not redistributed"),
    BoundaryCase("empty-versus-failure", "all paths return zero hits versus all paths fail",
                 "complete empty versus incomplete; distinct route statuses, no invented candidates"),
    BoundaryCase("queue-budget", "one running route consumes root deadline before queued route starts",
                 "running route timeout; queued route not_executed; no fresh timeout for later stages"),
    BoundaryCase("postprocess-budget", "recall leaves insufficient budget for parent read or encoding",
                 "same root deadline expires; safe default degradation or strict failure"),
    BoundaryCase("late-result", "external adapter completes after cancellation/timeout",
                 "returned result remains unchanged; cancellation propagated and concurrency stays bounded"),
    BoundaryCase("preflight-reject", "missing auth, unknown filter, bad limits/weights/lambda or malformed request",
                 "reject before pin/search/encoding; no permissive fallback"),
    BoundaryCase("selective-filter", "many unauthorized top hits precede one eligible hit",
                 "eligible TopK after full filter; ANN limitations reported without exact-recall claim"),
    BoundaryCase("filter-time", "nested AND/OR, IN/contains, missing/null, timezone half-open boundary",
                 "same condition and pinned now across all paths and body reads"),
    BoundaryCase("score-boundaries", "single candidate, tied scores, L2 all zero or nonfinite score",
                 "Min-Max ties=1/no-discrimination; L2 zeros=0; invalid scores fail safely; stable identity ties"),
    BoundaryCase("model-terms", "USB-C AX-100 v2.1 versus AX-100X and case variants",
                 "complete case-preserved exact tokens; no implicit rewriting or synonym expansion"),
    BoundaryCase("independent-corpus", "publish unrelated KB or FAQ questions",
                 "existing document corpus raw scores unchanged; document/FAQ rank separately"),
)


def document_corpus(api, *, knowledge_base_id="kb-a", version="v1"):
    """Build authoritative records using #83's already integrated public contract.

    Index child-a, child-b, duplicate and diverse, but explicitly leave parent and
    grandparent outside vector/BM25 manifests. Duplicate can collapse with parent
    only when a trusted caller supplies compatibility proof. The grandparent
    catches accidental recursive expansion. Caller owns indexing and publication.
    """
    def identity(chunk):
        return api.EvidenceIdentity(knowledge_base_id, "manual", version, chunk, "c1")

    def record(chunk, text, parent=None):
        return api.ContentRecord(
            identity(chunk), text,
            {"uri": "manual://" + knowledge_base_id + "/" + version, "section": chunk},
            {"product": "AX-100", "edition": version, "tags": ["public"],
             "effective": "2026-11-02T10:00:00+00:00"},
            parent,
        )

    return {
        "grandparent": record("grandparent", "不应递归展开的祖父全文"),
        "parent": record("parent", "USB-C AX-100 v2.1 完整恢复说明", identity("grandparent")),
        "child-a": record("child-a", "AX-100 恢复第一步", identity("parent")),
        "child-b": record("child-b", "AX-100 恢复第二步", identity("parent")),
        "duplicate": record("duplicate", "\r\nUSB-C AX-100 v2.1 完整恢复说明\r\n"),
        "diverse": record("diverse", "AX-100 保修与售后规则"),
    }


# Explicit deterministic route order, independent of actual encoder similarity or
# pg_search scores. Use only in injected public-route tests, not as a real-DB rank oracle.
DOCUMENT_ROUTE_ORDER = ("child-a", "child-b", "duplicate", "diverse")
# Same rank order on two equally weighted RRF routes. Literal worked examples:
# 2/(60+1), 2/(60+2). Parent merges take the first/max score, not their sum.
RRF_FIRST_SCORE = 0.03278688524590164
RRF_SECOND_SCORE = 0.03225806451612903

# Wire via #88/#89 public FAQ ingestion after integration; never turn this into
# ordinary document input or treat question vectors as answer-body vectors.
FAQ_INPUT = {
    "knowledge_base_id": "kb-a",
    "entry_id": "recovery-faq",
    "entry_version": "v1",
    "standard_question": "AX-100 如何恢复设备？",
    "similar_questions": ("AX-100 怎么恢复？", "USB-C v2.1 恢复步骤是什么？"),
    "answer": "连接 USB-C，按 AX-100 v2.1 完整恢复说明操作。",
    "metadata": {"product": "AX-100", "edition": "v1", "tags": ["public"]},
    "source": {"uri": "faq://kb-a/recovery/v1"},
}
