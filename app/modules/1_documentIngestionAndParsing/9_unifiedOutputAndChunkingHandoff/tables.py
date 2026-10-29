from dataclasses import asdict
from importlib import import_module

from .models import ContentUnit, Diagnostic, Document, HandoffReport, IdAllocator, Source


TableResult = import_module("..4_tabularFileProcessing", __package__).ConversionResult


def adapt_tables(
    result: TableResult, ids: IdAllocator, *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """复用上游行文字；原生行列来源不代表 Markdown 字符位置。"""
    document_id = ids.new_id("document")
    source = Source(ids.new_id("source"), "document", asdict(result.source))
    status = "success" if result.success else "failed"
    document = Document(
        document_id, result.markdown if result.success else None, "markdown", status,
        business_id=business_id, version=version,
        sources=[source], metadata={"encoding": result.encoding},
        structure={"tables": [asdict(table) for table in result.tables]},
    )
    if result.success:
        for table_index, table in enumerate(result.tables):
            for row_index, row in enumerate(table.rows):
                row_source = Source(ids.new_id("source"), "table_row", asdict(row.source))
                document.sources.append(row_source)
                document.units.append(ContentUnit(
                    ids.new_id("unit"), "table_row", row.text,
                    source_ids=[row_source.id],
                    metadata={"table_index": table_index, "row_index": row_index},
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
