from collections.abc import Mapping
import codecs
from io import BytesIO
import math
import ntpath
import time
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from .dispatch import UnsupportedFormat, convert_member
from .models import MemberResult, MemberSource, ZipLimits, ZipResult, _StopProcessing, _check_deadline


def convert_file(path, *, source=None, limits=None, metadata_encoding=None, parser_options=None):
    """只读取指定容器，成员名称从不作为写入路径；source 默认使用输入路径。"""
    location = str(path) if source is None else source
    try:
        limits, parser_options = _validate_options(location, limits, metadata_encoding, parser_options)
        path = Path(path)
    except (TypeError, ValueError, LookupError) as exc:
        return ZipResult(str(location), error=f"Invalid path or options: {exc}")
    try:
        with path.open("rb") as stream:
            return _convert_archive(stream, location, limits, metadata_encoding, parser_options)
    except OSError as exc:
        return ZipResult(location, error=f"Could not read ZIP: {exc}")


def convert_bytes(data, *, source, limits=None, metadata_encoding=None, parser_options=None):
    """字节入口与文件入口共享归档处理；成员失败保留其他成员的成功结果。"""
    try:
        limits, parser_options = _validate_options(source, limits, metadata_encoding, parser_options)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except (TypeError, ValueError, LookupError) as exc:
        return ZipResult(str(source), error=f"Invalid input or options: {exc}")
    return _convert_archive(BytesIO(data), source, limits, metadata_encoding, parser_options)


def _convert_archive(stream, source, limits, metadata_encoding, parser_options):
    result = ZipResult(source)
    deadline = time.monotonic() + limits.timeout_seconds
    stream.seek(0, 2)
    archive_size = stream.tell()
    stream.seek(0)
    if archive_size > limits.max_archive_bytes:
        result.stop_reason, result.error = "max_archive_bytes", "ZIP compressed input exceeds max_archive_bytes"
        return result
    try:
        container = ZipFile(stream, metadata_encoding=metadata_encoding)
    except (BadZipFile, OSError, ValueError, LookupError) as exc:
        result.error = f"ZIP reading failed: {exc}"
        return result
    with container:
        if len(container.infolist()) > limits.max_members:
            result.stop_reason, result.error = "max_members", "ZIP entry count exceeds max_members"
            return result
        for index, info in enumerate(container.infolist(), 1):
            name = info.orig_filename
            member_source = MemberSource(source, name, index)
            format = PurePosixPath(name.replace("\\", "/")).suffix.lower().lstrip(".")
            member = MemberResult(member_source, format, "failed")
            result.members.append(member)
            _process_member(container, info, member, result, limits, deadline, parser_options)
    if all(member.status == "ignored" for member in result.members):
        result.error = "No processable documents: ZIP is empty or contains only ignored entries"
    return result


def _process_member(container, info, member, result, limits, deadline, parser_options):
    """局部失败继续下一成员；全局预算/截止只停止尚未完成的资料。"""
    name = member.source.member_path
    unsafe = _unsafe_path(name)
    if _is_ignored(info) and not unsafe:
        member.status, member.reason = "ignored", "metadata_or_directory"
        return
    try:
        if result.stop_reason:
            raise _StopProcessing(result.stop_reason)
        _check_deadline(deadline)
    except _StopProcessing as exc:
        member.status, member.reason, member.error = "unprocessed", exc.reason, str(exc)
        result.stop_reason = exc.reason
        return
    if unsafe:
        member.reason, member.error = "unsafe_path", "Unsafe member path"
        return
    if member.format == "zip":
        member.reason, member.error = "nested_zip", "Nested ZIP is not supported"
        return
    if info.flag_bits & 1:
        member.reason, member.error = "encrypted_member", "Encrypted member is not supported"
        return
    if info.file_size > limits.max_member_bytes:
        member.reason, member.error = "max_member_bytes", "Member exceeds max_member_bytes"
        return
    try:
        if info.file_size > limits.max_total_bytes - result.total_bytes_read:
            raise _StopProcessing("max_total_bytes")
        content = _read_member(container, info, member, result, limits, deadline)
    except _StopProcessing as exc:
        member.status, member.reason, member.error = "unprocessed", exc.reason, str(exc)
        result.stop_reason = exc.reason
        return
    except Exception as exc:
        member.reason, member.error = "read_error", f"Member reading failed: {exc}"
        return
    try:
        kind, native = convert_member(
            content, format=member.format,
            source=f"{result.source}!/{name}#{member.source.entry_index}",
            parser_options=parser_options, limits=limits, deadline=deadline,
        )
        member.result_kind, member.result = kind, native
        member.status = "success" if native.success else "failed"
        if native.error is not None:
            member.error = native.error if isinstance(native.error, str) else native.error.message
        if not native.success:
            member.reason = "parse_error"
    except _StopProcessing as exc:
        member.status, member.reason, member.error = "unprocessed", exc.reason, str(exc)
        result.stop_reason = exc.reason
    except UnsupportedFormat as exc:
        member.reason, member.error = "unsupported_format", str(exc)
    except Exception as exc:
        member.reason, member.error = "parse_error", f"Member parsing failed: {exc}"


