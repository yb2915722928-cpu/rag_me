from pathlib import Path
from zipfile import BadZipFile
from zlib import error as ZlibError

from pptx.exc import InvalidXmlError

from ..exports import export_markdown
from .models import ContentSource, ConversionResult, ReviewIssue, Source


def convert_file(path, *, format=None, source=None, encoding=None) -> ConversionResult:
    """按后缀选择格式；显式 format 可覆盖后缀，encoding 只用于 JSON/XML。"""
    source_info = Source(str(path) if source is None else str(source))
    try:
        path = Path(path)
        source_info = _validate_options(
            path.suffix if format is None else format,
            str(path) if source is None else source, encoding,
        )
    except (TypeError, ValueError) as exc:
        return ConversionResult(None, source_info, error=f"Invalid path or options: {exc}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ConversionResult(None, source_info, error=f"Could not read '{path}': {exc}")
    return _convert_content(data, source_info, encoding)


def convert_bytes(data, *, format, source, encoding=None) -> ConversionResult:
    """字节入口明确指定格式和来源；与文件入口共用转换和失败语义。"""
    source_info = Source(str(source))
    try:
        source_info = _validate_options(format, source, encoding)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except ValueError as exc:
        return ConversionResult(None, source_info, error=str(exc))
    return _convert_content(data, source_info, encoding)


def _convert_content(data, source, encoding):
    if source.format != "pptx":
        from .structured import convert_structured

        return convert_structured(data, source, encoding)
    from .pptx_content import extract_pptx

    try:
        return extract_pptx(data, source)
    except (ValueError, OSError, BadZipFile, ZlibError, KeyError, IndexError, AttributeError, SyntaxError, InvalidXmlError) as exc:
        return ConversionResult(None, source, error=f"PPTX reading failed: {exc}")


def _validate_options(format, source, encoding):
    if not isinstance(format, str) or not format.strip():
        raise ValueError("format must be a nonempty string")
    input_format = format.strip().lower().lstrip(".")
    if input_format not in ("pptx", "json", "xml"):
        raise ValueError(f"Unsupported format: {input_format}")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a nonempty string")
    if encoding is not None:
        if not isinstance(encoding, str) or not encoding.strip():
            raise ValueError("encoding must be a nonempty string or None")
        if input_format == "pptx":
            raise ValueError("encoding is only supported for JSON/XML")
    return Source(source, input_format)
