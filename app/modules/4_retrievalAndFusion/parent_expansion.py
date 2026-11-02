"""One-level expansion using the authoritative, scoped content-read boundary.

This stage consumes already compliant fused hits. It never searches vectors or
constructs a parent body from children. The reader must enforce full snapshot,
authorization and business conditions for the parent's own identity.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import inspect
from typing import Iterable, Protocol

from .contracts import ContentRecord, EvidenceIdentity, ReadScope
from .deadline import deadline_scope
from .fusion_contracts import FusedCandidate, PostprocessStep


class RemainingBudget(Protocol):
    def check(self) -> None: ...
    def remaining(self) -> float: ...


class ScopedContentReader(Protocol):
    def read(self, identity: EvidenceIdentity, *, scope: ReadScope,
             remaining: RemainingBudget | None = None) -> ContentRecord | None: ...


@dataclass(frozen=True)
class ParentExpansionResult:
    candidates: tuple[FusedCandidate, ...]
    step: PostprocessStep


def expand_parents(candidates: Iterable[FusedCandidate], *, store: ScopedContentReader,
                   scope: ReadScope, enabled: bool = False, strict: bool = False,
                   remaining: RemainingBudget | None = None) -> ParentExpansionResult:
    """Expand each original hit once; preserve children and their full score traces.

    ``remaining`` is the request's existing deadline, never a new timeout. A
    failed parent read keeps the already compliant child in default mode; strict
    mode fails closed with an empty candidate pool. Reason codes reveal neither
    restricted parent content nor whether it exists outside the query scope.
    """
    candidates = tuple(candidates)
    if not enabled:
        return ParentExpansionResult(candidates, PostprocessStep("parent", "skipped", "disabled"))
    expanded: list[FusedCandidate] = []
    cache: dict[EvidenceIdentity, tuple[ContentRecord | None, str | None]] = {}
    reasons: set[str] = set()
    applicable = False
    exhausted = False
    for candidate in candidates:
        child = candidate.content
        if child.parent is None:
            expanded.append(candidate)
            continue
        applicable = True
        parent_identity = child.parent
        parent = None
        reason = None
        if (not isinstance(child.identity, EvidenceIdentity)
                or not isinstance(parent_identity, EvidenceIdentity)
                or parent_identity.parts[:3] != child.identity.parts[:3]
                or parent_identity == child.identity):
            reason = "parent_invalid_relation"
        elif (parent_identity.knowledge_base_id not in scope.snapshots
              or parent_identity.knowledge_base_id not in scope.authorization.knowledge_base_ids
              or (parent_identity.knowledge_base_id in scope.authorization.document_ids
                  and parent_identity.document_id not in
                  scope.authorization.document_ids[parent_identity.knowledge_base_id])):
            reason = "parent_unavailable"
        elif any(trace.knowledge_base_id != child.identity.knowledge_base_id
                 or trace.snapshot_id != scope.snapshots.get(trace.knowledge_base_id)
                 or trace.identity != child.identity for trace in candidate.traces):
            reason = "parent_scope_mismatch"
        elif exhausted:
            reason = "parent_budget_exhausted"
        else:
            try:
                if remaining is not None:
                    remaining.check()
                if parent_identity not in cache:
                    if remaining is None:
                        parent = store.read(parent_identity, scope=scope)
                    else:
                        parameters = inspect.signature(store.read).parameters
                        options = {"scope": scope}
                        if "remaining" in parameters or any(
                                value.kind == value.VAR_KEYWORD for value in parameters.values()):
                            options["remaining"] = remaining
                        # Legacy PostgreSQL readers use the exact same root via context.
                        with deadline_scope(remaining):
                            parent = store.read(parent_identity, **options)
                    # A reader returning after the deadline cannot publish late data.
                    if remaining is not None:
                        remaining.check()
                    if parent is None:
                        reason = "parent_unavailable"
                    elif not isinstance(parent, ContentRecord) or parent.identity != parent_identity:
                        parent, reason = None, "parent_invalid_relation"
                    cache[parent_identity] = parent, reason
                parent, reason = cache[parent_identity]
                if parent is not None and parent.parent == child.identity:
                    parent, reason = None, "parent_invalid_relation"
            except TimeoutError:
                exhausted = True
                reason = "parent_budget_exhausted"
            except Exception:
                # Never expose database errors, existence or protected content.
                reason = "parent_read_failed"
                cache[parent_identity] = None, reason
        if reason is not None:
            reasons.add(reason)
            if strict:
                return ParentExpansionResult((), PostprocessStep("parent", "failed", reason))
            expanded.append(candidate)
            continue
        expanded.append(replace(
            candidate, content=parent,
            represented_identities=tuple(dict.fromkeys(
                (parent.identity, child.identity) + candidate.represented_identities)),
            sources=_unique((parent.source, child.source) + candidate.sources),
            matched_children=_unique((child,) + candidate.matched_children),
        ))
    if not applicable:
        return ParentExpansionResult(candidates, PostprocessStep("parent", "skipped", "not_applicable"))
    merged: dict[str, FusedCandidate] = {}
    for candidate in expanded:
        key = candidate.content.identity.key
        previous = merged.get(key)
        if previous is None:
            merged[key] = candidate
            continue
        merged[key] = replace(
            previous, score=max(previous.score, candidate.score),
            traces=previous.traces + candidate.traces,
            represented_identities=_unique(previous.represented_identities +
                                            candidate.represented_identities),
            sources=_unique((previous.content.source, candidate.content.source) +
                            previous.sources + candidate.sources),
            matched_children=_unique(previous.matched_children + candidate.matched_children),
        )
    ordered = tuple(sorted(merged.values(), key=lambda item: (-item.score, item.content.identity.parts)))
    return ParentExpansionResult(ordered, PostprocessStep(
        "parent", "partial" if reasons else "complete",
        ";".join(sorted(reasons)) if reasons else None,
    ))


def _unique(values: tuple) -> tuple:
    """Preserve provenance order, including JSON sources that are unhashable."""
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)
