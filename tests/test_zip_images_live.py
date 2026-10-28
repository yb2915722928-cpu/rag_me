from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import re
import time
import unittest

from dotenv import load_dotenv


zips = importlib.import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
SAMPLES = Path(__file__).resolve().parent / "testFile"
MANIFEST = json.loads((SAMPLES / "zip_image_samples.json").read_text(encoding="utf-8"))
ARCHIVES = {record["archive"]: record for record in MANIFEST["archives"]}
QUESTION = "请根据图中的条件和箭头，分别说明两条分支由谁审批；如果依据不足，请说明哪些关系无法确认以及原因。"
CASES = {
    "ocr": ("zip_image_ocr.zip", {"task": "ocr"}, "content", "ocr-v1"),
    "describe": ("zip_image_describe.zip", {"task": "describe"}, "content", "describe-v1"),
    "understand": ("zip_image_understand.zip", {"task": "understand", "question": QUESTION}, "content", "understand-v2"),
    "no_text": ("zip_image_blank.zip", {"task": "ocr"}, "no_text", "ocr-v1"),
    "uncertain": ("zip_image_uncertain.zip", {"task": "understand", "question": QUESTION}, "uncertain", "understand-v2"),
    "crop": ("zip_image_crop.zip", {
        "task": "ocr", "is_cropped": True,
        "document": images.DocumentSource("payment-policy", "approved-2026-10", images.DocumentPosition("pdf_page", 3)),
        "crop": images.CropMapping("archive/payment-rules/source-image-01", 1200, 600, (120, 180, 1120, 440)),
    }, "content", "ocr-v1"),
}


@unittest.skipUnless(os.environ.get("STEP_ZIP_IMAGE_LIVE_TEST") == "1",
                     "Requires explicit STEP_ZIP_IMAGE_LIVE_TEST=1, STEP_ENV_FILE and fresh evidence path")
class ZipImageLiveTests(unittest.TestCase):
    def test_real_api_quality_through_zip_public_entries(self):
        env_file = os.environ.get("STEP_ENV_FILE")
        self.assertTrue(env_file and Path(env_file).is_file(), "STEP_ENV_FILE must identify the explicit environment file")
        evidence = os.environ.get("STEP_ZIP_IMAGE_LIVE_EVIDENCE")
        self.assertTrue(evidence, "Set STEP_ZIP_IMAGE_LIVE_EVIDENCE to a fresh output path")
        evidence = Path(evidence)
        self.assertFalse(evidence.exists(), "Use a fresh evidence path to preserve previous runs")
        selected = os.environ.get("STEP_ZIP_IMAGE_LIVE_CASE")
        self.assertTrue(selected is None or selected in CASES, "Unknown STEP_ZIP_IMAGE_LIVE_CASE")
        load_dotenv(dotenv_path=env_file, override=False)
        records = []
        for case, (archive, options, status, prompt_version) in CASES.items():
            if selected and selected != case:
                continue
            with self.subTest(case=case):
                started = time.perf_counter()
                archive_data = (SAMPLES / archive).read_bytes()
                if case == "uncertain":
                    result = zips.convert_bytes(archive_data, source=archive, parser_options={"image": options})
                    entry = "convert_bytes"
                else:
                    result = zips.convert_file(SAMPLES / archive, source=archive, parser_options={"image": options})
                    entry = "convert_file"
                seconds = round(time.perf_counter() - started, 3)
                report = result.to_dict()
                sample = ARCHIVES[archive]["members"][0]
                member = result.members[0] if result.members else None
                native = member.result if member else None
                source = native.source if native else None
                checks = {
                    "archive_identity": sha256(archive_data).hexdigest() == ARCHIVES[archive]["sha256"],
                    "success": result.success,
                    "requires_review": result.requires_review,
                    "one_successful_member": result.counts == {
                        "total": 1, "success": 1, "failed": 0, "ignored": 0, "unprocessed": 0,
                    },
                    "member_identity": bool(member and member.result_kind == "image"
                                            and member.source.container == archive
                                            and member.source.member_path == sample["member_path"]
                                            and member.source.entry_index == 1),
                    "image_identity": bool(source and source.sha256 == sample["sha256"]),
                    "source_location": bool(source and source.location == f"{archive}!/{sample['member_path']}#1"),
                    "native_contract": bool(native and native.success and native.status == status
                                            and native.task == options["task"] and native.question == options.get("question")
                                            and native.prompt_version == prompt_version and native.requires_review),
                    "json_contract": bool(report["success"] and report["requires_review"] and report["members"]
                                          and report["members"][0]["result"]["success"]
                                          and report["members"][0]["result"]["requires_review"]),
                }
                text = re.sub(r"\s+", "", native.text or "") if native else ""
                checks.update(_quality_checks(case, text, native, options))
                records.append({
                    "case": case, "entry": entry, "seconds": seconds,
                    "source_summary": {"archive": archive, "sha256": ARCHIVES[archive]["sha256"], "member": sample},
                    "report": report, "checks": checks, "quality_passed": all(checks.values()),
                })
                _persist_evidence(evidence, records)
                self.assertTrue(all(checks.values()), checks)


