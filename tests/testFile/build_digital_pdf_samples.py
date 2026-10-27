"""生成用于页序核验的固定 PDF；测试运行时只读取生成后的样本。"""

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)


ROOT = Path(__file__).parent


def write_pdf(filename, pages):
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    for lines in pages:
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        stream = DecodedStreamObject()
        commands = ["BT /F1 12 Tf 40 750 Td 24 TL"]
        for line in lines:
            commands.append(f"({line}) Tj T*")
        commands.append("ET")
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(ROOT / filename)


if __name__ == "__main__":
    write_pdf("pdf_digital_page_order.pdf", [
        ["Maintenance Start", "Disconnect power before maintenance.", "Printed page 41"],
        ["Maintenance Finish", "Inspect every month.", "Printed page 7"],
    ])
    (ROOT / "pdf_digital_corrupt.pdf").write_bytes(b"%PDF-1.7\nbroken, no xref or trailer\n")
    damaged = PdfWriter(ROOT / "pdf_digital_page_order.pdf")
    stream = DecodedStreamObject()
    stream.set_data(b"BT (unterminated")
    damaged.pages[1][NameObject("/Contents")] = damaged._add_object(stream)
    damaged.write(ROOT / "pdf_digital_damaged_page.pdf")
    write_pdf("pdf_digital_blank.pdf", [[]])
