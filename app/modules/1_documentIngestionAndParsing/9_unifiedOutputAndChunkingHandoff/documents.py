from dataclasses import asdict
from importlib import import_module

from ..hosted_documents import DocumentResult as HostedDocumentResult
from .diagnostics import _upstream_diagnostics
from .hosted_documents import adapt_hosted_document
from .models import (
    BodySpan, ContentUnit, Document, HandoffReport, IdAllocator, Source,
)


PdfWordResult = import_module("..3_pdfAndWordParsing.models", __package__).ConversionResult


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
