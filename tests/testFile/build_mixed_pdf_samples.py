"""交错两页数字事实和 #11 的扫描页；固定样本运行时不重新生成。"""

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).parent


def build():
    writer = PdfWriter()
    scans = PdfReader(ROOT / "pdf_scanned_maintenance_table.pdf")
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    for index, lines in enumerate((
        ["Digital Intake", "Asset code: PUMP-A17.", "Printed page 90"],
        ["Digital Release", "Torque setting: 12 Nm.", "Printed page 12"],
    )):
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        stream = DecodedStreamObject()
        commands = ["BT /F1 12 Tf 40 750 Td 24 TL"]
        commands.extend(f"({line}) Tj T*" for line in lines)
        commands.append("ET")
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.add_page(scans.pages[index])
    writer.write(ROOT / "pdf_mixed_maintenance.pdf")


if __name__ == "__main__":
    build()
