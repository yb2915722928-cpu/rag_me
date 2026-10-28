from dataclasses import asdict
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import time
import unittest

from dotenv import load_dotenv


images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
SAMPLES = Path(__file__).parent / "testFile"
MANIFEST = json.loads((SAMPLES / "image_understanding_constructed.json").read_text(encoding="utf-8"))


@unittest.skipUnless(os.environ.get("STEP_UNDERSTANDING_LIVE_TEST") == "1",
                     "Explicit STEP_UNDERSTANDING_LIVE_TEST=1 and STEP_ENV_FILE required")
class StepFunUnderstandingLiveTests(unittest.TestCase):
    def test_clear_branches_and_uncertainty_on_blurred_and_truncated_images(self):
        env_file = os.environ.get("STEP_ENV_FILE")
        self.assertTrue(env_file and Path(env_file).is_file(), "STEP_ENV_FILE must name the explicit .env")
        load_dotenv(dotenv_path=env_file, override=False)
        evidence_path = os.environ.get("STEP_UNDERSTANDING_LIVE_EVIDENCE")
        self.assertTrue(evidence_path, "Set a unique STEP_UNDERSTANDING_LIVE_EVIDENCE to preserve this run")
        self.assertFalse(Path(evidence_path).exists(), "Preserve prior evidence; use a new output path")
        selected = os.environ.get("STEP_UNDERSTANDING_LIVE_SAMPLE")
        if selected:
            self.assertIn(selected, [sample["filename"] for sample in MANIFEST["samples"]])
        records = []
        for sample in MANIFEST["samples"]:
            if selected and sample["filename"] != selected:
                continue
            with self.subTest(sample=sample["filename"]):
                started = time.perf_counter()
                result = images.convert_file(SAMPLES / sample["filename"], source=sample["filename"],
                                             task="understand", question=MANIFEST["question"])
                checks = {"success": result.success, "requires_review": result.requires_review,
                          "status": result.status == sample["expected"]["status"],
                          "question": result.question == MANIFEST["question"],
                          "image_identity": result.source.sha256 == sample["sha256"]}
                if result.success:
                    text = re.sub(r"\s+", "", result.text)
                    if sample["expected"]["status"] == "content":
                        checks["above_10000_to_manager"] = bool(re.search(
                            r"(?<!不)(?<!未)(?:超过|大于|>)(?:1万|一万|10000)元.{0,80}?负责人.{0,12}?审批", text))
                        checks["other_to_finance"] = bool(re.search(
                            r"(?:其他情况|其它情况|不超过(?:1万|一万|10000)元|未超过(?:1万|一万|10000)元|小于等于(?:1万|一万|10000)元|≤(?:1万|一万|10000)元).{0,80}?财务.{0,12}?审批", text))
                    else:
                        checks["explicit_unknown"] = bool(re.search(r"(?:无法|不能|不[能足以]*确定|难以).{0,12}(?:确认|确定|判断|对应)", text))
                        checks["keeps_known_content"] = "金额" in text and ("万元" in text or "10000" in text)
                        checks["reason"] = bool(re.search(
                            r"模糊|不清|难以辨认|无法辨认|未显示.{0,30}(?:连接|终点)|没有可见箭头" if "blurred" in sample["filename"] else r"截断|裁剪|截去|缺失|未显示|未展示|不可见|看不到|没有显示", text))
                        if "truncated" in sample["filename"]:
                            checks["no_invented_black_cover"] = "黑色遮挡" not in text and "黑色覆盖" not in text
                records.append({"sample": sample["filename"], "expected": sample["expected"],
                                "seconds": round(time.perf_counter() - started, 3),
                                "result": asdict(result), "checks": checks,
                                "quality_passed": all(checks.values())})
                Path(evidence_path).write_text(json.dumps({
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "environment_file": str(Path(env_file).resolve()), "records": records,
                    "limitation": "固定样本的语义检查仍需人工核对实际输出；结构化状态及来源均不证明任意图片关系正确。每图单次请求，无自动重试或回退。",
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
                self.assertTrue(result.success, result.error)
                self.assertTrue(all(checks.values()), checks)


if __name__ == "__main__":
    unittest.main()
