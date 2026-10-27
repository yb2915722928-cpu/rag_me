from dataclasses import dataclass, field, replace
from http.client import HTTPConnection, HTTPSConnection, HTTPException
from io import BytesIO
import json
import os
import re
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

from . import ContentSource, ConversionResult, Source


@dataclass
class MinerUConfig:
    token: str | None = field(default=None, repr=False)
    api_base: str = "https://mineru.net/api/v4"
    language: str = "ch"
    poll_interval: float = 3
    request_timeout: float = 30
    max_wait: float = 300


class MinerUError(Exception):
    pass


class MinerUClient:
    def __init__(self, config: MinerUConfig):
        self.config = config

    def extract(self, data: bytes, page_count: int) -> list[dict]:
        headers = {"Authorization": f"Bearer {self.config.token}"}
        request = {
            "files": [{"name": "document.pdf", "is_ocr": True}],
            "model_version": "vlm", "language": self.config.language,
            "enable_table": True,
        }
        applied = self._json("/file-urls/batch", headers, request)
        self._upload(applied["file_urls"][0], data)
        deadline = time.monotonic() + self.config.max_wait
        while time.monotonic() < deadline:
            result = self._json(
                f"/extract-results/batch/{applied['batch_id']}", headers,
            )["extract_result"][0]
            if result["state"] == "failed":
                raise MinerUError(f"MinerU parsing failed: {result.get('err_msg', '')}")
            if result["state"] == "done":
                break
            time.sleep(min(self.config.poll_interval, max(0, deadline - time.monotonic())))
        else:
            raise MinerUError("MinerU polling timed out")
        archive = self._read(result["full_zip_url"])
        return _read_content_list(archive, page_count)

    def _json(self, endpoint, headers, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None:
            headers = headers | {"Content-Type": "application/json"}
        try:
            response = json.loads(self._read(self.config.api_base + endpoint, headers, data))
        except (ValueError, UnicodeError):
            raise MinerUError("MinerU returned invalid JSON") from None
        if not isinstance(response, dict) or "code" not in response:
            raise MinerUError("MinerU returned an invalid response envelope")
        if response["code"] != 0:
            raise MinerUError(f"MinerU API {response['code']}: {response.get('msg', '')}")
        result = response.get("data")
        if not isinstance(result, dict):
            raise MinerUError("MinerU response data must be an object")
        if endpoint == "/file-urls/batch":
            urls = result.get("file_urls")
            if (not isinstance(result.get("batch_id"), str)
                    or not isinstance(urls, list) or len(urls) != 1
                    or not isinstance(urls[0], str) or not _http_url(urls[0])):
                raise MinerUError("MinerU upload response requires batch_id and one file_urls entry")
        else:
            items = result.get("extract_result")
            if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
                raise MinerUError("MinerU poll response requires one extract_result entry")
            item = items[0]
            if item.get("state") not in {"waiting-file", "pending", "running", "converting", "done", "failed"}:
                raise MinerUError("MinerU returned an unknown task state")
            if item["state"] == "done" and not _http_url(item.get("full_zip_url")):
                raise MinerUError("MinerU completed response requires full_zip_url")
        return result

    def _read(self, url, headers=None, data=None, method=None):
        request = Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urlopen(request, timeout=self.config.request_timeout) as response:
                return response.read()
        except HTTPError as exc:
            raise MinerUError(f"MinerU request HTTP {exc.code}") from None
        except (URLError, OSError, HTTPException):
            raise MinerUError("MinerU network request failed or timed out") from None

    def _upload(self, url: str, data: bytes):
        """签名 PUT 不附带认证或 Content-Type；urllib 会自动添加表单类型，导致签名拒绝。"""
        parts = urlsplit(url)
        connection_type = HTTPSConnection if parts.scheme == "https" else HTTPConnection
        connection = connection_type(parts.hostname, parts.port, timeout=self.config.request_timeout)
        try:
            target = parts.path + ("?" + parts.query if parts.query else "")
            connection.request("PUT", target, body=data)
            response = connection.getresponse()
            if response.status != 200:
                raise MinerUError(f"MinerU upload HTTP {response.status}")
            response.read()
        except (OSError, HTTPException):
            raise MinerUError("MinerU upload failed or timed out") from None
        finally:
            connection.close()


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


def _http_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)
