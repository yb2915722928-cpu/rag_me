"""Static native-result dispatch and handoff orchestration."""

from ..identity import validate_identity
from .models import HandoffReport, IdAllocator
from .text_web import TextWebResult, adapt_text_web
from .documents import HostedDocumentResult, PdfWordResult, adapt_hosted_document, adapt_pdf_word
from .tables import TableResult, adapt_tables
from .derived import ImageResult, MediaResult, adapt_image, adapt_media
from .structured import StructuredResult, adapt_structured
from .zip_container import ZipResult, adapt_zip


def adapt_result(
    result: (
        TextWebResult | PdfWordResult | HostedDocumentResult | TableResult
        | StructuredResult | ImageResult | MediaResult | ZipResult
    ), *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """只适配明确支持的原生结果，不读取文件、不重新解析或调用模型。"""
    validate_identity(business_id, version)
    return adapt_validated_result(result, business_id=business_id, version=version)


def adapt_validated_result(result, *, business_id=None, version=None) -> HandoffReport:
    """接入入口已在解析前校验身份；每份报告只建立一个标识分配器。"""
    return _adapt_result(result, IdAllocator(), business_id=business_id, version=version)


def _adapt_result(result, ids: IdAllocator, *, business_id=None, version=None) -> HandoffReport:
    """容器成员复用静态分派与同一个分配器，业务身份只属于当前输入。"""
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
        return adapt_zip(result, ids, adapt_member=_adapt_result,
                         business_id=business_id, version=version)
    raise TypeError(f"Unsupported result type: {type(result).__name__}")
