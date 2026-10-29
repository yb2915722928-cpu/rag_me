from dataclasses import asdict
from importlib import import_module

from .diagnostics import _upstream_diagnostics
from .models import ContentUnit, Document, HandoffReport, IdAllocator, Source


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
    document.diagnostics = _upstream_diagnostics(result, document_id, source.id)
    return HandoffReport(status, documents=[document])
