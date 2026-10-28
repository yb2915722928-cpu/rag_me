"""手工定义审批关系并固定生成图片；不调用模型，也不在测试运行时生成。"""

from hashlib import sha256
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).parent
FONT = "C:/Windows/Fonts/msyh.ttc"


def build():
    image = Image.new("RGB", (1200, 850), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT, 34)
    small = ImageFont.truetype(FONT, 28)
    draw.text((600, 35), "付款审批流程", font=font, fill="black", anchor="mm")
    draw.polygon([(600, 95), (870, 220), (600, 345), (330, 220)],
                 fill="#edf5ff", outline="black", width=4)
    draw.text((600, 220), "金额超过 1 万元？", font=font, fill="black", anchor="mm")
    draw.line([(600, 345), (600, 430), (270, 430), (270, 640)], fill="black", width=6)
    draw.polygon([(270, 640), (256, 614), (284, 614)], fill="black")
    draw.text((630, 380), "是", font=small, fill="black", anchor="mm")
    draw.line([(870, 220), (1030, 220), (1030, 550), (930, 550), (930, 640)],
              fill="black", width=6)
    draw.polygon([(930, 640), (916, 614), (944, 614)], fill="black")
    draw.text((990, 180), "否（其他情况）", font=small, fill="black", anchor="mm")
    for box, text in [((100, 640, 440, 760), "负责人审批"), ((760, 640, 1100, 760), "财务审批")]:
        draw.rounded_rectangle(box, radius=12, fill="#eef7ee", outline="black", width=4)
        draw.text(((box[0] + box[2]) // 2, 700), text, font=font, fill="black", anchor="mm")

    blurred = image.copy()
    blurred.paste(image.crop((0, 350, 1200, 640)).filter(ImageFilter.GaussianBlur(55)), (0, 350))
    truncated = image.crop((0, 0, 1200, 350))
    samples = []
    for name, picture, expected in [
        ("clear", image, {"status": "content", "branches": [
            "金额超过1万元 → 负责人审批", "其他情况（不超过1万元） → 财务审批"]}),
        ("blurred", blurred, {"status": "uncertain", "known": "可辨金额条件、否（其他情况）标签及两个审批节点；是标签也在模糊区域内",
                              "reason": "关键连线与箭头被模糊，不能确认条件和审批人的完整对应"}),
        ("truncated", truncated, {"status": "uncertain", "known": "可辨金额条件与是/否分支起点",
                                  "reason": "底部审批节点和箭头终点被截去，无法确认分支终点"}),
    ]:
        path = ROOT / f"image_understanding_{name}.png"
        picture.save(path)
        raw = path.read_bytes()
        samples.append({"filename": path.name, "bytes": len(raw), "sha256": sha256(raw).hexdigest(),
                        "dimensions": list(picture.size), "expected": expected})
    (ROOT / "image_understanding_constructed.json").write_text(json.dumps({
        "source": "本仓库原创 Pillow 构图，文字与箭头坐标手工定义，未用模型生成真值。",
        "license": "本仓库测试素材；无外部下载，字体由本机 Microsoft YaHei 栅格化，未分发字体文件。",
        "builder": Path(__file__).name,
        "method": "清晰图含两条连续折线及向下箭头；模糊图对 y=[350,640) 连线带高斯模糊；截断图只保留 y=[0,350)。",
        "question": "请根据图中的条件和箭头，分别说明两条分支由谁审批；如果依据不足，请说明哪些关系无法确认以及原因。",
        "samples": samples,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
