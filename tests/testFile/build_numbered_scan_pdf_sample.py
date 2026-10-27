"""在固定混合 PDF 第 2 页叠加仅页码的隐藏文本层，扫描图保持不变。"""

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).parent


def build():
    reader = PdfReader(ROOT / "pdf_mixed_maintenance.pdf")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    page = writer.pages[1]
    page["/Resources"][NameObject("/Font")] = DictionaryObject({
        NameObject("/PageNumberFont"): DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
    })
    stream = DecodedStreamObject()
    stream.set_data(page.get_contents().get_data()
                    + b"\nq BT /PageNumberFont 12 Tf 3 Tr 40 60 Td (Printed page 41) Tj ET Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(ROOT / "pdf_mixed_numbered_scan.pdf")


if __name__ == "__main__":
    build()
