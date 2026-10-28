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


@unittest.skipUnless(os.environ.get("STEP_DESCRIPTION_LIVE_TEST") == "1",
                     "Explicit STEP_DESCRIPTION_LIVE_TEST=1 and STEP_ENV_FILE required")
class StepFunDescriptionLiveTests(unittest.TestCase):
    def test_fixed_scene_and_flowchart_have_relevant_themes_without_obvious_rule_expansion(self):
        env_file = os.environ.get("STEP_ENV_FILE")
        self.assertTrue(env_file and Path(env_file).is_file(), "STEP_ENV_FILE must name the explicit .env")
        load_dotenv(dotenv_path=env_file, override=False)
        evidence_path = Path(os.environ.get("STEP_DESCRIPTION_LIVE_EVIDENCE",
                                             SAMPLES / "image_description_live_evidence.json"))
        records = []
        for name in ("image_description_camping.png", "image_description_approval.png"):
            with self.subTest(sample=name):
                started = time.perf_counter()
                result = images.convert_file(SAMPLES / name, source=name, task="describe")
                checks = {"success": result.success, "requires_review": result.requires_review,
                          "nonempty_description": result.status == "content" and bool(result.text and result.text.strip())}
                if result.success:
                    text = result.text.lower()
                    if "camping" in name:
                        checks["camping_theme"] = any(word in text for word in ("露营", "野营", "营地", "帐篷", "camp", "tent"))
                        checks["landscape"] = any(word in text for word in ("湖", "山", "水", "lake", "mountain"))
                    else:
                        checks["payment_theme"] = any(word in text for word in ("付款", "支付", "payment"))
                        checks["approval_theme"] = any(word in text for word in ("审批", "审核", "approval"))
                        checks["no_obvious_universal_approver_claim"] = not re.search(
                            r"(?:所有|一律|均需|统一由|无论|不论|任何)[^。！？\n]{0,45}(?:负责人|财务)[^。！？\n]{0,12}(?:审批|审核)", text)
                records.append({"sample": name, "seconds": round(time.perf_counter() - started, 3),
                                "result": asdict(result), "checks": checks,
                                "quality_passed": all(checks.values())})
                evidence_path.write_text(json.dumps({
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "environment_file": str(Path(env_file).resolve()),
                    "records": records,
                    "limitation": "语义关键词及通用审批断言只作有限筛查，必须人工对照原图；不能检测所有扩写、遗漏或模型错误，固定样本不代表任意图片质量。",
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
                self.assertTrue(result.success, result.error)
                self.assertTrue(all(checks.values()), checks)


if __name__ == "__main__":
    unittest.main()
