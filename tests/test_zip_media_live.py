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


zip_containers = importlib.import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
SAMPLES = Path(__file__).parent / "testFile"
MANIFEST = json.loads((SAMPLES / "zip_media_samples.json").read_text(encoding="utf-8"))
MEDIA_EXPECTED = json.loads((SAMPLES / "media_constructed.json").read_text(encoding="utf-8"))


@unittest.skipUnless(os.environ.get("ZIP_MEDIA_LIVE_TEST") == "1",
                     "Explicit ZIP_MEDIA_LIVE_TEST=1 and STEP_ENV_FILE required")
class ZipMediaLiveTests(unittest.TestCase):
    def test_real_stepfun_through_zip_public_entry(self):
        evidence_path = os.environ.get("ZIP_MEDIA_LIVE_EVIDENCE")
        self.assertTrue(evidence_path, "Set a new ZIP_MEDIA_LIVE_EVIDENCE output file")
        evidence = {
            "checked_at": datetime.now(timezone.utc).isoformat(), "records": [],
            "expected": {"transcript": MEDIA_EXPECTED["script"],
                         "visual_branches": MEDIA_EXPECTED["expected_branches"]},
            "limitation": "固定合成中文语音与审批图示短视频的定向验收；自动核验不能代替人工对照原媒体。"
                          "片段级时间不等于词级时间；说话人未知；不得推广为任意媒体的识别质量。",
        }
        with Path(evidence_path).open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        selection = os.environ.get("ZIP_MEDIA_LIVE_CASE")
        env_file = os.environ.get("STEP_ENV_FILE")
        evidence["preflight"] = {"selection_valid": selection in (None, "audio", "video", "both"),
                                 "explicit_env_file_exists": bool(env_file and Path(env_file).is_file())}
        Path(evidence_path).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8", newline="\n")
        self.assertTrue(all(evidence["preflight"].values()), evidence["preflight"])
        load_dotenv(dotenv_path=env_file, override=False)
        secrets = [os.environ.get(name) for name in ("STEP_API_KEY", "STEP_BASE_URL")]
        for case, filename, task in (("audio", "zip_media_live_audio.zip", "transcribe"),
                                     ("video", "zip_media_live_video.zip", "video"),
                                     ("both", "zip_media_live_video.zip", "both")):
            if selection and selection != case:
                continue
            sample = next(s for s in MANIFEST["archives"] if s["filename"] == filename)
            options = {"task": task}
            if task != "transcribe":
                options["question"] = MEDIA_EXPECTED["question"]
            started = time.perf_counter()
            result = zip_containers.convert_file(
                SAMPLES / filename, source="zip-media-live:" + case, parser_options={"media": options})
            member = result.members[0] if result.members else None
            native = member.result if member else None
            checks = {"zip_success": result.success, "member_count": len(result.members) == 2,
                      "archive_sha256": sha256((SAMPLES / filename).read_bytes()).hexdigest() == sample["sha256"],
                      "sibling_success": len(result.members) == 2 and result.members[1].status == "success",
                      "media_success": bool(native and native.success)}
            if native and native.success:
                checks.update({
                    "source_sha256": native.source.sha256 == sample["members"][0]["sha256"],
                    "member_source": member.source.member_path == sample["members"][0]["member_path"]
                                     and member.source.entry_index == 1
                                     and native.source.location == f"zip-media-live:{case}!/{member.source.member_path}#1",
                    "task": native.task == task,
                    "requires_review": native.requires_review,
                    "real_ranges": bool(native.segments) and all(
                        0 <= s.start_seconds < s.end_seconds <= native.source.duration_seconds
                        and s.time_precision == "segment" for s in native.segments),
                    "unknown_speakers": all(s.speaker is None for s in native.segments),
                    "modality_separation": {s.kind for s in native.segments} == (
                        {"audio", "video"} if task == "both" else {"audio" if task == "transcribe" else "video"}),
                })
                audio = re.sub(r"\s+", "", "".join(s.text for s in native.segments if s.kind == "audio"))
                video = re.sub(r"\s+", "", "".join(s.text for s in native.segments if s.kind == "video"))
                if task in ("transcribe", "both"):
                    checks.update({
                        "amount_condition": bool(re.search(r"超过.{0,8}(?:1万|一万|10000)", audio)),
                        "question_context": "是不是所有" in audio and "负责人审批" in audio,
                        "negation_and_other_branch": bool(re.search(r"不是.{0,30}其他.{0,15}财务.{0,8}审批", audio)),
                        "payment_denial": bool(re.search(r"未经批准.{0,6}不得付款", audio)),
                    })
                if task in ("video", "both"):
                    checks.update({
                        "above_10000_to_manager": bool(re.search(
                            r"(?<!不)(?<!未)(?:超过|大于|>).{0,8}(?:1万|一万|10000)元.{0,90}负责人.{0,15}审批", video)),
                        "other_to_finance": bool(re.search(
                            r"(?:其他|其它|不超过|未超过|小于等于|≤).{0,90}财务.{0,15}审批", video)),
                        "question": native.question == MEDIA_EXPECTED["question"],
                    })
            evidence["records"].append({
                "case": case, "archive": sample, "seconds": round(time.perf_counter() - started, 3),
                "result": result.to_dict(), "checks": checks,
                "automated_quality_passed": all(checks.values()), "manual_review": "pending",
            })
            Path(evidence_path).write_text(
                json.dumps(_sanitize(evidence, secrets), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n")
        for record in evidence["records"]:
            with self.subTest(case=record["case"]):
                self.assertTrue(record["automated_quality_passed"], record["checks"])


def _sanitize(value, secrets):
    """证据保留实际输出，但删除配置值及输出中可能携带的 URL。"""
    if isinstance(value, dict):
        return {key: _sanitize(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return re.sub(r"https?://[^\s\"<>]+", "[url redacted]", value)
    return value


if __name__ == "__main__":
    unittest.main()
