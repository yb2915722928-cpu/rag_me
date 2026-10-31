"""Nominal native-result dispatch without initializing unrelated parsers."""
from __future__ import annotations

from importlib import import_module
import sys

from ..identity import validate_identity
from .models import HandoffReport, IdAllocator


_PARSER_PACKAGE = __package__.rsplit(".", 1)[0]
# Keep the original isinstance precedence, including multiple-inheritance results.
# Native results already have their defining module loaded; importing a model leaf
# here would also execute its parser's initializer and load unrelated dependencies.
_NATIVE_RESULTS = (
    ("TextWebResult", "2_textAndWebContent", "ConversionResult", "text_web", "adapt_text_web"),
    ("PdfWordResult", "pdfAndDocxExtraction.models", "ConversionResult", "documents", "adapt_pdf_word"),
    ("HostedDocumentResult", "hosted_documents", "DocumentResult", "hosted_documents", "adapt_hosted_document"),
    ("TableResult", "4_tabularFileProcessing.models", "ConversionResult", "tables", "adapt_tables"),
    ("StructuredResult", "5_presentationsAndStructuredDocuments.models", "ConversionResult", "structured", "adapt_structured"),
    ("ImageResult", "6_imageProcessing.models", "ConversionResult", "derived", "adapt_image"),
    ("MediaResult", "audioTranscriptionAndVideoUnderstanding.models", "ConversionResult", "derived", "adapt_media"),
    ("ZipResult", "8_zipContainers.models", "ZipResult", "zip_container", "adapt_zip"),
)


def __getattr__(name):
    """Resolve existing explicit type/adapter imports only when callers ask for them."""
    for alias, native_module, native_name, adapter_module, adapter_name in _NATIVE_RESULTS:
        if name == alias:
            return getattr(import_module(".." + native_module, __package__), native_name)
        if name == adapter_name:
            return getattr(import_module("." + adapter_module, __package__), adapter_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    for alias, native_module, native_name, adapter_module, adapter_name in _NATIVE_RESULTS:
        module = sys.modules.get(_PARSER_PACKAGE + "." + native_module)
        if module is None or not isinstance(result, getattr(module, native_name)):
            continue
        adapter = getattr(import_module("." + adapter_module, __package__), adapter_name)
        if alias == "ZipResult":
            return adapter(result, ids, adapt_member=_adapt_result,
                           business_id=business_id, version=version)
        return adapter(result, ids, business_id=business_id, version=version)
    raise TypeError(f"Unsupported result type: {type(result).__name__}")
