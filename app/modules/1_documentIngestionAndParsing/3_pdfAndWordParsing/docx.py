from io import BytesIO
from zipfile import BadZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from lxml.etree import XMLSyntaxError

from . import ContentSource, ConversionResult, Source


def extract_docx(data: bytes, source: Source) -> ConversionResult:
    """顶层段落和表格各占一个正文块；空块保留计数，非空标题开启新章节。"""
    try:
        document = Document(BytesIO(data))
    except (BadZipFile, XMLSyntaxError, KeyError, ValueError) as exc:
        return ConversionResult(None, source, error=f"DOCX parsing failed: {exc}")
    markdown = ""
    sources = []
    warnings = []
    headings = []
    section_block_number = 0
    for body_block_number, block in enumerate(document.iter_inner_content(), start=1):
        block_type = "paragraph"
        level = None
        if isinstance(block, Table):
            block_type = "table"
            text = _table_markdown(block)
        else:
            text = block.text.strip()
            level = _heading_level(block) if text else None
            if level is not None:
                headings = [(depth, title) for depth, title in headings if depth < level]
                headings.append((level, text))
                section_block_number = 0
                block_type = "heading"
                text = "#" * min(level, 6) + " " + text
                if level > 6:
                    warnings.append(
                        f"DOCX body block {body_block_number}: heading level {level} "
                        "rendered at Markdown level 6; native level retained in source"
                    )
        section_block_number += 1
        if not text:
            continue
        if markdown:
            markdown += "\n"
        start = len(markdown)
        markdown += text + "\n"
        sources.append(ContentSource(
            start, len(markdown), None, "docx_native",
            section_path=tuple(title for _, title in headings),
            body_block_number=body_block_number,
            section_block_number=section_block_number,
            block_type=block_type,
            heading_level=level,
        ))
    if not markdown:
        return ConversionResult(None, source, error="No usable text body in DOCX")
    warnings.append(
        "DOCX native extraction covers body paragraphs and simple rectangular tables; "
        "images, text boxes, headers/footers, list numbering and merged/nested table "
        "layouts are not reconstructed; verify against the DOCX"
    )
    return ConversionResult(markdown, source, sources, warnings)


def _table_markdown(table: Table) -> str:
    """普通矩形表格首行作为表头；单元格换行不拆成新行，空表不生成结构占位。"""
    cells = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if not any(text for row in cells for text in row):
        return ""
    rows = ["| " + " | ".join(
        text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
        for text in row
    ) + " |" for row in cells]
    rows.insert(1, "| " + " | ".join("---" for _ in table.columns) + " |")
    return "\n".join(rows)


def _heading_level(paragraph) -> int | None:
    """段落直接指定的大纲级别优先于样式，并沿 basedOn 继承；级别 9 表示正文。"""
    properties = [paragraph._p.pPr]
    style = paragraph.style
    while style is not None:
        properties.append(style.element.pPr)
        style = style.base_style
    for property_set in properties:
        if property_set is not None:
            outline = property_set.find(qn("w:outlineLvl"))
            if outline is not None:
                value = int(outline.get(qn("w:val")))
                return value + 1 if value < 9 else None
    return None
