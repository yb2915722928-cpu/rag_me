"""文件或字节 → 格式解析 → 统一输出与切分交接。"""

from importlib import import_module
import json
from pathlib import Path


__all__ = ["convert_file", "convert_bytes", "export_json"]

_PARSERS = {
    format: module
    for module, formats in (
        ("2_textAndWebContent", ("txt", "md", "markdown", "html", "htm", "mhtml", "mht")),
        ("3_pdfAndWordParsing", ("pdf", "docx")),
        ("4_tabularFileProcessing", ("csv", "xlsx")),
        ("5_presentationsAndStructuredDocuments", ("pptx", "json", "xml")),
        ("6_imageProcessing", ("png", "jpg", "jpeg", "webp")),
        ("7_audioAndVideoProcessing", ("wav", "mp3", "m4a", "ogg", "flac", "mp4", "mov", "mkv")),
        ("8_zipContainers", ("zip",)),
    )
    for format in formats
}


def convert_file(path, *, format=None, source=None, business_id=None, version=None, **options):
    """按后缀或显式格式解析并返回 HandoffReport；options 沿用所选解析器的选项。

    格式、路径类型及业务身份错误在读取前抛出；读取和解析失败保留在报告中。
    文件直接交给原文件入口，避免把媒体和 ZIP 额外整份读入内存。
    """
    return _convert(
        "convert_file", path, format, source, business_id, version, options,
    )


def convert_bytes(data, *, format, source, business_id=None, version=None, **options):
    """字节必须明确格式与来源；JSON 使用保留节点路径的结构化解析器。

    ZIP 保留整包状态与成员清单，业务身份仅属于容器，不继承到成员文档。
    图片和媒体仍须通过 options 明确选择 task。
    """
    return _convert(
        "convert_bytes", data, format, source, business_id, version, options,
    )


def export_json(report, path) -> Path:
    """包括失败报告在内均可导出；写入异常按普通 I/O 错误向调用方传播。"""
    data = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    path = Path(path)
    path.write_bytes((data + "\n").encode("utf-8"))
    return path


def _convert(entry, value, format, source, business_id, version, options):
    """业务身份先于解析校验；内部交接复用已校验分派，避免重复校验或重新解析。"""
    if entry == "convert_file":
        value = Path(value)
        if format is None:
            format = value.suffix
    parser, format = _parser(format)
    handoff = import_module(".9_unifiedOutputAndChunkingHandoff", __name__)
    handoff._validate_identity(business_id, version)
    if format != "zip":
        options["format"] = format
    native = getattr(parser, entry)(value, source=source, **options)
    return handoff._adapt_result(
        native, handoff.IdAllocator(), business_id=business_id, version=version,
    )


def _parser(format):
    if not isinstance(format, str) or not format.strip():
        raise ValueError("format must be a nonempty string")
    format = format.strip().lower().lstrip(".")
    module = _PARSERS.get(format)
    if module is None:
        raise ValueError(f"Unsupported format: {format}")
    return import_module("." + module, __name__), format
