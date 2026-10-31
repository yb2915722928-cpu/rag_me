from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import partial
import math
import os
import re

from . import mineru_client as _mineru
from .archive_budget import ArchiveLimits, ArchiveProcessingStopped, check_deadline
from .hosted_document_artifacts import read_result
from .hosted_document_input import HTML_FORMATS, prepare_input


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
    model = "MinerU-HTML" if format in HTML_FORMATS else "vlm"
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
        prepared = prepare_input(data, format=format)
        result.main_html = prepared.main_html
        result.warnings.extend(prepared.warnings)
        archive = _mineru.MinerUClient(config).extract_document(
            prepared.data, filename=prepared.filename,
            model_version=model, max_archive_bytes=limits.max_archive_bytes,
            check_result_deadline=partial(check_deadline, deadline),
        )
        read_result(archive, result, limits, deadline)
        _attach_sources(result)
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


def _attach_sources(result: DocumentResult) -> None:
    """服务块来源不建立到 Markdown 或 Office 原生位置的推测映射。"""
    if result.requested_model == "MinerU-HTML":
        result.review_items = ["HTML DOM locations and Markdown character ranges are unavailable; "
                               "verify body selection and table relationships against the input."]
        return
    blocks = result.structured_json[result.content_list_file]
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
