import json
from pathlib import Path

from .models import (
    BodySpan, ContentUnit, Diagnostic, Document, HandoffReport, IdAllocator, Source,
)
from .text_web import TextWebResult, adapt_text_web
from .tables import TableResult, adapt_tables
from .structured import StructuredResult, adapt_structured

__all__ = [
    "adapt_result", "export_json", "BodySpan", "ContentUnit", "Diagnostic",
    "Document", "HandoffReport", "IdAllocator", "Source",
]


def adapt_result(
    result: TextWebResult | TableResult | StructuredResult, *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """只适配明确支持的原生结果，不读取文件、不重新解析或调用模型。"""
    _validate_identity(business_id, version)
    if isinstance(result, TextWebResult):
        return adapt_text_web(result, IdAllocator(), business_id=business_id, version=version)
    if isinstance(result, TableResult):
        return adapt_tables(result, IdAllocator(), business_id=business_id, version=version)
    if isinstance(result, StructuredResult):
        return adapt_structured(result, IdAllocator(), business_id=business_id, version=version)
    raise TypeError(f"Unsupported result type: {type(result).__name__}")


def _validate_identity(business_id, version):
    for name, value in (("business_id", business_id), ("version", version)):
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a nonempty string or None")
        if not value.strip():
            raise ValueError(f"{name} must be a nonempty string or None")


def export_json(report: HandoffReport, path) -> Path:
    """包括失败报告在内均可导出；写入异常按普通 I/O 错误向调用方传播。"""
    data = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    path = Path(path)
    path.write_bytes((data + "\n").encode("utf-8"))
    return path
