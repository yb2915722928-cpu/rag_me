"""Read one MinerU result ZIP within its own caller-provided archive limits."""

from io import BytesIO
import json
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

from .archive_budget import ArchiveLimits, check_deadline

if TYPE_CHECKING:
    from .hosted_documents import DocumentResult


def read_result(archive: bytes, result: "DocumentResult", limits: ArchiveLimits,
                deadline: float) -> None:
    """独立保留 Markdown、JSON、HTML；失败时由调用方丢弃未完成结果。"""
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
    if result.requested_model != "MinerU-HTML":
        _validate_content_list(result.structured_json[result.content_list_file],
                               require_page=result.format == "pdf")


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
