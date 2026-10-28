"""手工构造并固化来源样本；测试运行时不执行此脚本。"""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__


ROOT = Path(__file__).parent
BBOX = (120, 180, 1120, 440)
TEXT = "付款条件\n金额超过 1 万元时，须负责人审批。\n未经批准不得付款。"


def main():
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 36)
    original = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(original)
    draw.text((140, 60), "文档示例：付款规则", font=font, fill="black")
    draw.multiline_text((150, 210), TEXT, font=font, fill="black", spacing=20)
    draw.text((140, 500), "区域外文字：其他情况由财务审批。", font=font, fill="black")
    original.save(ROOT / "image_provenance_original.png")
    original.crop(BBOX).save(ROOT / "image_provenance_crop.png")
    alternate = original.copy()
    draw = ImageDraw.Draw(alternate)
    draw.rectangle(BBOX, fill="white")
    draw.multiline_text((150, 210), TEXT.replace("1 万元", "2 万元"), font=font, fill="black", spacing=20)
    alternate.crop(BBOX).save(ROOT / "image_provenance_crop_v2.png")
    records = []
    for name in ("original", "crop", "crop_v2"):
        path = ROOT / f"image_provenance_{name}.png"
        data = path.read_bytes()
        with Image.open(path) as image:
            records.append({"filename": path.name, "width": image.width, "height": image.height,
                            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (ROOT / "image_provenance_samples.json").write_text(json.dumps({
        "method": "Locally authored synthetic payment rules; Pillow ImageDraw on white RGB; "
                  "black text at (140,60), (150,210), (140,500), font 36, line spacing 20; "
                  "crop = original.crop((120,180,1120,440)); v2 changes 1 to 2 in crop text",
        "source": "Constructed locally; no downloaded images or model-generated truth",
        "license": "Project-authored fixture; follows repository license; system font not redistributed",
        "pillow": __version__, "font": str(font_path), "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "document": {"document_id": "payment-policy", "business_version": "approved-2026-10",
                     "position": {"kind": "pdf_page", "index": 3}},
        "crop": {"original_image_id": "archive/payment-rules/source-image-01", "original_width": 1200,
                 "original_height": 600, "bbox": list(BBOX)},
        "coordinate_system": "original top-left, zero-based pixels, right/bottom excluded",
        "expected_crop_text": TEXT, "excluded_text": "其他情况由财务审批",
        "samples": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
