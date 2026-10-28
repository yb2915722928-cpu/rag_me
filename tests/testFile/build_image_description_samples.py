"""手工重建描述样本；默认测试不生成图片或访问网络。"""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__


ROOT = Path(__file__).parent


def main():
    scene = Image.new("RGB", (960, 640), "#bde5f5")
    draw = ImageDraw.Draw(scene)
    draw.ellipse((735, 35, 845, 145), fill="#ffdb70")
    draw.polygon([(0, 350), (230, 95), (470, 350)], fill="#718b99")
    draw.polygon([(290, 350), (540, 65), (820, 350)], fill="#91a7ad")
    draw.polygon([(192, 138), (230, 95), (274, 142)], fill="white")
    draw.polygon([(488, 125), (540, 65), (600, 130)], fill="white")
    draw.rectangle((0, 335, 960, 640), fill="#8cba75")
    draw.ellipse((-140, 345, 760, 540), fill="#4ca9cf")
    for x, y in ((75, 330), (820, 345), (900, 380)):
        draw.rectangle((x - 7, y, x + 7, y + 100), fill="#79563c")
        draw.polygon([(x - 58, y + 65), (x, y - 80), (x + 58, y + 65)], fill="#286d48")
    draw.polygon([(330, 580), (465, 405), (620, 580)], fill="#f2a33c", outline="#6d4728", width=4)
    draw.polygon([(465, 405), (620, 580), (765, 550), (570, 395)], fill="#dc7830", outline="#6d4728", width=4)
    draw.polygon([(392, 580), (465, 450), (540, 580)], fill="#483e36")
    scene.save(ROOT / "image_description_camping.png")
    scene.save(ROOT / "image_description_camping.jpg", quality=95)
    scene.save(ROOT / "image_description_camping.webp", lossless=True)

    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 32)
    heading = ImageFont.truetype(str(font_path), 42)
    flow = Image.new("RGB", (1200, 780), "white")
    draw = ImageDraw.Draw(flow)
    draw.text((600, 55), "付款审批流程", font=heading, anchor="mm", fill="#182b45")
    draw.rounded_rectangle((430, 120, 770, 195), radius=12, fill="#e6eef7", outline="#325879", width=3)
    draw.text((600, 157), "提交付款申请", font=font, anchor="mm", fill="#182b45")
    draw.line([(600, 195), (600, 245)], fill="#325879", width=4)
    draw.polygon([(590, 232), (600, 247), (610, 232)], fill="#325879")
    draw.polygon([(600, 245), (860, 345), (600, 445), (340, 345)], fill="#fff1cd", outline="#936b24", width=3)
    draw.text((600, 345), "金额超过 1 万元？", font=font, anchor="mm", fill="#182b45")
    for x, label, approver in ((280, "是：超过 1 万元", "负责人审批"), (920, "否：其他情况", "财务审批")):
        draw.line([(x, 345), (x, 530)], fill="#325879", width=4)
        draw.line([(340 if x == 280 else 860, 345), (x, 345)], fill="#325879", width=4)
        draw.polygon([(x - 10, 515), (x, 532), (x + 10, 515)], fill="#325879")
        draw.text((x - 25 if x == 280 else x + 25, 465), label, font=font,
                  anchor="rm" if x == 280 else "lm", fill="#182b45")
        draw.rounded_rectangle((x - 155, 535, x + 155, 635), radius=12, fill="#e7f4e6", outline="#367044", width=3)
        draw.text((x, 585), approver, font=font, anchor="mm", fill="#182b45")
    draw.text((600, 715), "按金额条件分支选择审批人", font=font, anchor="mm", fill="#536579")
    flow.save(ROOT / "image_description_approval.png")

    records = []
    for path in sorted(ROOT.glob("image_description_*")):
        if path.suffix not in (".png", ".jpg", ".webp"):
            continue
        data = path.read_bytes()
        records.append({"filename": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (ROOT / "image_description_constructed.json").write_text(json.dumps({
        "source": "Original deterministic Pillow drawings in build_image_description_samples.py; no downloads or model-generated references",
        "license": "Original sample drawings dedicated to CC0-1.0; system font file is not distributed",
        "method": "Camping: 960x640 RGB, geometric mountains, sun, lake, three trees and orange tent; JPEG quality=95, WebP lossless. Approval: 1200x780 RGB, Chinese labels and explicit arrows to two approvers.",
        "pillow": __version__, "font": str(font_path), "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "camping_reference": "Lake-side camping scene: orange tent, mountains, lake, trees, sun; no people or text drawn",
        "approval_reference": "付款审批流程；提交付款申请；金额超过1万元→负责人审批；其他情况→财务审批。No universal single-approver rule is shown.",
        "samples": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
