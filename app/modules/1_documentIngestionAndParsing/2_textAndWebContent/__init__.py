from dataclasses import dataclass, field, replace
from pathlib import Path

from .decoding import decode_bytes
from .html_conversion import html_encoding_declarations, html_to_markdown
from .json_content import convert_json
from .markdown import normalize_markdown
from .mhtml import select_mhtml_html


@dataclass
class Source:
    location: str
    format: str | None = None
    encoding: str | None = None
    content_id: str | None = None
    content_location: str | None = None
    mime_index: int | None = None


@dataclass
class ConversionResult:
    markdown: str | None
    source: Source
    encoding: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.markdown is not None and self.error is None


def convert_file(
    path, *, format=None, source=None, encoding=None, mode="article"
) -> ConversionResult:
    source_info = source if isinstance(source, Source) else Source(
        str(path) if source is None else str(source)
    )
    try:
        path = Path(path)
        source_info = _validate_options(
            path.suffix if format is None else format,
            str(path) if source is None else source,
            encoding,
            mode,
        )
    except (TypeError, ValueError) as exc:
        return ConversionResult(
            markdown=None, source=source_info, error=f"Invalid path or options: {exc}"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ConversionResult(
            markdown=None, source=source_info, error=f"Could not read '{path}': {exc}"
        )
    return _convert_content(data, source_info, encoding, mode)


def convert_bytes(
    data, *, format, source, encoding=None, mode="article"
) -> ConversionResult:
    source_info = source if isinstance(source, Source) else Source(str(source))
    try:
        source_info = _validate_options(format, source, encoding, mode)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except ValueError as exc:
        return ConversionResult(markdown=None, source=source_info, error=str(exc))
    return _convert_content(data, source_info, encoding, mode)


def export_markdown(result: ConversionResult, path) -> Path:
    if not result.success:
        raise ValueError(f"Cannot export failed conversion: {result.error}")
    path = Path(path)
    path.write_bytes(result.markdown.encode("utf-8"))
    return path


def _convert_content(data: bytes, source_info: Source, encoding: str | None, mode: str):
    if source_info.format in ("mht", "mhtml"):
        return _convert_mhtml(data, source_info, encoding, mode)
    declarations = (
        html_encoding_declarations(data) if source_info.format in ("html", "htm") else ()
    )
    try:
        text, used_encoding, warnings = decode_bytes(data, encoding, declarations)
    except (UnicodeError, LookupError) as exc:
        return ConversionResult(
            markdown=None, source=source_info, error=f"Decoding failed: {exc}"
        )
    if source_info.format != "json" and not text.strip():
        return ConversionResult(
            markdown=None,
            source=source_info,
            encoding=used_encoding,
            warnings=warnings,
            error="No usable text body",
        )
    try:
        if source_info.format in ("html", "htm"):
            markdown = html_to_markdown(text, mode)
        elif source_info.format == "json":
            markdown = convert_json(text)
        elif source_info.format in ("md", "markdown"):
            markdown = normalize_markdown(text)
        else:
            markdown = text.replace("\r\n", "\n").replace("\r", "\n")
    except ValueError as exc:
        return ConversionResult(
            markdown=None,
            source=source_info,
            encoding=used_encoding,
            warnings=warnings,
            error=f"Invalid JSON: {exc}" if source_info.format == "json" else str(exc),
        )
    return ConversionResult(
        markdown=markdown,
        source=source_info,
        encoding=used_encoding,
        warnings=warnings,
    )


def _convert_mhtml(data, source_info, encoding, mode):
    try:
        text, used_encoding, warnings, selected = select_mhtml_html(data, encoding)
    except (ValueError, LookupError) as exc:
        return ConversionResult(
            markdown=None, source=source_info,
            error=f"MHTML decoding failed: {str(exc) or type(exc).__name__}",
        )
    source_info = replace(source_info, encoding=used_encoding, **selected)
    try:
        markdown = html_to_markdown(text, mode)
    except ValueError as exc:
        return ConversionResult(
            markdown=None, source=source_info, encoding=used_encoding,
            warnings=warnings, error=str(exc),
        )
    return ConversionResult(
        markdown=markdown, source=source_info, encoding=used_encoding, warnings=warnings
    )


def _validate_options(format, source, encoding, mode):
    if not isinstance(format, str) or not format.strip():
        raise ValueError("format must be a nonempty string")
    input_format = format.strip().lower().lstrip(".")
    if input_format not in ("txt", "md", "markdown", "json", "html", "htm", "mht", "mhtml"):
        raise ValueError(f"Unsupported format: {input_format}")
    if not isinstance(source, (str, Source)):
        raise ValueError("source must be a nonempty string or Source")
    source_info = source if isinstance(source, Source) else Source(source)
    if not isinstance(source_info.location, str) or not source_info.location.strip():
        raise ValueError("source location must be a nonempty string")
    if encoding is not None and (not isinstance(encoding, str) or not encoding.strip()):
        raise ValueError("encoding must be a nonempty string or None")
    if mode not in ("article", "full"):
        raise ValueError("mode must be 'article' or 'full'")
    return replace(source_info, format=input_format)
