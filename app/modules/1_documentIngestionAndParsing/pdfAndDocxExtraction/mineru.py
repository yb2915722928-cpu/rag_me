from dataclasses import replace
from io import BytesIO
import json
import os
import re
from zipfile import BadZipFile, ZipFile

from ..mineru_client import MinerUClient as _MinerUClient, MinerUConfig, MinerUError, _http_url
from .models import ContentSource, ConversionResult, Source


class MinerUClient(_MinerUClient):
    """Legacy PDF client; document transport is shared with hosted parsing."""

    def extract(self, data: bytes, page_count: int) -> list[dict]:
        archive = self.extract_document(data, filename="document.pdf", is_ocr=True)
        return _read_content_list(archive, page_count)


def extract_scanned_pdf(data: bytes, source: Source, page_numbers: list[int],
                        config: MinerUConfig | None) -> ConversionResult:
    """page_numbers 按上传页序列出原 PDF 页序；API page_idx 是其中的零基索引。"""
    page_count = len(page_numbers)
    original_pages = ", ".join(map(str, page_numbers))
    config = config or MinerUConfig()
    token = config.token if config.token is not None else os.environ.get("MINERU_API_TOKEN")
    if not token:
        return ConversionResult(
            None, source,
            warnings=[f"PDF page {p}: OCR unavailable" for p in page_numbers],
            error=f"OCR unavailable for PDF pages {original_pages}: set MINERU_API_TOKEN "
                  "or MinerUConfig.token",
        )
    config = replace(config, token=token)
    try:
        blocks = MinerUClient(config).extract(data, page_count)
    except MinerUError as exc:
        message = re.sub(r"https?://\S+", "[redacted URL]", str(exc).replace(token, "[redacted]"))
        return ConversionResult(None, source,
                                error=f"OCR failed for PDF pages {original_pages}: {message}")
    pages = {}
    warnings = []
    for block in blocks:
        text = _block_markdown(block).strip()
        if block["type"] == "table" and "<table" not in text.lower():
            warnings.append(
                f"PDF page {page_numbers[block['page_idx']]}: table relationships were not recovered"
            )
        if text:
            pages.setdefault(block["page_idx"], []).append(text)
    missing = [number for index, number in enumerate(page_numbers) if index not in pages]
    if missing:
        return ConversionResult(None, source, warnings=warnings, error=(
            "No usable OCR body for " + ", ".join(f"PDF page {p}" for p in missing)
        ))
    markdown = ""
    sources = []
    for page_idx, texts in sorted(pages.items()):
        if markdown:
            markdown += "\n"
        start = len(markdown)
        markdown += "\n\n".join(texts) + "\n"
        sources.append(ContentSource(start, len(markdown), page_numbers[page_idx], "mineru_api"))
    return ConversionResult(markdown, source, sources, warnings)


def _block_markdown(block: dict) -> str:
    if block["type"] == "list":
        return "\n".join(block.get("list_items", []))
    if block["type"] == "table":
        parts = (block.get("table_caption", []) + [block.get("table_body", "")]
                 + block.get("table_footnote", []))
        return "\n\n".join(part for part in parts if part.strip())
    text = block.get("text", "")
    level = block.get("text_level", 0)
    return "#" * level + " " + text if level else text


def _read_content_list(archive: bytes, page_count: int) -> list[dict]:
    """使用云端旧版内容列表定位页序；随机前缀和 V2 文件不是同一个协议。"""
    try:
        with ZipFile(BytesIO(archive)) as zipped:
            names = [n for n in zipped.namelist() if n.endswith("_content_list.json")
                     or n.rsplit("/", 1)[-1] == "content_list.json"]
            if len(names) != 1:
                raise MinerUError("MinerU ZIP must contain one content_list.json")
            blocks = json.loads(zipped.read(names[0]).decode("utf-8-sig"))
    except (BadZipFile, ValueError, UnicodeError):
        raise MinerUError("MinerU ZIP or content_list JSON is invalid") from None
    if not isinstance(blocks, list):
        raise MinerUError("MinerU content_list must be an array")
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str):
            raise MinerUError("MinerU content_list contains an invalid block")
        index = block.get("page_idx")
        if type(index) is not int or not 0 <= index < page_count:
            raise MinerUError("MinerU content_list page_idx is missing or outside the uploaded PDF")
        for key in ("text", "table_body"):
            if key in block and not isinstance(block[key], str):
                raise MinerUError(f"MinerU content_list {key} must be a string")
        for key in ("list_items", "table_caption", "table_footnote"):
            if key in block and (not isinstance(block[key], list)
                                 or any(not isinstance(item, str) for item in block[key])):
                raise MinerUError(f"MinerU content_list {key} must be an array of strings")
        level = block.get("text_level", 0)
        if type(level) is not int or not 0 <= level <= 6:
            raise MinerUError("MinerU content_list text_level must be an integer from 0 to 6")
    return blocks
