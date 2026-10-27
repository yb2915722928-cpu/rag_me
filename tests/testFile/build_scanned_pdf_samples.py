"""生成纯图像维护表格 PDF；Pillow 只用于样本构造，不是解析运行时依赖。"""

from pathlib import Path
import zlib

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject, DictionaryObject, EncodedStreamObject,
    NameObject, NumberObject,
)


ROOT = Path(__file__).parent


def build():
    writer = PdfWriter()
    font = ImageFont.load_default(size=46)
    title = ImageFont.load_default(size=62)
    for page_number in (1, 2):
        image = Image.new("RGB", (1800, 2400), "white")
        draw = ImageDraw.Draw(image)
        if page_number == 1:
            draw.text((120, 150), "Equipment Maintenance", font=title, fill="black")
            for y, line in (
                (330, "Disconnect power before maintenance."),
                (430, "Do not service while power is on."),
                (530, "Inspect every 30 days."),
                (1450, "Restart after inspection."),
                (2180, "Printed page 41"),
            ):
                draw.text((120, y), line, font=font, fill="black")
            for x in (120, 920, 1680):
                draw.line((x, 780, x, 1230), fill="black", width=5)
            for y in (780, 930, 1080, 1230):
                draw.line((120, y, 1680, y), fill="black", width=5)
            for y, left, right in (
                (825, "Equipment", "Interval"),
                (975, "Pump", "Monthly"),
                (1125, "Valve", "Quarterly"),
            ):
                draw.text((170, y), left, font=font, fill="black")
                draw.text((970, y), right, font=font, fill="black")
        else:
            draw.text((120, 150), "Inspection Limits", font=title, fill="black")
            draw.text((120, 350), "Temperature must not exceed 60 C.", font=font, fill="black")
            draw.text((120, 2180), "Printed page 7", font=font, fill="black")
        page = writer.add_blank_page(width=600, height=800)
        raster = EncodedStreamObject()
        raster._data = zlib.compress(image.tobytes())
        raster.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(image.width),
            NameObject("/Height"): NumberObject(image.height),
            NameObject("/BitsPerComponent"): NumberObject(8),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/Filter"): NameObject("/FlateDecode"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Scan"): writer._add_object(raster)})
        })
        stream = DecodedStreamObject()
        stream.set_data(b"q 600 0 0 800 0 0 cm /Scan Do Q")
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(ROOT / "pdf_scanned_maintenance_table.pdf")


if __name__ == "__main__":
    build()
