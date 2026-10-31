from dataclasses import asdict
from importlib import import_module

from ..hosted_documents import DocumentResult as HostedDocumentResult
from .diagnostics import _upstream_diagnostics
from .models import (
    BodySpan, ContentUnit, Diagnostic, Document, HandoffReport, IdAllocator, Source,
)


PdfWordResult = import_module("..pdfAndDocxExtraction.models", __package__).ConversionResult


def adapt_pdf_word(
    result: PdfWordResult, ids: IdAllocator, *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """保留完整原 Markdown；来源未覆盖的分隔符仍留在正文中。"""
    status = "success" if result.success else "failed"
    origin = Source(ids.new_id("source"), "document", asdict(result.source))
    document = Document(
        ids.new_id("document"), result.markdown if result.success else None, "markdown", status,
        business_id=business_id, version=version, sources=[origin],
        structure={"sources": [asdict(source) for source in result.sources]},
    )
    if result.success:
        for native_source in result.sources:
            kind = "pdf_page" if native_source.pdf_page_number is not None else "docx_block"
            source = Source(ids.new_id("source"), kind,
                            asdict(result.source) | asdict(native_source))
            document.sources.append(source)
            document.units.append(ContentUnit(
                ids.new_id("unit"), native_source.block_type or kind,
                result.markdown[native_source.markdown_start:native_source.markdown_end],
                source_ids=[source.id],
                body_span=BodySpan(native_source.markdown_start, native_source.markdown_end),
                alignment="exact",
            ))
    document.diagnostics = _upstream_diagnostics(result, document.id, origin.id)
    return HandoffReport(status, documents=[document])


def adapt_hosted_document(
    result: HostedDocumentResult, ids: IdAllocator, *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """服务块只关联原产物位置；与 Markdown 的字符映射保持未知。"""
    native = asdict(result)
    status = "success" if result.success else "failed"
    origin = Source(ids.new_id("source"), "document", {"location": result.source, "format": result.format})
    document = Document(
        ids.new_id("document"), result.markdown if result.success else None, "markdown", status,
        business_id=business_id, version=version, sources=[origin],
        structure={name: native[name] for name in (
            "structured_json", "sources", "artifacts", "markdown_file", "content_list_file",
            "html", "html_file",
        )},
        metadata={"provider": result.provider, "requested_model": result.requested_model,
                  "review_items": native["review_items"], "main_html": native["main_html"]},
        requires_review=result.requires_review,
    )
    if result.success:
        document.units.append(ContentUnit(
            ids.new_id("unit"), "document", result.markdown,
            source_ids=[origin.id], alignment="document",
        ))
        for native_source in native["sources"]:
            source = Source(ids.new_id("source"), "service_block", origin.locator | native_source)
            document.sources.append(source)
            document.units.append(ContentUnit(
                ids.new_id("unit"), "service_block", None, source_ids=[source.id],
            ))
    document.diagnostics = _upstream_diagnostics(result, document.id, origin.id) + [
        Diagnostic("warning", "upstream_review", message,
                   document_id=document.id, source_id=origin.id)
        for message in result.review_items
    ]
    return HandoffReport(status, documents=[document])
