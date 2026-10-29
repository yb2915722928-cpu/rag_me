from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import partial
from importlib import import_module
from io import BytesIO
import json
import math
import os
import re
from zipfile import BadZipFile, ZipFile

from .archive_budget import ArchiveLimits, ArchiveProcessingStopped, check_deadline


_mineru = import_module(".3_pdfAndWordParsing.mineru", __package__)
MinerUConfig = _mineru.MinerUConfig


@dataclass(frozen=True)
class DocumentSource:
    """block_index 是服务产物内零基块序号；与原生正文块及 Markdown 偏移无映射。"""

    artifact: str
    block_index: int
    service_page_index: int | None
    pdf_page_number: int | None
    page_origin: str
    markdown_start: None = None
    markdown_end: None = None


@dataclass
class DocumentResult:
    source: str
    format: str
    provider: str = "mineru"
    requested_model: str = "vlm"
    markdown: str | None = None
    markdown_file: str | None = None
    structured_json: dict = field(default_factory=dict)
    content_list_file: str | None = None
    html: str | None = None
    html_file: str | None = None
    artifacts: list[str] = field(default_factory=list)
    sources: list[DocumentSource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review_items: list[str] = field(default_factory=list)
    main_html: dict | None = None
    error: str | None = None

    @property
    def success(self):
        return self.error is None and self.markdown is not None

    @property
    def requires_review(self):
        return bool(self.review_items)


def convert_bytes(data: bytes, *, format: str, source: str, limits: ArchiveLimits, deadline: float,
                  mineru: MinerUConfig | Mapping | None = None) -> DocumentResult:
    """沿用调用方给定的归档预算与绝对截止；远端失败不回退本地解析。"""
    html_input = format in ("html", "htm", "mhtml", "mht")
    model = "MinerU-HTML" if html_input else "vlm"
    result = DocumentResult(source, format, requested_model=model)
    try:
        config = _configuration(mineru)
    except ValueError as exc:
        result.error = f"Invalid document options: {exc}"
        return result
    token = config.token if config.token is not None else os.environ.get("MINERU_API_TOKEN")
    if not token:
        result.error = "MinerU unavailable: set MINERU_API_TOKEN or MinerUConfig.token"
        return result
    config = replace(config, token=token, max_wait=min(config.max_wait, limits.timeout_seconds),
                     request_timeout=min(config.request_timeout, limits.timeout_seconds))
    try:
        if format in ("mhtml", "mht"):
            selector = import_module(".2_textAndWebContent.mhtml", __package__)
            text, encoding, warnings, selected = selector.select_mhtml_html(data)
            data = text.encode(encoding)
            result.main_html = selected | {"encoding": encoding}
            result.warnings.extend(warnings)
        archive = _mineru.MinerUClient(config).extract_document(
            data, filename="document.html" if html_input else f"document.{format}",
            model_version=model, max_archive_bytes=limits.max_archive_bytes,
            check_result_deadline=partial(check_deadline, deadline),
        )
        _read_result(archive, result, limits, deadline)
    except ArchiveProcessingStopped:
        raise
    except Exception as exc:
        message = re.sub(r"https?://\S+", "[redacted URL]", str(exc).replace(token, "[redacted]"))
        return DocumentResult(source, format, requested_model=model,
                              main_html=result.main_html, warnings=result.warnings,
                              error=f"MinerU document failed: {message}")
    return result


def _configuration(value):
    """JSON CLI 只接受既有配置字段；错误不回显调用方配置值。"""
    if value is None:
        value = MinerUConfig()
    if isinstance(value, Mapping):
        try:
            value = MinerUConfig(**value)
        except TypeError:
            raise ValueError("mineru contains unknown configuration fields") from None
    if not isinstance(value, MinerUConfig):
        raise ValueError("mineru must be MinerUConfig or an object")
    if value.token is not None and not isinstance(value.token, str):
        raise ValueError("mineru.token must be a string or null")
    if not _mineru._http_url(value.api_base):
        raise ValueError("mineru.api_base must be an HTTP(S) URL")
    if not isinstance(value.language, str) or not value.language.strip():
        raise ValueError("mineru.language must be a nonempty string")
    for name in ("poll_interval", "request_timeout", "max_wait"):
        number = getattr(value, name)
        if (type(number) not in (int, float) or not math.isfinite(number)
                or number < 0 or (name != "poll_interval" and number == 0)):
            raise ValueError(f"mineru.{name} must be finite and "
                             + ("nonnegative" if name == "poll_interval" else "positive"))
    return value


def _read_result(archive, result, limits, deadline):
    """原始 Markdown 与结构 JSON 独立保留；不猜测两者的字符对齐。"""
    try:
        zipped = ZipFile(BytesIO(archive))
    except BadZipFile:
        raise ValueError("MinerU result ZIP is invalid") from None
    with zipped:
        infos = zipped.infolist()
        if len(infos) > limits.max_members:
            raise ValueError("MinerU result ZIP exceeds max_members")
        if any(info.file_size > limits.max_member_bytes for info in infos):
            raise ValueError("MinerU result ZIP exceeds max_member_bytes")
        if sum(info.file_size for info in infos) > limits.max_total_bytes:
            raise ValueError("MinerU result ZIP exceeds max_total_bytes")
        names = [info.filename for info in infos if not info.is_dir()]
        markdown_files = [name for name in names if name.rsplit("/", 1)[-1] == "full.md"]
        content_lists = [name for name in names if name.endswith("_content_list.json")
                         or name.rsplit("/", 1)[-1] == "content_list.json"]
        if len(markdown_files) != 1:
            raise ValueError("MinerU result ZIP requires one full.md")
        if result.requested_model != "MinerU-HTML" and len(content_lists) != 1:
            raise ValueError("MinerU result ZIP requires one V1 content_list.json")
        total = 0
        for info in infos:
            if info.is_dir():
                continue
            name = info.filename
            result.artifacts.append(name)
            basename = name.rsplit("/", 1)[-1]
            payload, size = _read_artifact(zipped, info, limits, total, deadline,
                                            basename in ("full.md", "main.html") or name.endswith(".json"))
            total += size
            if basename == "full.md":
                result.markdown_file = name
                result.markdown = payload.decode("utf-8")
            elif name.endswith(".json"):
                try:
                    result.structured_json[name] = json.loads(payload.decode("utf-8-sig"))
                except (ValueError, UnicodeError):
                    raise ValueError("MinerU result JSON is invalid") from None
                if name.endswith("_content_list.json") or name.rsplit("/", 1)[-1] == "content_list.json":
                    result.content_list_file = name
            elif basename == "main.html":
                result.html_file = name
                result.html = payload.decode("utf-8")
    if not result.markdown.strip():
        raise ValueError("MinerU full.md has no usable body")
    if result.requested_model == "MinerU-HTML":
        result.review_items = ["HTML DOM locations and Markdown character ranges are unavailable; "
                               "verify body selection and table relationships against the input."]
        return
    blocks = result.structured_json[result.content_list_file]
    _validate_content_list(blocks, require_page=result.format == "pdf")
    result.sources = [DocumentSource(result.content_list_file, index, block.get("page_idx"),
                                     block["page_idx"] + 1 if result.format == "pdf" else None,
                                     "uploaded_pdf" if result.format == "pdf" else "service_page_unverified")
                      for index, block in enumerate(blocks)]
    result.review_items = ["Markdown character ranges are unavailable; structured block order is separate.",
                           "Reading order and table relationships require verification against the input."]
    if result.format != "pdf":
        result.review_items.append(
            "Office native locations are unavailable: Word sections/body blocks, slide/object ownership, "
            "worksheet/cell addresses and formula caches are not established by service page indices."
        )


def _read_artifact(zipped, info, limits, total, deadline, keep):
    """所有产物都计量并检查 CRC，非文本附件逐块丢弃且不落盘。"""
    content = bytearray()
    size = 0
    with zipped.open(info) as stream:
        while True:
            check_deadline(deadline)
            chunk = stream.read(min(64 * 1024, limits.max_member_bytes - size + 1,
                                    limits.max_total_bytes - total - size + 1))
            size += len(chunk)
            if size > limits.max_member_bytes:
                raise ValueError("MinerU result ZIP exceeds max_member_bytes")
            if total + size > limits.max_total_bytes:
                raise ValueError("MinerU result ZIP exceeds max_total_bytes")
            if not chunk:
                return bytes(content), size
            if keep:
                content.extend(chunk)


def _validate_content_list(blocks, require_page):
    """仅 V1 的块/页字段用于派生来源，其他 JSON 按服务产物原样保留。"""
    if not isinstance(blocks, list):
        raise ValueError("MinerU content_list must be an array")
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str):
            raise ValueError("MinerU content_list contains an invalid block")
        page = block.get("page_idx")
        if (require_page or page is not None) and (type(page) is not int or page < 0):
            raise ValueError("MinerU content_list page_idx must be a nonnegative integer")
