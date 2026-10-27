from io import BytesIO
import re

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries

from .models import Column, Row, SourcePosition, Table, XlsxOptions, XlsxSheetOptions
from .xlsx_values import adapt_cell


def validate_xlsx_options(options: XlsxOptions) -> None:
    """只在公开入口调用；行号基于原工作表，区域只接受封闭 A1 矩形。"""
    if not isinstance(options, XlsxOptions):
        raise ValueError("xlsx must be XlsxOptions or None")
    if options.sheets is None:
        return
    if not isinstance(options.sheets, tuple) or not options.sheets:
        raise ValueError("xlsx.sheets must be a nonempty tuple or None")
    names = set()
    for config in options.sheets:
        if not isinstance(config, XlsxSheetOptions):
            raise ValueError("xlsx.sheets items must be XlsxSheetOptions")
        if not isinstance(config.sheet, str) or not config.sheet.strip() or config.sheet in names:
            raise ValueError("sheet names must be nonempty and unique")
        names.add(config.sheet)
        top, bottom = 1, 1048576
        if config.cell_range is not None:
            if not isinstance(config.cell_range, str) or not re.fullmatch(
                r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)?",
                config.cell_range,
            ):
                raise ValueError("cell_range must be a closed A1 rectangle")
            left, top, right, bottom = range_boundaries(config.cell_range)
            if not (1 <= left <= right <= 16384 and 1 <= top <= bottom <= 1048576):
                raise ValueError("cell_range is reversed or outside XLSX bounds")
        if config.header_rows is not None:
            header = config.header_rows
            if not isinstance(header, tuple) or not header or any(
                type(row) is not int or not top <= row <= bottom for row in header
            ):
                raise ValueError("header_rows must be a nonempty tuple of rows within the range")
            if any(current != previous + 1 for previous, current in zip(header, header[1:])):
                raise ValueError("header_rows must be consecutive and increasing")


def read_xlsx(data, source, context, options, warnings: list[str]) -> list[Table]:
    """两份工作簿视图对应同一输入字节；缓存视图只交给值适配器，不进行计算。"""
    book = load_workbook(BytesIO(data), data_only=False)
    try:
        cached = load_workbook(BytesIO(data), data_only=True)
        try:
            selected = None if options is None or options.sheets is None else {
                item.sheet: item for item in options.sheets
            }
            if selected is not None:
                missing = set(selected) - set(book.sheetnames)
                if missing:
                    raise ValueError(f"XLSX sheets not found: {sorted(missing)}")
            tables = []
            for sheet in book.worksheets:
                if selected is not None:
                    if sheet.title not in selected:
                        continue
                    config = selected[sheet.title]
                else:
                    if sheet.sheet_state != "visible":
                        continue
                    config = XlsxSheetOptions(sheet.title)
                populated = [cell for row in sheet.iter_rows() for cell in row
                             if cell.value is not None and str(cell.value).strip()]
                if not populated and selected is None:
                    continue
                if not populated:
                    raise ValueError(f"XLSX sheet {sheet.title}: empty selected sheet")
                bounds = range_boundaries(config.cell_range) if config.cell_range else (
                    min(cell.column for cell in populated), min(cell.row for cell in populated),
                    max(cell.column for cell in populated), max(cell.row for cell in populated),
                )
                tables.append(_read_sheet(sheet, cached[sheet.title], source,
                                          config.context or context, bounds, config.header_rows, warnings))
            if not tables:
                raise ValueError("XLSX has no nonempty visible sheets")
            return tables
        finally:
            cached.close()
    finally:
        book.close()


def _read_sheet(sheet, cached_sheet, source, context, bounds, header_rows, warnings):
    left, top, right, bottom = bounds
    location = f"XLSX sheet {sheet.title}"
    if header_rows is not None and len(header_rows) > 1:
        raise ValueError(f"{location}: multi-level headers are not supported yet")
    for merged in sheet.merged_cells.ranges:
        if merged.min_col <= right and merged.max_col >= left and merged.min_row <= bottom and merged.max_row >= top:
            raise ValueError(f"{location}: merged range {merged} is not supported yet")
    if header_rows is not None:
        top = header_rows[0]
    columns = []
    rows = []
    for cells in sheet.iter_rows(min_row=top, max_row=bottom, min_col=left, max_col=right):
        if all(cell.value is None or not str(cell.value).strip() for cell in cells):
            if header_rows is not None and cells[0].row == top:
                raise ValueError(f"{location}: header row {top} is empty")
            continue
        values = [adapt_cell(cell, cached_sheet.cell(cell.row, cell.column),
                             _position(source, sheet.title, cell.row, cell.row, cell.column, cell.column),
                             warnings) for cell in cells]
        if not columns:
            names = [cell.text for cell in values]
            for cell in values:
                if not cell.text.strip():
                    raise ValueError(f"{location}: empty column name at {cell.source.coordinate}")
            if len(set(names)) != len(names):
                raise ValueError(f"{location}: duplicate column names at row {cells[0].row}")
            columns = [Column(cell.text, cell.source) for cell in values]
            header = cells[0].row
        else:
            rows.append(Row(values, columns, context,
                            _position(source, sheet.title, cells[0].row, cells[0].row, left, right)))
    if not columns:
        raise ValueError(f"{location}: header not found in selected range")
    if not rows:
        raise ValueError(f"{location}: no data records after header row {header}")
    return Table(columns, rows, context,
                 _position(source, sheet.title, header, rows[-1].source.row_end, left, right))


def _position(source, sheet, top, bottom, left, right):
    start, end = f"{get_column_letter(left)}{top}", f"{get_column_letter(right)}{bottom}"
    return SourcePosition(source, top, bottom, left, right, sheet=sheet,
                          coordinate=start if start == end else f"{start}:{end}")
