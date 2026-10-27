from dataclasses import dataclass, field, replace
from pathlib import Path

from .decoding import decode_bytes
from .html_conversion import html_encoding_declarations, html_to_markdown
from .json_content import convert_json
from .markdown import normalize_markdown
from .mhtml import select_mhtml_html


@dataclass
class Source:
    """保留输入来源及实际选中的归档部分，不将这些信息拼入 Markdown 正文。

    mime_index 按 MIME 遍历顺序计数，归档根为 0；缺失的来源头保持为 None。
    """

    location: str
    format: str | None = None
    encoding: str | None = None
    content_id: str | None = None
    content_location: str | None = None
    mime_index: int | None = None


@dataclass
class ConversionResult:
    """失败时不提供正文，避免下游把错误提示当作可用文档继续处理。

    编码、警告和失败原因独立于正文，导出时只使用成功结果的正文。
    """

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
    """读取本地文件并转换整篇正文；省略格式时使用文件后缀。

    读取、解码及内容转换失败统一通过结果返回，不在本入口抓取网页或切块。
    """

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
    """处理调用方已取得的文件字节，格式和来源必须显式提供。

    外部参数在公共入口完成校验，随后与文件入口共用实际转换流程。
    """

    source_info = source if isinstance(source, Source) else Source(str(source))
    try:
        source_info = _validate_options(format, source, encoding, mode)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except ValueError as exc:
        return ConversionResult(markdown=None, source=source_info, error=str(exc))
    return _convert_content(data, source_info, encoding, mode)


def export_markdown(result: ConversionResult, path) -> Path:
    """仅导出成功正文，失败结果在创建或覆盖目标文件之前被拒绝。

    按 UTF-8 字节写入，避免 Windows 文本写入改写换行；写入错误正常抛出。
    """

    if not result.success:
        raise ValueError(f"Cannot export failed conversion: {result.error}")
    path = Path(path)
    path.write_bytes(result.markdown.encode("utf-8"))
    return path


def _convert_content(data: bytes, source_info: Source, encoding: str | None, mode: str):
    """MHTML 先进行 MIME 解包，其他格式先完成严格解码再转换正文。

    单独的 BOM 不算可用正文；JSON 的空输入交给解析器报告格式错误。
    所有诊断保存在结果字段中，不能成为成功正文的一部分。
    """

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
    if source_info.format != "json" and not text.removeprefix("\ufeff").strip():
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
    """先确定主 HTML 部分，再复用静态 HTML 转换。

    已选中且解码成功的部分即使没有正文，也保留来源和编码，便于回查失败原因。
    """

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
    """在公共入口规范化格式和选项，并生成携带实际格式的来源副本。

    不原地修改调用方传入的 Source，避免多次转换相互改写来源信息。
    """

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
