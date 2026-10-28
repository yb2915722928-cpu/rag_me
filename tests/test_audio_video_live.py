from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import unittest

from dotenv import load_dotenv

from tests.test_audio_video import MANIFEST, QUESTION, SAMPLES, media


@unittest.skipUnless(os.environ.get("STEP_MEDIA_LIVE_TEST") == "1",
                     "Explicit STEP_MEDIA_LIVE_TEST=1 and STEP_ENV_FILE required")
class AudioVideoLiveTests(unittest.TestCase):
    def test_fixed_media_with_real_stepfun(self):
        env_file = os.environ.get("STEP_ENV_FILE")
        self.assertTrue(env_file and Path(env_file).is_file(), "STEP_ENV_FILE must identify an existing .env")
        load_dotenv(dotenv_path=env_file, override=False)
        evidence = os.environ.get("STEP_MEDIA_LIVE_EVIDENCE")
        self.assertTrue(evidence, "Set STEP_MEDIA_LIVE_EVIDENCE to a new output file")
        self.assertFalse(Path(evidence).exists(), "Use a new evidence path to preserve prior runs")
        selection = os.environ.get("STEP_MEDIA_LIVE_CASE")
        self.assertIn(selection, (None, "audio", "both", "uncertain"))
        records = []
        for case, filename, task in (("audio", "media_rules.wav", "transcribe"),
                                      ("both", "media_rules.mp4", "both"),
                                      ("uncertain", "media_uncertain.mp4", "video")):
            if selection and selection != case:
                continue
            with self.subTest(case=case):
                print("Real StepFun media check: " + case, flush=True)
                started = time.perf_counter()
                result = media.convert_file(SAMPLES / filename, task=task,
                                            question=QUESTION if task != "transcribe" else None)
                checks = {"success": result.success, "requires_review": result.requires_review,
                          "original_identity": result.source.sha256 == next(
                              s["sha256"] for s in MANIFEST["samples"] if s["filename"] == filename)}
                if result.success:
                    audio = "".join(s.text for s in result.segments if s.kind == "audio")
                    video = "".join(s.text for s in result.segments if s.kind == "video")
                    if task in ("transcribe", "both"):
                        checks.update({
                            "amount_condition": bool(re.search(r"超过.{0,8}(?:1万|一万|10000)", audio)),
                            "question_context": "是不是所有" in audio and "负责人审批" in audio,
                            "negation_and_other_branch": bool(re.search(r"不是.{0,30}其他.{0,15}财务.{0,8}审批", audio)),
                            "payment_denial": bool(re.search(r"未经批准.{0,6}不得付款", audio)),
                            "unknown_speakers": all(s.speaker is None for s in result.segments),
                        })
                    if case == "both":
                        checks.update({
                            "above_10000_to_manager": bool(re.search(r"(?:超过|大于|>).{0,8}(?:1万|一万|10000)元.{0,90}负责人.{0,15}审批", video)),
                            "other_to_finance": bool(re.search(r"(?:其他|其它|不超过|未超过|小于等于|≤).{0,90}财务.{0,15}审批", video)),
                        })
                    if case == "uncertain":
                        checks["uncertain_status"] = result.status == "uncertain"
                        checks["explicit_unknown"] = bool(re.search(r"(?:无法|不能|不确定|难以).{0,18}(?:确认|确定|判断|对应)", video))
                        checks["reason"] = any(s.review_notes for s in result.segments)
                records.append({"case": case, "sample": filename,
                                "seconds": round(time.perf_counter() - started, 3),
                                "result": asdict(result), "checks": checks,
                                "quality_passed": all(checks.values())})
                Path(evidence).write_text(json.dumps({
                    "checked_at": datetime.now(timezone.utc).isoformat(), "records": records,
                    "limitation": "合成中文语音及固定短视频的定向验收，需对照原媒体核验，不代表任意音视频均准确。片段级时间，无自动说话人区分。",
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
                self.assertTrue(result.success, result.error)
                self.assertTrue(all(checks.values()), checks)


if __name__ == "__main__":
    unittest.main()