def _read_member(container, info, member, result, limits, deadline):
    """CRC 错误不返回当前块，该次请求保守占用预算，已读字节不会因失败退还。"""
    content = bytearray()
    with container.open(info) as stream:
        while True:
            _check_deadline(deadline)
            remaining = limits.max_total_bytes - result.total_bytes_read
            if remaining == 0:
                if member.bytes_read == info.file_size:
                    return bytes(content)
                raise _StopProcessing("max_total_bytes")
            requested = min(64 * 1024, limits.max_member_bytes - member.bytes_read + 1, remaining)
            try:
                chunk = stream.read(requested)
            except Exception:
                charged = min(requested, max(0, info.file_size - member.bytes_read))
                member.bytes_read += charged
                result.total_bytes_read += charged
                raise
            member.bytes_read += len(chunk)
            result.total_bytes_read += len(chunk)
            if member.bytes_read > limits.max_member_bytes:
                raise ValueError("Member exceeds max_member_bytes")
            if not chunk:
                return bytes(content)
            content.extend(chunk)


def _is_ignored(info):
    parts = info.filename.replace("\\", "/").split("/")
    return (info.is_dir() or "__MACOSX" in parts or parts[-1] == ".DS_Store"
            or parts[-1].startswith("._"))


def _unsafe_path(name):
    return (name.startswith(("/", "\\")) or bool(ntpath.splitdrive(name)[0])
            or ".." in name.replace("\\", "/").split("/"))


def _validate_options(source, limits, metadata_encoding, parser_options):
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a nonempty string")
    if limits is None:
        limits = ZipLimits()
    if not isinstance(limits, ZipLimits):
        raise ValueError("limits must be ZipLimits")
    for name in ("max_archive_bytes", "max_members", "max_member_bytes", "max_total_bytes"):
        value = getattr(limits, name)
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if (type(limits.timeout_seconds) not in (int, float)
            or not math.isfinite(limits.timeout_seconds) or limits.timeout_seconds <= 0):
        raise ValueError("timeout_seconds must be positive and finite")
    if metadata_encoding is not None:
        if not isinstance(metadata_encoding, str) or not metadata_encoding.strip():
            raise ValueError("metadata_encoding must be a codec name")
        codecs.lookup(metadata_encoding)
    if parser_options is None:
        parser_options = {}
    if not isinstance(parser_options, Mapping):
        raise ValueError("parser_options must be a mapping")
    options = {}
    for category, values in parser_options.items():
        if category not in ("text", "structured", "csv", "document", "image", "media"):
            raise ValueError("Unknown parser_options category")
        if not isinstance(values, Mapping):
            raise ValueError(f"parser_options.{category} must be a mapping")
        for key in values:
            if not isinstance(key, str):
                raise ValueError("parser option names must be strings")
            if key in ("format", "source", "limits", "deadline"):
                raise ValueError(f"parser_options must not override {key}")
        options[category] = dict(values)
    return limits, options
