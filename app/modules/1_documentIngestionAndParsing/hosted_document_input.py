"""Prepare a hosted upload without interpreting service artifacts."""

from dataclasses import dataclass, field
from importlib import import_module


HTML_FORMATS = ("html", "htm", "mhtml", "mht")


@dataclass(frozen=True)
class PreparedInput:
    data: bytes
    filename: str
    main_html: dict | None = None
    warnings: list[str] = field(default_factory=list)


def prepare_input(data: bytes, *, format: str) -> PreparedInput:
    """整份文档原样上传；MHTML 仅上传选中的主 HTML，并保留真实选择信息。"""
    filename = "document.html" if format in HTML_FORMATS else f"document.{format}"
    if format not in ("mhtml", "mht"):
        return PreparedInput(data, filename)
    selector = import_module(".2_textAndWebContent.mhtml", __package__)
    text, encoding, warnings, selected = selector.select_mhtml_html(data)
    return PreparedInput(text.encode(encoding), filename,
                         selected | {"encoding": encoding}, warnings)
