"""仅打包已有可核验图片；固定元数据使归档可重复构造，不重新绘图。"""

from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


SAMPLES = Path(__file__).resolve().parent
ARCHIVES = {
    "zip_image_formats.zip": [
        ("before.txt", None),
        ("图片/rules.png", "image_ocr_rules.png"),
        ("图片/rules.jpg", "image_ocr_rules.jpg"),
        ("图片/rules.jpeg", "image_ocr_rules.jpg"),
        ("图片/rules.webp", "image_ocr_rules.webp"),
        ("after.txt", None),
    ],
    "zip_image_ocr.zip": [("rules.png", "image_ocr_rules.png")],
    "zip_image_describe.zip": [("camping.webp", "image_description_camping.webp")],
    "zip_image_understand.zip": [("approval.png", "image_understanding_clear.png")],
    "zip_image_uncertain.zip": [("approval.png", "image_understanding_truncated.png")],
    "zip_image_blank.zip": [("blank.png", "image_ocr_blank.png")],
    "zip_image_crop.zip": [("crop.png", "image_provenance_crop.png")],
    "zip_image_corrupt.zip": [
        ("before.txt", None), ("broken.png", "image_ocr_corrupt.png"), ("after.txt", None),
    ],
}


def main():
    records = []
    for archive, members in ARCHIVES.items():
        entries = []
        with ZipFile(SAMPLES / archive, "w") as zipped:
            for index, (member, original) in enumerate(members, 1):
                data = (SAMPLES / original).read_bytes() if original else (member + "\n").encode()
                info = ZipInfo(member, date_time=(2026, 10, 28, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                zipped.writestr(info, data)
                entries.append({"member_path": member, "entry_index": index, "source_sample": original,
                                "bytes": len(data), "sha256": sha256(data).hexdigest()})
        records.append({"archive": archive, "sha256": sha256((SAMPLES / archive).read_bytes()).hexdigest(),
                        "members": entries})
    (SAMPLES / "zip_image_samples.json").write_text(json.dumps({
        "builder": Path(__file__).name,
        "source": "Reuse repository-authored fixed images; original builders and facts remain in image_* manifests.",
        "archives": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
