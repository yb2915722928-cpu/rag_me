"""Conservative exact-body deduplication over the whole fused working pool.

Run after direct-parent expansion and before MMR/final truncation. Nothing is
retrieved here: the pinned scope and every original evidence identity survive.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, Sequence

from .contracts import ReadScope, required_strings
from .fusion_contracts import FusedCandidate, PostprocessStep


class RemainingBudget(Protocol):
    """The query's shared Deadline object, never a refreshed numeric budget."""

    def remaining(self) -> float: ...

    def check(self) -> None: ...


@dataclass(frozen=True)
class BodyDedupProof:
    """A trusted policy's attestations covering both candidates in their entirety.

    The prover must establish applicability and business-version compatibility
    for ALL represented identities, including parents and matched children, in
    the supplied pinned scope. References explain that decision; arbitrary equal
    strings are not evidence. Metadata equality, missing metadata and matching
    version labels alone never establish compatibility. This is a trusted caller
    seam, not a verifier for untrusted user input or an authorization grant.
    """

    applicability_evidence: str
    version_semantics_evidence: str

    def __post_init__(self):
        required_strings(self.applicability_evidence, self.version_semantics_evidence)


class BodyDedupProver(Protocol):
    def __call__(self, left: FusedCandidate, right: FusedCandidate, *,
                 scope: ReadScope, remaining: RemainingBudget | None) -> BodyDedupProof | None:
        """Return explicit compatibility evidence, or None if not provable.

        Must be bounded local work, or honor the shared deadline for any I/O.
        May not add candidates, broaden visibility or infer latest revisions.
        """
        ...


def _identity_key(candidate):
    # Same stable full-identity ordering used by fusion, including FAQ's tag.
    return candidate.content.identity.parts


def _unique(values):
    # Source mappings and content records need not be hashable. Equality removes
    # only repeated provenance, never distinct identities or different versions.
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _merge(members):
    representative = members[0]  # score descending, then full identity ascending
    return replace(
        representative,
        score=max(member.score for member in members),
        represented_identities=_unique(
            identity for member in members
            for identity in (member.content.identity, *member.represented_identities,
                             *(child.identity for child in member.matched_children))
        ),
        sources=_unique(
            source for member in members
            for source in (member.content.source, *member.sources,
                           *(child.source for child in member.matched_children))
        ),
        traces=tuple(trace for member in members for trace in member.traces),
        matched_children=_unique(child for member in members for child in member.matched_children),
    )


def process_body_dedup(
    pool: Sequence[FusedCandidate], *, scope: ReadScope, enabled: bool = False,
    prover: BodyDedupProver | None = None, remaining: RemainingBudget | None = None,
) -> tuple[tuple[FusedCandidate, ...], PostprocessStep]:
    """Return the full processed pool plus the dedup status, without padding.

    No prover means unknown compatibility and therefore preserves every entry.
    A declined comparison continues to the next same-body group. Compatibility
    need not be transitive: every original member must approve a new member.
    Failure is atomic: return the original pool with a safe failure code, letting
    the query's common postprocess_strict handling reject a requested downgrade.
    """
    original = tuple(pool)
    if not enabled:
        return original, PostprocessStep("dedup", "skipped", "disabled")
    try:
        if remaining is not None:
            remaining.check()
        if prover is None:
            return original, PostprocessStep("dedup", "complete")
        ordered = sorted(original, key=lambda item: (-item.score, _identity_key(item)))
        groups: list[list[FusedCandidate]] = []
        by_body: dict[tuple[type, str], list[list[FusedCandidate]]] = {}
        for item in ordered:
            if remaining is not None:
                remaining.check()
            # Different authoritative identity types cannot coalesce (FAQ/doc).
            key = (type(item.content.identity), item.content.text.replace("\r\n", "\n").strip())
            same_body = by_body.setdefault(key, [])
            for group in same_body:
                compatible = True
                for member in group:
                    if remaining is not None:
                        remaining.check()
                    proof = prover(member, item, scope=scope, remaining=remaining)
                    if remaining is not None:
                        remaining.check()
                    if proof is None:
                        compatible = False
                        break
                    if not isinstance(proof, BodyDedupProof):
                        raise TypeError("body dedup prover must return BodyDedupProof or None")
                if compatible:
                    group.append(item)
                    break
            else:
                group = [item]
                groups.append(group)
                same_body.append(group)
        result = []
        for group in groups:
            if remaining is not None:
                remaining.check()
            result.append(_merge(group) if len(group) > 1 else group[0])
        if remaining is not None:
            remaining.check()
        return tuple(result), PostprocessStep("dedup", "complete")
    except TimeoutError:
        return original, PostprocessStep("dedup", "failed", "deadline_exhausted")
    except Exception:
        # Never return exception text: a policy adapter may contain private data.
        return original, PostprocessStep("dedup", "failed", "compatibility_proof_failed")