def _quality_checks(case, text, native, options):
    """真值来自既有构图及人工定义的分支，不根据模型结果重新生成预期。"""
    if case == "no_text":
        return {"empty_ocr": bool(native and native.text == "" and native.warnings)}
    if case == "describe":
        return {"tent": "帐篷" in text, "mountains": "山" in text,
                "water": bool(re.search(r"湖|水", text)), "trees": "树" in text,
                "no_invented_people": not bool(re.search(r"(?<!无)(?<!没)(?<!没有)有人|[一二三两几多]个人", text))}
    if case == "uncertain":
        return {"keeps_known_condition": "金额" in text and bool(re.search(r"1万|一万|10000", text)),
                "explicit_unknown": bool(re.search(r"无法|不能|难以|不确定", text)),
                "reason": bool(re.search(r"截断|裁剪|缺失|截去|未显示|看不到|不可见", text)),
                "no_invented_cover": "黑色遮挡" not in text and "黑色覆盖" not in text}
    above = bool(re.search(r"(?<!不)(?<!未)(?:超过|大于|>)(?:1万|一万|10000)元.{0,80}?负责人.{0,12}?审批", text))
    if case == "crop":
        return {"above_10000_to_manager": above, "negative_rule": "未经批准不得付款" in text,
                "no_outside_crop_rule": "其他情况由财务审批" not in text,
                "document_source": bool(native and native.source.document == options["document"]),
                "original_mapping": bool(native and native.source.crop == options["crop"]
                                         and (native.source.width, native.source.height) == (1000, 260))}
    other = bool(re.search(
        r"(?:其他情况|其它情况|不超过(?:1万|一万|10000)元|未超过(?:1万|一万|10000)元|小于等于(?:1万|一万|10000)元|≤(?:1万|一万|10000)元).{0,80}?财务.{0,12}?审批", text))
    checks = {"above_10000_to_manager": above, "other_to_finance": other}
    if case == "ocr":
        checks.update({"negative_rule": "未经批准不得付款" in text,
                       "temperature": bool(re.search(r"不得超过60(?:°C|℃)", text)),
                       "interval": "每30天检查一次" in text})
    return checks


def _persist_evidence(path, records):
    """先保存每次公开入口的实际报告与检查；不保存配置、环境文件位置或 URL/token。"""
    payload = json.dumps({
        "checked_at": datetime.now(timezone.utc).isoformat(), "records": records,
        "limitation": "每例单次请求，无重试或本地回退。自动语义检查仍需人工对照固定原图；不证明任意图片质量。",
    }, ensure_ascii=False, indent=2)
    for name in ("STEP_API_KEY", "STEP_BASE_URL"):
        value = os.environ.get(name)
        if value:
            payload = payload.replace(json.dumps(value, ensure_ascii=False)[1:-1], "[REDACTED]")
    payload = re.sub(r'https?://[^\s"\\]+', "[URL_REDACTED]", payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    unittest.main()
