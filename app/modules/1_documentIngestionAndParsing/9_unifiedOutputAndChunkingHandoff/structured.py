from dataclasses import asdict
from importlib import import_module

from .models import (
    BodySpan, ContentUnit, Diagnostic, Document, HandoffReport, IdAllocator, Source,
)


StructuredResult = import_module(
    "..5_presentationsAndStructuredDocuments", __package__,
).ConversionResult


def adapt_structured(
    result: StructuredResult, ids: IdAllocator, *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """节点定位独立于正文；只使用上游已提供的结构和关系，不重新解析。"""
    status = "success" if result.success else "failed"
    sources = [Source(ids.new_id("source"), "document", asdict(result.source))]
    sources.extend(
        Source(ids.new_id("source"), source.kind, asdict(source))
        for source in result.sources
    )
    document = Document(
        ids.new_id("document"), result.markdown if result.success else None,
        "markdown", status, business_id=business_id, version=version,
        sources=sources, metadata={"encoding": result.encoding},
        structure={
            "sources": [asdict(source) for source in result.sources],
            "review_issues": [asdict(issue) for issue in result.review_issues],
        },
        requires_review=result.requires_review,
    )
    if result.success:
        document.units = _content_units(result, sources[1:], ids)
    document.diagnostics = _diagnostics(result, document)
    return HandoffReport(status, documents=[document])


def _content_units(result, sources, ids):
    units = [
        ContentUnit(ids.new_id("unit"), source.kind, None, source_ids=[source.id])
        for source in sources
    ]
    nodes = {
        source.node_path: unit.id
        for source, unit in zip(result.sources, units)
        if source.node_path is not None
    }
    for source, unit in zip(result.sources, units):
        unit.parent_id = nodes.get(source.parent_path)
        if source.markdown_start is not None:
            unit.body_span = BodySpan(source.markdown_start, source.markdown_end)
            unit.text = result.markdown[source.markdown_start:source.markdown_end]
            unit.alignment = "exact"
    return units


def _diagnostics(result, document):
    diagnostics = [
        Diagnostic("warning", "upstream_warning", message,
                   document_id=document.id, source_id=document.sources[0].id)
        for message in result.warnings
    ]
    if result.error is not None:
        diagnostics.append(Diagnostic(
            "error", "upstream_error", result.error,
            document_id=document.id, source_id=document.sources[0].id,
        ))
    for issue in result.review_issues:
        index = result.sources.index(issue.source)
        diagnostics.append(Diagnostic(
            "review", issue.code, issue.message, document_id=document.id,
            unit_id=document.units[index].id, source_id=document.sources[index + 1].id,
        ))
    return diagnostics
