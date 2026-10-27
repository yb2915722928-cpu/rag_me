from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Source:
    location: str
    format: str | None = None


@dataclass
class ContentSource:
    """正文区间采用字符串切片；PDF 页序与 DOCX 章节/正文块位置分别表达，均非印刷页码。"""

    markdown_start: int
    markdown_end: int
    pdf_page_number: int | None
    extraction_method: str
    section_path: tuple[str, ...] = ()
    body_block_number: int | None = None
    section_block_number: int | None = None
    block_type: str | None = None
    heading_level: int | None = None


@dataclass
class ConversionResult:
    markdown: str | None
    source: Source
    sources: list[ContentSource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.markdown is not None and self.error is None


def convert_file(path, *, format=None, source=None, mineru=None) -> ConversionResult:
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
    return _convert_content(data, source_info, mineru)


def convert_bytes(data, *, format, source, mineru=None) -> ConversionResult:
    source_info = Source(str(source))
    try:
        source_info = _validate_options(format, source)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except ValueError as exc:
        return ConversionResult(None, source_info, error=str(exc))
    return _convert_content(data, source_info, mineru)


def _convert_content(data: bytes, source: Source, mineru=None) -> ConversionResult:
    if mineru is not None and not isinstance(mineru, MinerUConfig):
        return ConversionResult(None, source, error="mineru must be a MinerUConfig")
    if source.format == "docx":
        from .docx import extract_docx

        return extract_docx(data, source)
    from .pdf import extract_pdf

    return extract_pdf(data, source, mineru)


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
