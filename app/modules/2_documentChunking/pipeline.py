"""文档切分文件夹的流程编排。

公开接口接收交接报告、文档或文档迭代器。本模块负责协调校验与切分策略，
保持输入对象不变，并在每个返回块中保留来源追踪信息。
"""
from __future__ import annotations

from .errors import InvalidHandoffReference
from .models import Chunk, ChunkingConfig, ChunkingResult
from .provenance import diagnostic_dict, structure_path, unit_text, verified_body_range
from .relationships import add_parent_child
from .strategies import counter_for, fixed_group, groups, is_protected, protected_text, selected_strategy


_SUCCESS_STATUSES = {"success", "partial", "completed", "ok"}


def chunk_report(report, *, config=None):
    """切分交接报告中的每个独立文档。"""
    if not hasattr(report, "documents"):
        raise TypeError("report must provide documents")
    return chunk_documents(report.documents, config=config)


def chunk_documents(documents, *, config=None):
    """校验配置，并按稳定的输入顺序处理文档。"""
    config = config or ChunkingConfig()
    config.validate()
    docs = tuple(documents)
    document_ids = [getattr(document, "id", None) for document in docs]
    if any(not item for item in document_ids) or len(set(document_ids)) != len(document_ids):
        raise InvalidHandoffReference("document ids must be non-empty and unique")
    chunks = []
    diagnostics = []
    for document in docs:
        produced, document_diagnostics = _chunk_document(document, config)
        chunks.extend(produced)
        diagnostics.extend(document_diagnostics)
    return ChunkingResult(tuple(chunks), tuple(diagnostics))


def chunk_document(document, *, config=None):
    return chunk_documents((document,), config=config)


def chunk(value, *, config=None):
    """根据交接对象的形态，分派便捷入口。"""
    if hasattr(value, "documents"):
        return chunk_report(value, config=config)
    if hasattr(value, "id"):
        return chunk_document(value, config=config)
    return chunk_documents(value, config=config)


def _chunk_document(document, config):
    """切分单个文档，并保留不可用交接输入的诊断信息。"""
    if document.body is None or document.status not in _SUCCESS_STATUSES:
        return [], [{"code": "DOCUMENT_NOT_CHUNKED", "document_id": document.id, "message": "document has no usable body or did not succeed"}]
    units = list(document.units)
    if not units and not document.body:
        return [], []
    by_id = {unit.id: unit for unit in units}
    if len(by_id) != len(units):
        raise InvalidHandoffReference("unit ids must be unique")
    source_ids = {source.id for source in document.sources}
    for unit in units:
        for source_id in unit.source_ids:
            if source_id not in source_ids:
                raise InvalidHandoffReference(f"unknown source reference: {source_id}")
    result = []
    diagnostics = [diagnostic_dict(item) for item in document.diagnostics]
    counter = counter_for(config)
    for unit in units:
        if len(unit.source_ids) > 1:
            diagnostics.append({"code": "MULTI_SOURCE_UNIT", "unit_id": unit.id, "message": "unit references multiple sources"})
        if unit.parent_id is not None and unit.parent_id not in by_id:
            raise InvalidHandoffReference(f"unknown parent reference: {unit.parent_id}")
    for group in groups(units, config):
        if is_protected(group):
            result.append(_protected_chunk(document, group, config, len(result), counter))
            continue
        strategy = selected_strategy(group, config, structure_path)
        result.extend(fixed_group(document, group, config, len(result), counter, strategy, lambda group, text, order, strategy, diagnostics, span_hint: _make_chunk(document, group, text, order, config, counter, strategy, diagnostics, span_hint)))
    if config.parent_child:
        result = add_parent_child(document, result, config, counter)
    return result, diagnostics


def _protected_chunk(document, group, config, order, counter):
    text = protected_text(group)
    diagnostics = []
    if counter(text) > config.size:
        diagnostics.append({"code": "PROTECTED_UNIT_OVER_BUDGET", "message": "protected unit was kept intact"})
    return _make_chunk(document, group, text, order, config, counter, "protected", diagnostics)


def _make_chunk(document, group, text, order, config, counter, strategy, diagnostics, span_hint=None):
    """构造一个不可变结果，并在返回前校验 exact 来源追踪信息。"""
    span = None
    alignment = "unmapped"
    body = document.body
    verified = verified_body_range(document, group)
    if verified is not None:
        lo, hi = span_hint or verified
        if 0 <= lo <= hi <= len(body) and body[lo:hi] == text:
            span = (lo, hi)
            alignment = "exact"
        else:
            diagnostics = list(diagnostics) + [{"code": "SPAN_NOT_CONTIGUOUS", "message": "emitted text is not verified by the body span"}]
    path = structure_path(group)
    if config.context_projection and path:
        text = " > ".join(path) + "\n" + text
        if alignment == "exact":
            alignment = "document"
            span = None
            diagnostics = list(diagnostics) + [{"code": "CONTEXT_PROJECTED", "message": "projected context is not part of the exact body span"}]
    return Chunk(
        chunk_id=f"chunk-{document.id}-{order + 1}",
        document_id=document.id,
        business_id=document.business_id,
        version=document.version,
        text=text,
        order=order,
        unit_ids=tuple(unit.id for unit in group),
        source_ids=tuple(dict.fromkeys(source for unit in group for source in unit.source_ids)),
        structure_path=path,
        alignment=alignment,
        body_span=span,
        strategy=strategy,
        count_mode=config.count_mode,
        count=counter(text),
        diagnostics=tuple(diagnostics),
        requires_review=bool(diagnostics) or document.requires_review,
        projected_context=config.context_projection and bool(path),
    )


# 为偏好显式接口名称的调用方保留别名。
chunk_documents_result = chunk_documents
