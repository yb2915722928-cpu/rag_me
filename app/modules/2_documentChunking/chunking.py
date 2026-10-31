"""Deterministic conversion of handoff documents into retrieval chunks."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from importlib import import_module
from typing import Callable, Iterable, Sequence


class ChunkingError(ValueError):
    """Base error for invalid chunking configuration or handoff relationships."""


class InvalidChunkingConfiguration(ChunkingError):
    pass


class InvalidHandoffReference(ChunkingError):
    pass


@dataclass(frozen=True)
class ChunkingConfig:
    size: int = 500
    overlap: int = 0
    count_mode: str = "characters"
    token_counter: Callable[[str], int] | None = None
    strategy: str = "auto"
    table_mode: str = "rows"
    context_projection: bool = False
    parent_size: int | None = None
    parent_child: bool = False

    def validate(self) -> None:
        if not isinstance(self.size, int) or isinstance(self.size, bool) or self.size <= 0:
            raise InvalidChunkingConfiguration("size must be a positive integer")
        if not isinstance(self.overlap, int) or isinstance(self.overlap, bool) or self.overlap < 0:
            raise InvalidChunkingConfiguration("overlap must be a nonnegative integer")
        if self.overlap >= self.size:
            raise InvalidChunkingConfiguration("overlap must be smaller than size")
        if self.count_mode not in {"characters", "tokens"}:
            raise InvalidChunkingConfiguration("count_mode must be characters or tokens")
        if self.count_mode == "tokens" and self.token_counter is None:
            raise InvalidChunkingConfiguration("token_counter is required for token mode")
        if self.strategy not in {"auto", "fixed", "structured", "parent_child"}:
            raise InvalidChunkingConfiguration("unsupported strategy")
        if self.table_mode not in {"whole", "rows"}:
            raise InvalidChunkingConfiguration("table_mode must be whole or rows")
        if self.parent_size is not None and self.parent_size <= 0:
            raise InvalidChunkingConfiguration("parent_size must be positive")
        if self.parent_child and self.parent_size is None:
            raise InvalidChunkingConfiguration("parent_size is required for parent_child mode")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    business_id: str | None
    version: str | None
    text: str
    order: int
    unit_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    structure_path: tuple[str, ...] = ()
    alignment: str = "unmapped"
    body_span: tuple[int, int] | None = None
    strategy: str = "fixed"
    count_mode: str = "characters"
    count: int = 0
    diagnostics: tuple[dict, ...] = ()
    requires_review: bool = False
    projected_context: bool = False
    parent_chunk_id: str | None = None
    child_chunk_ids: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = dict(self.__dict__)
        result["unit_ids"] = list(self.unit_ids)
        result["source_ids"] = list(self.source_ids)
        result["structure_path"] = list(self.structure_path)
        result["diagnostics"] = [dict(item) for item in self.diagnostics]
        result["child_chunk_ids"] = list(self.child_chunk_ids)
        return result


@dataclass(frozen=True)
class ChunkingResult:
    chunks: tuple[Chunk, ...]
    diagnostics: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"chunks": [chunk.to_dict() for chunk in self.chunks], "diagnostics": list(self.diagnostics)}


def _handoff_types():
    return import_module("app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff")


def chunk_report(report, *, config: ChunkingConfig | None = None) -> ChunkingResult:
    """Chunk every independent document in a handoff report without mutating it."""
    if not hasattr(report, "documents"):
        raise TypeError("report must provide documents")
    return chunk_documents(report.documents, config=config)


def chunk_documents(documents: Iterable, *, config: ChunkingConfig | None = None) -> ChunkingResult:
    config = config or ChunkingConfig()
    config.validate()
    docs = tuple(documents)
    document_ids = [getattr(document, "id", None) for document in docs]
    if any(not item for item in document_ids) or len(set(document_ids)) != len(document_ids):
        raise InvalidHandoffReference("document ids must be non-empty and unique")
    chunks: list[Chunk] = []
    diagnostics: list[dict] = []
    for document in docs:
        produced, document_diagnostics = _chunk_document(document, config)
        chunks.extend(produced)
        diagnostics.extend(document_diagnostics)
    return ChunkingResult(tuple(chunks), tuple(diagnostics))


def chunk_document(document, *, config: ChunkingConfig | None = None) -> ChunkingResult:
    return chunk_documents((document,), config=config)


def chunk(value, *, config: ChunkingConfig | None = None) -> ChunkingResult:
    if hasattr(value, "documents"):
        return chunk_report(value, config=config)
    if hasattr(value, "id"):
        return chunk_document(value, config=config)
    return chunk_documents(value, config=config)


def _chunk_document(document, config: ChunkingConfig):
    if document.body is None or document.status not in {"success", "partial", "completed", "ok"}:
        return [], [{"code": "DOCUMENT_NOT_CHUNKED", "document_id": document.id, "message": "document has no usable body or did not succeed"}]
    units = list(document.units)
    if not units and not document.body:
        return [], []
    by_id = {unit.id: unit for unit in units}
    if len(by_id) != len(units):
        raise InvalidHandoffReference("unit ids must be unique")
    for unit in units:
        for source_id in unit.source_ids:
            if source_id not in {source.id for source in document.sources}:
                raise InvalidHandoffReference(f"unknown source reference: {source_id}")
    result: list[Chunk] = []
    diagnostics: list[dict] = [_diagnostic_dict(item) for item in document.diagnostics]
    counter = _counter(config)
    for unit in units:
        if len(unit.source_ids) > 1:
            diagnostics.append({"code": "MULTI_SOURCE_UNIT", "unit_id": unit.id, "message": "unit references multiple sources"})
        if unit.parent_id is not None and unit.parent_id not in by_id:
            raise InvalidHandoffReference(f"unknown parent reference: {unit.parent_id}")
    groups = _groups(units, config)
    for group in groups:
        if _protected(group):
            result.append(_protected_chunk(document, group, config, len(result), counter))
            continue
        strategy = _selected_strategy(group, config)
        result.extend(_fixed_group(document, group, config, len(result), counter, strategy))
    if config.parent_child:
        result = _add_parent_child(document, result, config, counter)
    return result, diagnostics


def _diagnostic_dict(item):
    if isinstance(item, dict):
        return dict(item)
    return {
        "level": getattr(item, "level", "warning"),
        "code": getattr(item, "code", "HANDOFF_DIAGNOSTIC"),
        "message": getattr(item, "message", str(item)),
        "document_id": getattr(item, "document_id", None),
        "unit_id": getattr(item, "unit_id", None),
        "source_id": getattr(item, "source_id", None),
        "details": dict(getattr(item, "details", {}) or {}),
    }


def _counter(config):
    return config.token_counter if config.count_mode == "tokens" else len


def _groups(units, config):
    groups = []
    current = []
    current_key = None
    for unit in units:
        key = _group_key(unit, config)
        if current and key != current_key:
            groups.append(current)
            current = []
        current.append(unit)
        current_key = key
    if current:
        groups.append(current)
    return groups


def _group_key(unit, config):
    kind = (unit.kind or "").lower()
    metadata = unit.metadata or {}
    if kind.startswith("table") or kind in {"table_row", "cell", "media", "service", "image", "audio", "video"}:
        table_id = metadata.get("table_id", unit.parent_id or unit.id)
        if config.table_mode == "whole" and kind in {"table", "table_row", "cell"}:
            return ("protected", tuple(unit.source_ids), table_id)
        if kind in {"table", "table_row", "cell"}:
            return ("protected", tuple(unit.source_ids), table_id, metadata.get("row_index", unit.id))
        return ("protected", unit.id)
    return ("text", tuple(unit.source_ids))


def _protected(group):
    return bool(group) and (group[0].kind or "").lower() in {"table", "table_row", "cell", "media", "service", "image", "audio", "video"}


def _unit_text(unit):
    return unit.text if isinstance(unit.text, str) else ""


def _protected_chunk(document, group, config, order, counter):
    text = "\n".join(_unit_text(unit) for unit in group if _unit_text(unit))
    diagnostics = []
    if counter(text) > config.size:
        diagnostics.append({"code": "PROTECTED_UNIT_OVER_BUDGET", "message": "protected unit was kept intact"})
    return _make_chunk(document, group, text, order, config, counter, "protected", diagnostics)


def _verified_body_range(document, group):
    if not document.body or not group or any(unit.alignment != "exact" or unit.body_span is None for unit in group):
        return None
    spans = []
    for unit in group:
        span = unit.body_span
        if not isinstance(span.start, int) or not isinstance(span.end, int):
            return None
        if span.start < 0 or span.end < span.start or span.end > len(document.body):
            return None
        if document.body[span.start:span.end] != _unit_text(unit):
            return None
        spans.append((span.start, span.end))
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        return None
    return spans[0][0], spans[-1][1]


def _valid_exact_spans(group, body):
    for unit in group:
        span = unit.body_span
        if span.start < 0 or span.end < span.start or span.end > len(body):
            return False
        if body[span.start:span.end] != _unit_text(unit):
            return False
    return True


def _selected_strategy(group, config):
    if config.strategy == "fixed":
        return "fixed"
    if config.strategy == "structured":
        return "structured"
    if config.strategy == "parent_child":
        return "fixed"
    return "structured" if any(_structure_path([unit]) for unit in group) else "fixed"


def _fixed_group(document, group, config, start_order, counter, strategy="fixed"):
    lo = _verified_body_range(document, group)
    if lo is not None:
        start, finish = lo
        text = document.body[start:finish]
    else:
        start = None
        text = "\n".join(_unit_text(unit) for unit in group if _unit_text(unit))
    if not text:
        return []
    chunks = []
    pos = 0
    while pos < len(text):
        end = _fit_end(text, pos, config.size, counter)
        if end <= pos:
            end = pos + 1
        part = text[pos:end]
        span_hint = (start + pos, start + end) if start is not None else None
        chunks.append(_make_chunk(document, group, part, start_order + len(chunks), config, counter, strategy, [], span_hint))
        if end >= len(text):
            break
        next_pos = _overlap_start(text, end, config.overlap, counter)
        pos = max(pos + 1, next_pos)
    return chunks


def _fit_end(text, start, size, counter):
    end = start
    while end < len(text) and counter(text[start:end + 1]) <= size:
        end += 1
    return end


def _overlap_start(text, end, overlap, counter):
    if overlap <= 0:
        return end
    start = end
    while start > 0 and counter(text[start - 1:end]) <= overlap:
        start -= 1
    return start


def _make_chunk(document, group, text, order, config, counter, strategy, diagnostics, span_hint=None):
    spans = [unit.body_span for unit in group if unit.alignment == "exact" and unit.body_span is not None]
    span = None
    alignment = "unmapped"
    body = document.body
    verified = _verified_body_range(document, group)
    if spans and body is not None and verified is not None:
        lo, hi = span_hint or verified
        if 0 <= lo <= hi <= len(body) and body[lo:hi] == text:
            span = (lo, hi)
            alignment = "exact"
        else:
            diagnostics = list(diagnostics) + [{"code": "SPAN_NOT_CONTIGUOUS", "message": "emitted text is not verified by the body span"}]
    path = _structure_path(group)
    if config.context_projection and path:
        prefix = " > ".join(path) + "\n"
        text = prefix + text
        if alignment == "exact":
            alignment = "document"
            span = None
            diagnostics = list(diagnostics) + [{"code": "CONTEXT_PROJECTED", "message": "projected context is not part of the exact body span"}]
    return Chunk(
        chunk_id=f"chunk-{document.id}-{order + 1}", document_id=document.id,
        business_id=document.business_id, version=document.version, text=text, order=order,
        unit_ids=tuple(unit.id for unit in group),
        source_ids=tuple(dict.fromkeys(source for unit in group for source in unit.source_ids)),
        structure_path=path, alignment=alignment, body_span=span, strategy=strategy,
        count_mode=config.count_mode, count=counter(text), diagnostics=tuple(diagnostics),
        requires_review=bool(diagnostics) or document.requires_review,
        projected_context=config.context_projection and bool(path),
    )


def _structure_path(group):
    for unit in group:
        metadata = unit.metadata or {}
        path = metadata.get("structure_path") or metadata.get("heading_path") or metadata.get("ancestors")
        if path:
            return tuple(path) if not isinstance(path, str) else (path,)
    return ()


def _add_parent_child(document, children, config, counter):
    if not children:
        return children
    parent_size = config.parent_size or config.size
    parents = []
    mapping = {}
    step = max(1, parent_size // config.size)
    runs = []
    current = []
    current_key = None
    for child in children:
        key = (child.source_ids, child.strategy == "protected")
        if current and key != current_key:
            runs.append(current)
            current = []
        current.append(child)
        current_key = key
    if current:
        runs.append(current)
    for run in runs:
        for index in range(0, len(run), step):
            group = run[index:index + step]
            text = "\n".join(chunk.text for chunk in group)
            parent_id = f"chunk-{document.id}-parent-{len(parents) + 1}"
            parent = Chunk(
                chunk_id=parent_id, document_id=document.id,
                business_id=document.business_id, version=document.version, text=text,
                order=len(children) + len(parents), unit_ids=tuple(i for chunk in group for i in chunk.unit_ids),
                source_ids=tuple(dict.fromkeys(i for chunk in group for i in chunk.source_ids)),
                strategy="parent", count_mode=config.count_mode, count=counter(text),
                child_chunk_ids=tuple(chunk.chunk_id for chunk in group),
            )
            parents.append(parent)
            for child in group:
                mapping[child.chunk_id] = parent_id
    children = [Chunk(**{**child.__dict__, "parent_chunk_id": mapping[child.chunk_id]}) for child in children]
    return children + parents


# Names used by callers that prefer an explicit API name.
chunk_documents_result = chunk_documents
