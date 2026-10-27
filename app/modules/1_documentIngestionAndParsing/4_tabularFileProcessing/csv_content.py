import csv
from io import StringIO
from itertools import count
import re

from .models import Cell, Column, Row, Source, SourcePosition, Table, TableContext


def read_csv(
    text: str, source: Source, context: TableContext, delimiter: str, header_record: int | None,
) -> Table:
    columns = []
    rows = []
    for number, record, start, end in _read_records(text, delimiter):
        if header_record is not None and number < header_record:
            continue
        if not any(value.strip() for value in record):
            if number == header_record:
                raise ValueError(f"CSV header record {number} (physical lines {start}–{end}) is empty")
            continue
        position = SourcePosition(source, number, number, 1, len(record), start, end)
        cells = [
            Cell(value, value, SourcePosition(source, number, number, field, field, start, end))
            for field, value in enumerate(record, 1)
        ]
        if not columns:
            _validate_header(record, number, start, end)
            columns = [Column(cell.text, cell.source) for cell in cells]
            header = position
        else:
            if len(record) != len(columns):
                raise ValueError(
                    f"CSV record {number} (physical lines {start}–{end}): "
                    f"row width {len(record)} differs from header width {len(columns)}"
                )
            rows.append(Row(cells, columns, context, position))
    if not columns:
        label = "header" if header_record is None else f"header record {header_record}"
        raise ValueError(f"CSV {label} not found")
    if not rows:
        raise ValueError(f"CSV has no data records after header record {header.row_start}")
    return Table(columns, rows, context, SourcePosition(
        source, header.row_start, rows[-1].source.row_end, 1, len(columns),
        header.line_start, rows[-1].source.line_end,
    ))


def _validate_header(names: list[str], number: int, start: int, end: int) -> None:
    location = f"CSV header record {number} (physical lines {start}–{end})"
    for field, name in enumerate(names, 1):
        if not name.strip():
            raise ValueError(f"{location}: empty column name at field {field}")
    if len(set(names)) != len(names):
        raise ValueError(f"{location}: duplicate column names")


def _read_records(text: str, delimiter: str):
    """csv.reader 的 strict 模式仍接受裸双引号；额外检查语法，字段值始终由标准库读取。"""
    stream = StringIO(text, newline="")
    records = csv.reader(stream, delimiter=delimiter, strict=True)
    separator = re.escape(delimiter)
    field = rf'(?:[^{separator}"\r\n]*|"(?:[^"]|"")*")'
    grammar = re.compile(rf"{field}(?:{separator}{field})*(?:\r\n|\r|\n)?")
    for number in count(1):
        start, offset = records.line_num + 1, stream.tell()
        try:
            record = next(records)
        except StopIteration:
            return
        except csv.Error as exc:
            raise ValueError(
                f"CSV record {number} (physical lines {start}–{records.line_num}): "
                f"invalid CSV quoting or field: {exc}"
            ) from exc
        raw_record = text[offset:stream.tell()]
        if '"' in raw_record and not grammar.fullmatch(raw_record):
            raise ValueError(
                f"CSV record {number} (physical lines {start}–{records.line_num}): invalid quoting"
            )
        yield number, record, start, records.line_num
