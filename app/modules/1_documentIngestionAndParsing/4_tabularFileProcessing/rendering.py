from html import escape

from .models import SourcePosition, Table, TableContext


def render_source(position: SourcePosition) -> str:
    if position.sheet is not None:
        return (
            f"来源：{position.source.location}；工作表：{position.sheet}；"
            f"区域：{position.coordinate}；行 {position.row_start}–{position.row_end}；"
            f"列 {position.column_start}–{position.column_end}"
        )
    return (
        f"来源：{position.source.location}；记录 {position.row_start}–{position.row_end}；"
        f"字段 {position.column_start}–{position.column_end}；"
        f"物理行 {position.line_start}–{position.line_end}"
    )


def render_context(context: TableContext) -> str:
    lines = [
        f"表名：{context.name or '未知'}",
        f"版本：{context.version or '未知'}",
        f"适用条件：{context.applicability or '未知'}",
    ]
    if context.notes is not None:
        lines.append(f"备注：{context.notes}")
    return "\n".join(lines)


def render_table(table: Table) -> str:
    lines = [
        "| " + " | ".join(_markdown_text(column.name) for column in table.columns) + " |",
        "| " + " | ".join("---" for _ in table.columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_markdown_text(cell.text) for cell in row.cells) + " |"
        for row in table.rows
    )
    return (
        render_context(table.context) + "\n" + render_source(table.source)
        + "\n\n" + "\n".join(lines)
    )


def render_rows(table: Table) -> None:
    context = render_context(table.context)
    for row in table.rows:
        fields = "\n".join(
            f"{_markdown_text(column.name)}：{_markdown_text(cell.text)}"
            for column, cell in zip(row.columns, row.cells)
        )
        row.text = context + "\n" + render_source(row.source) + "\n" + fields


def _markdown_text(text: str) -> str:
    return (
        escape(text, quote=False).replace("\\", "\\\\").replace("|", "\\|")
        .replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    )
