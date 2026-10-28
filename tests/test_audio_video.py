import base64
from contextlib import contextmanager
from dataclasses import asdict, replace
from email.parser import BytesParser
from email.policy import default
from hashlib import sha256
from http.server import BaseHTTPRequestHandler
import importlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
import wave

from tests.image_test_support import image_server


media = importlib.import_module("app.modules.1_documentIngestionAndParsing.7_audioAndVideoProcessing")
SAMPLES = Path(__file__).parent / "testFile"
MANIFEST = json.loads((SAMPLES / "media_constructed.json").read_text(encoding="utf-8"))
QUESTION = MANIFEST["question"]
TRANSCRIPT = MANIFEST["script"]
VISUAL = "金额超过1万元由负责人审批；其他情况由财务审批。"


def video_reply(text=VISUAL, status="content", notes=None):
    return {"model": "step-5-preview-actual", "choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"status": status, "text": text, "review_notes": notes or []})}}]}


@contextmanager
def media_server(*, asr=None, video=None, http_status=200, fail_at=None, delay=0):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            record = {"path": self.path}
            valid = self.headers.get("Authorization") == "Bearer test-key"
            if self.path == "/v1/audio/transcriptions":
                message = BytesParser(policy=default).parsebytes(
                    ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode() + raw)
                parts = {p.get_param("name", header="Content-Disposition"): p.get_payload(decode=True)
                         for p in message.iter_parts()}
                valid = valid and parts.get("model") == b"stepaudio-2.5-asr"
                valid = valid and parts.get("response_format") == b"json"
                with wave.open(BytesIO(parts["file"])) as handle:
                    valid = valid and (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) == (1, 2, 16000)
                    record["duration"] = handle.getnframes() / handle.getframerate()
                record["media_bytes"] = parts["file"]
                reply = {"text": TRANSCRIPT} if asr is None else asr
            elif self.path == "/v1/chat/completions":
                body = json.loads(raw)
                record["body"] = body
                parts = body["messages"][0]["content"]
                valid = valid and body["model"] == "step-5-preview" and body["stream"] is False
                valid = valid and body["response_format"]["json_schema"]["strict"] is True
                valid = valid and parts[0]["type"] == "video_url" and parts[1]["type"] == "text"
                prefix, encoded = parts[0]["video_url"]["url"].split(";base64,")
                valid = valid and prefix == "data:video/mp4"
                record["media_bytes"] = base64.b64decode(encoded, validate=True)
                reply = video_reply() if video is None else video
            else:
                valid, reply = False, {}
            requests.append(record)
            data = reply if isinstance(reply, bytes) else json.dumps(reply).encode("utf-8")
            time.sleep(delay)
            status = 503 if fail_at == len(requests) else http_status
            self.send_response(status if valid else 400)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    with image_server(Handler) as url:
        yield media.StepFunConfig(api_key="test-key", base_url=url, asr_model="stepaudio-2.5-asr",
                                  video_model="step-5-preview", timeout=2), requests


class AudioVideoTests(unittest.TestCase):
    def test_fixed_sample_versions(self):
        for sample in MANIFEST["samples"]:
            with self.subTest(sample=sample["filename"]):
                data = (SAMPLES / sample["filename"]).read_bytes()
                self.assertEqual(len(data), sample["bytes"])
                self.assertEqual(sha256(data).hexdigest(), sample["sha256"])

    def test_audio_formats_use_real_wav_and_unknown_speakers(self):
        for format in ("wav", "mp3", "m4a", "ogg", "flac"):
            with self.subTest(format=format), media_server() as (config, requests):
                result = media.convert_file(SAMPLES / ("media_rules." + format), task="transcribe", config=config)
                self.assertTrue(result.success, result.error)
                self.assertIn("不是", result.text)
                self.assertEqual(len(requests), 1)
                self.assertEqual(result.segments[0].time_precision, "segment")
                self.assertIsNone(result.segments[0].speaker)
                self.assertIsNone(result.segments[0].response_model)
                self.assertTrue(result.requires_review)

    def test_file_and_bytes_have_same_contract_and_original_identity(self):
        path = SAMPLES / "media_rules.wav"
        with media_server() as (config, _):
            first = media.convert_file(path, task="transcribe", source="recording", config=config,
                                       media_id="course", media_version="v2")
            second = media.convert_bytes(path.read_bytes(), format="wav", source="recording",
                                        task="transcribe", config=config, media_id="course", media_version="v2")
        self.assertTrue(first.success, first.error)
        self.assertEqual(asdict(first), asdict(second))
        self.assertEqual(first.source.sha256, sha256(path.read_bytes()).hexdigest())
        self.assertEqual(first.source.media_version, "v2")

    def test_audio_segments_use_actual_sample_ranges_and_last_segment(self):
        with media_server() as (config, requests):
            result = media.convert_file(SAMPLES / "media_rules.wav", task="transcribe", config=config,
                                        options=media.ProcessingOptions(audio_segment_seconds=5))
        self.assertTrue(result.success, result.error)
        self.assertGreater(len(result.segments), 2)
        for index, (segment, request) in enumerate(zip(result.segments, requests, strict=True)):
            self.assertAlmostEqual(segment.end_seconds - segment.start_seconds, request["duration"], delta=1 / 16000 + 0.000001)
            if index:
                self.assertAlmostEqual(segment.start_seconds, result.segments[index - 1].end_seconds)
        self.assertAlmostEqual(result.segments[-1].end_seconds, result.source.duration_seconds, delta=1 / 16000)

    def test_video_copies_b_frames_without_fictional_uniform_cutpoints(self):
        for filename in ("media_timeline.mp4", "media_offset.mp4", "media_timeline.mov", "media_timeline.mkv"):
            with self.subTest(filename=filename), media_server() as (config, requests):
                result = media.convert_file(SAMPLES / filename, task="video", config=config,
                                            options=media.ProcessingOptions(video_segment_seconds=2))
                self.assertTrue(result.success, result.error)
                self.assertEqual([(s.start_seconds, s.end_seconds) for s in result.segments], [(0, 3), (3, 6)])
                self.assertAlmostEqual(result.source.duration_seconds, 6)
                with TemporaryDirectory() as directory:
                    for index, request in enumerate(requests):
                        path = Path(directory) / "clip.mp4"
                        path.write_bytes(request["media_bytes"])
                        pixel = subprocess.check_output([
                            "ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1",
                            "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
                        self.assertEqual(len(pixel), 3)
                        self.assertGreater(pixel[index], max(pixel[(index + 1) % 3], pixel[(index + 2) % 3]) * 2)

    def test_video_question_uncertainty_and_response_model_are_preserved(self):
        with media_server(video=video_reply("节点被截断，无法确认审批人。", "uncertain", ["缺少终点"])) as (config, requests):
            result = media.convert_file(SAMPLES / "media_uncertain.mp4", task="video", question=QUESTION, config=config)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.question, QUESTION)
        self.assertIn(QUESTION, requests[0]["body"]["messages"][0]["content"][1]["text"])
        self.assertEqual(result.segments[0].response_model, "step-5-preview-actual")
        self.assertEqual(result.segments[0].review_notes, ["缺少终点"])
        self.assertTrue(result.requires_review)

    def test_combined_mode_keeps_modalities_and_source_separate(self):
        with media_server() as (config, requests):
            result = media.convert_file(SAMPLES / "media_rules.mp4", task="both", question=QUESTION, config=config,
                                        options=media.ProcessingOptions(audio_segment_seconds=5, video_segment_seconds=6))
        self.assertTrue(result.success, result.error)
        self.assertEqual({s.kind for s in result.segments}, {"audio", "video"})
        self.assertEqual(result.segments, sorted(result.segments, key=lambda s: (s.start_seconds, s.kind)))
        self.assertIn("语音转写", result.text)
        self.assertIn("画面信息", result.text)
        self.assertEqual(result.source.audio_stream_index, 1)
        self.assertEqual(len(requests), len(result.segments))

    def test_video_bytes_match_file_entry(self):
        path = SAMPLES / "media_timeline.mp4"
        with media_server() as (config, _):
            first = media.convert_file(path, source="movie", task="video", config=config)
            second = media.convert_bytes(path.read_bytes(), source="movie", format="mp4", task="video", config=config)
        self.assertTrue(first.success, first.error)
        self.assertEqual(asdict(first), asdict(second))

    def test_transcribe_video_avoids_visual_api_and_visual_config(self):
        with media_server() as (config, requests):
            result = media.convert_file(SAMPLES / "media_rules.mp4", task="transcribe",
                                        config=replace(config, video_model=None))
        self.assertTrue(result.success, result.error)
        self.assertTrue(all(r["path"].endswith("/audio/transcriptions") for r in requests))

    def test_empty_transcription_is_normal_but_still_requires_review(self):
        with media_server(asr={"text": ""}) as (config, _):
            result = media.convert_file(SAMPLES / "media_silence.wav", task="transcribe", config=config)
        self.assertTrue(result.success, result.error)
        self.assertEqual((result.status, result.text), ("no_text", ""))
        self.assertTrue(result.requires_review)
        self.assertEqual(result.segments[0].status, "no_text")

    def test_missing_audio_fails_only_for_tasks_that_require_it(self):
        with media_server() as (config, requests):
            for task in ("transcribe", "both"):
                result = media.convert_file(SAMPLES / "media_timeline.mp4", task=task, config=config)
                self.assertEqual(result.error.code, "missing_audio")
                self.assertIsNone(result.text)
                self.assertEqual(result.segments, [])
            self.assertEqual(requests, [])

    def test_input_failures_are_diagnostics_and_do_not_call_api(self):
        with media_server() as (config, requests):
            for path, kwargs, code in (
                (SAMPLES / "media_corrupt.mp4", {}, "media_tool_error"),
                (SAMPLES / "absent.wav", {}, "file_read_error"),
                (SAMPLES / "media_rules.wav", {"format": "mp3"}, "format_mismatch"),
                (SAMPLES / "media_rules.wav", {"question": "why"}, "invalid_options"),
                (SAMPLES / "media_rules.wav", {"options": media.ProcessingOptions(audio_segment_seconds=float("nan"))}, "invalid_options"),
                (SAMPLES / "media_rules.wav", {"options": media.ProcessingOptions(ffprobe="missing-rag-ffprobe")}, "missing_media_tool"),
                (SAMPLES / "media_rules.wav", {"options": media.ProcessingOptions(ffmpeg="missing-rag-ffmpeg")}, "missing_media_tool"),
            ):
                with self.subTest(path=path, code=code):
                    result = media.convert_file(path, task="transcribe", config=config, **kwargs)
                    self.assertFalse(result.success)
                    self.assertIsNone(result.text)
                    self.assertEqual(result.error.code, code)
            self.assertEqual(requests, [])

    def test_missing_config_is_not_loaded_implicitly(self):
        environment = {k: v for k, v in os.environ.items() if not k.startswith("STEP_")}
        with patch.dict(os.environ, environment, clear=True):
            result = media.convert_file(SAMPLES / "media_rules.wav", task="transcribe")
        self.assertEqual(result.error.code, "missing_config")
        self.assertIsNotNone(result.source.sha256)

    def test_http_failures_do_not_expose_credentials_or_error_body(self):
        for status, code in ((401, "authentication_error"), (429, "rate_limited"), (503, "service_error")):
            with self.subTest(status=status), media_server(http_status=status, asr=b"test-key secret body") as (config, _):
                result = media.convert_file(SAMPLES / "media_rules.wav", task="transcribe", config=config)
                self.assertEqual(result.error.code, code)
                self.assertEqual(result.error.http_status, status)
                self.assertIsNone(result.text)
                self.assertNotIn("test-key", str(asdict(result)))

    def test_invalid_responses_cannot_become_empty_success(self):
        for asr in ({}, {"text": None}, b"not JSON"):
            with self.subTest(asr=asr), media_server(asr=asr) as (config, _):
                result = media.convert_file(SAMPLES / "media_rules.wav", task="transcribe", config=config)
                self.assertEqual(result.error.code, "protocol_error")
                self.assertIsNone(result.text)
        broken = video_reply()
        broken["choices"][0]["finish_reason"] = "length"
        for video in ({}, [], broken, video_reply("unknown", "uncertain")):
            with self.subTest(video=video), media_server(video=video) as (config, _):
                result = media.convert_file(SAMPLES / "media_timeline.mp4", task="video", config=config)
                self.assertEqual(result.error.code, "protocol_error")
                self.assertEqual(result.segments, [])

    def test_midway_failure_never_exposes_partial_success(self):
        with media_server(fail_at=2) as (config, requests):
            result = media.convert_file(SAMPLES / "media_rules.wav", task="transcribe", config=config,
                                        options=media.ProcessingOptions(audio_segment_seconds=5))
        self.assertEqual(len(requests), 2)
        self.assertFalse(result.success)
        self.assertIsNone(result.text)
        self.assertEqual(result.segments, [])
        self.assertGreater(result.error.start_seconds, 0)
        self.assertEqual(result.error.stage, "audio")
        self.assertIsNotNone(result.source.sha256)

    def test_timeout_is_a_diagnostic(self):
        with media_server(delay=0.15) as (config, _):
            result = media.convert_file(SAMPLES / "media_rules.wav", task="transcribe", config=replace(config, timeout=0.03))
        self.assertEqual(result.error.code, "timeout")
        self.assertIsNone(result.text)

    def test_cli_loads_explicit_environment_and_emits_json(self):
        with media_server() as (config, _), TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(f"STEP_API_KEY=test-key\nSTEP_BASE_URL={config.base_url}\n", encoding="utf-8")
            environment = {k: v for k, v in os.environ.items() if not k.startswith("STEP_")}
            command = [os.sys.executable, "-m", media.__name__, str(SAMPLES / "media_rules.wav"),
                       "--task", "transcribe", "--env-file", str(env_file)]
            run = subprocess.run(command, capture_output=True, encoding="utf-8", env=environment, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["status"], "content")
        self.assertIn("不是", result["text"])
        self.assertNotIn("test-key", run.stdout)


if __name__ == "__main__":
    unittest.main()
