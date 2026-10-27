from dataclasses import dataclass, field


@dataclass
class Source:
    location: str
    format: str | None = None


@dataclass
class SourcePosition:
    """行列从 1 开始且两端包含；CSV 行指原始记录，物理行范围指该记录所占文本行。"""

    source: Source
    row_start: int
    row_end: int
    column_start: int
    column_end: int
    line_start: int | None = None
    line_end: int | None = None
    sheet: str | None = None
    coordinate: str | None = None
    merged_anchor: str | None = None
    merged_range: str | None = None


@dataclass
class TableContext:
    name: str | None = None
    version: str | None = None
    applicability: str | None = None
    notes: str | None = None


@dataclass
class XlsxSheetOptions:
    sheet: str
    cell_range: str | None = None
    header_rows: tuple[int, ...] | None = None
    context: TableContext | None = None


@dataclass
class XlsxOptions:
    sheets: tuple[XlsxSheetOptions, ...] | None = None


@dataclass
class Column:
    name: str
    source: SourcePosition
    header_sources: list[SourcePosition] = field(default_factory=list)


@dataclass
class Cell:
    raw_value: object
    text: str
    source: SourcePosition
    data_type: str | None = None
    number_format: str | None = None
    formula: str | None = None
    cached_value: object = None
    cache_status: str | None = None


@dataclass
class Row:
    cells: list[Cell]
    columns: list[Column]
    context: TableContext
    source: SourcePosition
    text: str = ""


@dataclass
class Table:
    columns: list[Column]
    rows: list[Row]
    context: TableContext
    source: SourcePosition


@dataclass
class ConversionResult:
    markdown: str | None
    source: Source
    tables: list[Table] = field(default_factory=list)
    encoding: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.markdown is not None and self.error is None
