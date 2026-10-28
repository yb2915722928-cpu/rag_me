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
MANIFEST = json.loads((SAMPLES / "image_provenance_samples.json").read_text(encoding="utf-8"))
CROP_HASH = next(sample["sha256"] for sample in MANIFEST["samples"]
                 if sample["filename"] == "image_provenance_crop.png")


@unittest.skipUnless(os.environ.get("STEP_PROVENANCE_LIVE_TEST") == "1",
                     "Explicit STEP_PROVENANCE_LIVE_TEST=1 and STEP_ENV_FILE required")
class ImageProvenanceLiveTests(unittest.TestCase):
    def test_real_crop_ocr_text_matches_original_region_through_file_and_bytes(self):
        env_file = os.environ.get("STEP_ENV_FILE")
        self.assertTrue(env_file and Path(env_file).is_file(), "STEP_ENV_FILE must identify the explicit .env")
        load_dotenv(dotenv_path=env_file, override=False)
        evidence = Path(os.environ.get("STEP_PROVENANCE_LIVE_EVIDENCE",
                                      str(SAMPLES / "image_provenance_live_evidence.json")))
        document = images.DocumentSource("payment-policy", "approved-2026-10", images.DocumentPosition("pdf_page", 3))
        crop = images.CropMapping("archive/payment-rules/source-image-01", 1200, 600, (120, 180, 1120, 440))
        path = SAMPLES / "image_provenance_crop.png"
        records = []
        for entry in ("file", "bytes"):
            with self.subTest(entry=entry):
                started = time.perf_counter()
                options = {"source": "acceptance/crop.png", "task": "ocr", "document": document,
                           "crop": crop, "is_cropped": True}
                result = (images.convert_file(path, **options) if entry == "file" else
                          images.convert_bytes(path.read_bytes(), format="png", **options))
                normalized = re.sub(r"[^\w]", "", result.text or "")
                checks = {
                    "success": result.success, "requires_review": result.requires_review,
                    "crop_title": "付款条件" in normalized,
                    "condition_number_and_approver": "金额超过1万元时须负责人审批" in normalized,
                    "negation": "未经批准不得付款" in normalized,
                    "outside_region_not_invented": "财务审批" not in normalized and "文档示例" not in normalized,
                    "document_source": result.source.document == document,
                    "original_region": result.source.crop == crop,
                    "cropped_input_dimensions": (result.source.width, result.source.height) == (1000, 260),
                    "input_byte_version": result.source.sha256 == CROP_HASH,
                }
                records.append({"entry": entry, "sample": path.name,
                                "seconds": round(time.perf_counter() - started, 3),
                                "result": asdict(result), "checks": checks,
                                "quality_passed": all(checks.values())})
                evidence.write_text(json.dumps({
                    "checked_at": datetime.now(timezone.utc).isoformat(), "environment_file": str(Path(env_file).resolve()),
                    "fixture_manifest": "image_provenance_samples.json", "records": records,
                    "manual_region_check": "Original 1200x600, bbox (120,180,1120,440), crop 1000x260; "
                                           "payment condition and negation lie inside; finance rule lies outside",
                    "limitation": "Only this fixed, axis-aligned crop is checked; provenance does not prove arbitrary OCR correct; "
                                  "no retries or fallback; caller retains original image and its access method",
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
                self.assertTrue(result.success, result.error)
                self.assertTrue(all(checks.values()), checks)


if __name__ == "__main__":
    unittest.main()
