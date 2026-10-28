"""手工重建固定样本；测试本身不运行此脚本，也不访问网络。"""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__


ROOT = Path(__file__).parent
TEXT = (
    "金额超过 1 万元时，须负责人审批。\n"
    "其他情况由财务审批。\n"
    "未经批准不得付款。\n"
    "温度不得超过 60 °C；每 30 天检查一次。"
)


def main():
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 42)
    image = Image.new("RGB", (1100, 340), "white")
    ImageDraw.Draw(image).multiline_text((30, 28), TEXT, font=font, fill="black", spacing=22)
    image.save(ROOT / "image_ocr_rules.png")
    image.save(ROOT / "image_ocr_rules.jpg", quality=95)
    image.save(ROOT / "image_ocr_rules.webp", lossless=True)
    Image.new("RGB", (320, 240), "white").save(ROOT / "image_ocr_blank.png")
    (ROOT / "image_ocr_override.bin").write_bytes((ROOT / "image_ocr_rules.png").read_bytes())
    (ROOT / "image_ocr_corrupt.png").write_bytes((ROOT / "image_ocr_rules.png").read_bytes()[:120])
    second = Image.new("RGB", image.size, "blue")
    for extension in ("png", "webp", "gif", "tiff"):
        image.save(ROOT / f"image_ocr_multiframe.{extension}", save_all=True,
                   append_images=[second], duration=100, loop=0,
                   **({"compression": "tiff_deflate"} if extension == "tiff" else {}))
    image.save(ROOT / "image_ocr_static.gif")
    records = []
    for path in sorted(ROOT.glob("image_ocr_*")):
        if path.name.startswith("image_ocr_stepfun"):
            continue
        if path.suffix not in (".png", ".jpg", ".webp", ".bin", ".gif", ".tiff"):
            continue
        data = path.read_bytes()
        records.append({"filename": path.name, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    (ROOT / "image_ocr_constructed.json").write_text(json.dumps({
        "method": "Pillow ImageDraw, white RGB 1100x340, black text at (30,28), spacing=22; "
                  "JPEG quality=95, WebP lossless; blank white RGB 320x240; "
                  "multiframe: second blue frame, TIFF deflate; corrupt: first 120 PNG bytes; override: exact PNG bytes",
        "pillow": __version__, "font": str(font_path), "font_size": 42,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "expected_rules_text": TEXT, "expected_blank_status": "no_text",
        "samples": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
