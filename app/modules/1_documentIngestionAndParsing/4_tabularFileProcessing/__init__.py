from importlib import import_module
from pathlib import Path

from .csv_content import read_csv
from .models import (
    Cell, Column, ConversionResult, Row, Source, SourcePosition, Table, TableContext,
)
from .rendering import render_rows, render_table


decode_bytes = import_module("..2_textAndWebContent.decoding", __package__).decode_bytes


def convert_file(
    path, *, format=None, source=None, mode="table", context=None,
    encoding=None, delimiter=",", header_record=None,
) -> ConversionResult:
    """header_record 从 1 开始计原始 CSV 记录，包含空记录，不是物理行号。"""
    source_info = Source(str(path) if source is None else str(source))
    try:
        path = Path(path)
        source_info = _validate_options(
            path.suffix if format is None else format,
            str(path) if source is None else source,
            mode, context, encoding, delimiter, header_record,
        )
    except (TypeError, ValueError) as exc:
        return ConversionResult(None, source_info, error=f"Invalid path or options: {exc}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ConversionResult(None, source_info, error=f"Could not read '{path}': {exc}")
    return _convert_content(
        data, source_info, mode, context or TableContext(), encoding, delimiter, header_record,
    )


def convert_bytes(
    data, *, format, source, mode="table", context=None,
    encoding=None, delimiter=",", header_record=None,
) -> ConversionResult:
    """source 必须由调用方明确提供；失败时不暴露部分正文或表格。"""
    source_info = Source(str(source))
    try:
        source_info = _validate_options(
            format, source, mode, context, encoding, delimiter, header_record,
        )
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except ValueError as exc:
        return ConversionResult(None, source_info, error=str(exc))
    return _convert_content(
        data, source_info, mode, context or TableContext(), encoding, delimiter, header_record,
    )


def _convert_content(
    data: bytes, source_info: Source, mode: str, context: TableContext,
    encoding: str | None, delimiter: str, header_record: int | None,
) -> ConversionResult:
    try:
        text, encoding, warnings = decode_bytes(data, encoding)
    except (UnicodeError, LookupError) as exc:
        return ConversionResult(None, source_info, error=f"Decoding failed: {exc}")
    try:
        table = read_csv(text.removeprefix("\ufeff"), source_info, context, delimiter, header_record)
    except ValueError as exc:
        return ConversionResult(
            None, source_info, encoding=encoding, warnings=warnings, error=str(exc),
        )
    warnings.extend(
        f"Table context {name} is unknown; caller did not supply it."
        for name in ("name", "version", "applicability")
        if getattr(table.context, name) is None
    )
    render_rows(table)
    markdown = (
        render_table(table) if mode == "table"
        else "\n\n".join(row.text for row in table.rows)
    )
    return ConversionResult(markdown, source_info, [table], encoding, warnings)


def _validate_options(format, source, mode, context, encoding, delimiter, header_record) -> Source:
    if not isinstance(format, str) or not format.strip():
        raise ValueError("format must be a nonempty string")
    input_format = format.strip().lower().lstrip(".")
    if input_format != "csv":
        raise ValueError(f"Unsupported format: {input_format}")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a nonempty string")
    if mode not in ("table", "rows"):
        raise ValueError("mode must be 'table' or 'rows'")
    if encoding is not None and (not isinstance(encoding, str) or not encoding.strip()):
        raise ValueError("encoding must be a nonempty string or None")
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n"':
        raise ValueError("delimiter must be one character other than a quote or newline")
    if header_record is not None and (type(header_record) is not int or header_record < 1):
        raise ValueError("header_record must be a positive integer or None")
    if context is not None:
        if not isinstance(context, TableContext):
            raise ValueError("context must be a TableContext or None")
        for name in ("name", "version", "applicability", "notes"):
            value = getattr(context, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"context.{name} must be a nonempty string or None")
    return Source(source, input_format)
