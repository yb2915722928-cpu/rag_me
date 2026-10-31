from pathlib import Path

from .models import ContentSource, ConversionResult, Source


def convert_file(path, *, format=None, source=None, mineru=None, ocr_pages=()) -> ConversionResult:
    """ocr_pages 使用从 1 开始的实际 PDF 页序，以 OCR 替换指定页的文本层结果。"""
    source_info = Source(str(path) if source is None else str(source))
    try:
        path = Path(path)
        source_info = _validate_options(
            path.suffix if format is None else format,
            str(path) if source is None else source,
        )
    except (TypeError, ValueError) as exc:
        return ConversionResult(None, source_info, error=f"Invalid path or options: {exc}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ConversionResult(None, source_info, error=f"Could not read '{path}': {exc}")
    return _convert_content(data, source_info, mineru, ocr_pages)


def convert_bytes(data, *, format, source, mineru=None, ocr_pages=()) -> ConversionResult:
    """ocr_pages 与文件入口相同，仅选择 PDF 页，不使用页面上印刷的页码。"""
    source_info = Source(str(source))
    try:
        source_info = _validate_options(format, source)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except ValueError as exc:
        return ConversionResult(None, source_info, error=str(exc))
    return _convert_content(data, source_info, mineru, ocr_pages)


def _convert_content(data: bytes, source: Source, mineru=None, ocr_pages=()) -> ConversionResult:
    if mineru is not None and not isinstance(mineru, MinerUConfig):
        return ConversionResult(None, source, error="mineru must be a MinerUConfig")
    if not isinstance(ocr_pages, tuple) or any(type(number) is not int for number in ocr_pages):
        return ConversionResult(None, source, error="ocr_pages must be a tuple of integers (1-based PDF pages)")
    if ocr_pages and source.format != "pdf":
        return ConversionResult(None, source, error="ocr_pages is only supported for PDF")
    if source.format == "docx":
        from .docx import extract_docx

        return extract_docx(data, source)
    from .pdf import extract_pdf

    return extract_pdf(data, source, mineru, ocr_pages)


def _validate_options(format, source) -> Source:
    if not isinstance(format, str) or not format.strip():
        raise ValueError("format must be a nonempty string")
    input_format = format.strip().lower().lstrip(".")
    if input_format not in {"pdf", "docx"}:
        raise ValueError(f"Unsupported format: {input_format}")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a nonempty string")
    return Source(source, input_format)


from .mineru import MinerUConfig
