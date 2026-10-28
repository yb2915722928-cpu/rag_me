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


@unittest.skipUnless(os.environ.get("STEP_OCR_LIVE_TEST") == "1",
                     "Explicit STEP_OCR_LIVE_TEST=1 and STEP_ENV_FILE required")
class StepFunOcrLiveTests(unittest.TestCase):
    def test_fixed_samples_preserve_conditions_negation_numbers_units_and_empty_state(self):
        env_file = os.environ.get("STEP_ENV_FILE")
        self.assertTrue(env_file and Path(env_file).is_file(), "STEP_ENV_FILE must name the explicit .env")
        load_dotenv(dotenv_path=env_file, override=False)
        records = []
        evidence_path = os.environ.get("STEP_OCR_LIVE_EVIDENCE")
        for name in ("image_ocr_rules.png", "image_ocr_rules.jpg", "image_ocr_rules.webp",
                     "image_ocr_blank.png", "image_ocr_stepfun_clear.png"):
            with self.subTest(sample=name):
                started = time.perf_counter()
                result = images.convert_file(SAMPLES / name, source=name, task="ocr")
                checks = {"success": result.success, "requires_review": result.requires_review}
                if result.success and name.startswith("image_ocr_rules"):
                    normalized = re.sub(r"[^\w]", "", result.text.lower())
                    for expected in ("金额超过1万元时须负责人审批", "其他情况由财务审批",
                                     "未经批准不得付款", "温度不得超过60c", "每30天检查一次"):
                        checks[expected] = expected in normalized
                elif result.success and name == "image_ocr_blank.png":
                    checks["normal_empty"] = result.status == "no_text" and result.text == ""
                elif result.success:
                    for label, number in (("A", "12"), ("B", "7"), ("C", "5")):
                        checks[f"{label}={number}"] = bool(re.search(
                            rf"{label}\s*[|:=：\s]+\s*{number}(?!\d)", result.text))
                records.append({"sample": name, "seconds": round(time.perf_counter() - started, 3),
                                "result": asdict(result), "checks": checks,
                                "quality_passed": all(checks.values())})
                if evidence_path:
                    Path(evidence_path).write_text(json.dumps({
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "environment_file": str(Path(env_file).resolve()),
                        "records": records,
                        "limitation": "仅验证固定样本；成功不代表任意图片的条件、否定和单位均正确，仍需核验。",
                    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
                self.assertTrue(result.success, result.error)
                self.assertTrue(all(checks.values()), checks)


if __name__ == "__main__":
    unittest.main()
