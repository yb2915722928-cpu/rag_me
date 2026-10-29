from dataclasses import asdict
from importlib import import_module

from .models import ContentUnit, Diagnostic, Document, HandoffReport, IdAllocator, Source


TextWebResult = import_module("..2_textAndWebContent", __package__).ConversionResult


def adapt_text_web(
    result: TextWebResult, ids: IdAllocator, *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """整篇交接，不从 Markdown 猜测原文的章节、页码或字符位置。"""
    document_id = ids.new_id("document")
    source = Source(ids.new_id("source"), "document", asdict(result.source))
    status = "success" if result.success else "failed"
    document = Document(
        document_id, result.markdown if result.success else None, "markdown", status,
        business_id=business_id, version=version,
        sources=[source], metadata={"encoding": result.encoding},
    )
    if result.success:
        document.units.append(ContentUnit(
            ids.new_id("unit"), "document", result.markdown,
            source_ids=[source.id], alignment="document",
        ))
    document.diagnostics = [
        Diagnostic("warning", "upstream_warning", message,
                   document_id=document_id, source_id=source.id)
        for message in result.warnings
    ]
    if result.error is not None:
        document.diagnostics.append(Diagnostic(
            "error", "upstream_error", result.error,
            document_id=document_id, source_id=source.id,
        ))
    return HandoffReport(status, documents=[document])
