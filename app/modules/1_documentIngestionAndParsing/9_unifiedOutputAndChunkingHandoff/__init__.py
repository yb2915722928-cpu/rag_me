from ..exports import export_json

from .models import (
    BodySpan, ContentUnit, Diagnostic, Document, HandoffReport, IdAllocator, Source,
)
from .text_web import TextWebResult, adapt_text_web
from .documents import HostedDocumentResult, PdfWordResult, adapt_hosted_document, adapt_pdf_word
from .tables import TableResult, adapt_tables
from .derived import ImageResult, MediaResult, adapt_image, adapt_media
from .structured import StructuredResult, adapt_structured
from .zip_container import ZipResult, adapt_zip

__all__ = [
    "adapt_result", "export_json", "BodySpan", "ContentUnit", "Diagnostic",
    "Document", "HandoffReport", "IdAllocator", "Source",
]


def adapt_result(
    result: (
        TextWebResult | PdfWordResult | HostedDocumentResult | TableResult
        | StructuredResult | ImageResult | MediaResult | ZipResult
    ), *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """只适配明确支持的原生结果，不读取文件、不重新解析或调用模型。"""
    _validate_identity(business_id, version)
    return _adapt_result(result, IdAllocator(), business_id=business_id, version=version)


def _adapt_result(result, ids: IdAllocator, *, business_id=None, version=None) -> HandoffReport:
    """容器成员复用静态分派与同一个分配器，业务参数只在公开入口校验。"""
    if isinstance(result, TextWebResult):
        return adapt_text_web(result, ids, business_id=business_id, version=version)
    if isinstance(result, PdfWordResult):
        return adapt_pdf_word(result, ids, business_id=business_id, version=version)
    if isinstance(result, HostedDocumentResult):
        return adapt_hosted_document(result, ids, business_id=business_id, version=version)
    if isinstance(result, TableResult):
        return adapt_tables(result, ids, business_id=business_id, version=version)
    if isinstance(result, StructuredResult):
        return adapt_structured(result, ids, business_id=business_id, version=version)
    if isinstance(result, ImageResult):
        return adapt_image(result, ids, business_id=business_id, version=version)
    if isinstance(result, MediaResult):
        return adapt_media(result, ids, business_id=business_id, version=version)
    if isinstance(result, ZipResult):
        return adapt_zip(result, ids, business_id=business_id, version=version)
    raise TypeError(f"Unsupported result type: {type(result).__name__}")


def _validate_identity(business_id, version):
    for name, value in (("business_id", business_id), ("version", version)):
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a nonempty string or None")
        if not value.strip():
            raise ValueError(f"{name} must be a nonempty string or None")
