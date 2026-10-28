from dataclasses import asdict
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import wave

from tests.test_audio_video import (
    MANIFEST, QUESTION, SAMPLES, TRANSCRIPT, VISUAL, media, media_server, video_reply,
)
from tests.image_test_support import image_server


class CombinedMediaExtraTests(unittest.TestCase):
    def test_both_file_and_bytes_preserve_the_same_source_and_modality_contract(self):
        path = SAMPLES / "media_rules.mp4"
        kwargs = dict(source="training:combined", task="both", question=QUESTION,
                      media_id="training", media_version="v2")
        with media_server() as (config, _):
            file_result = media.convert_file(path, config=config, **kwargs)
            byte_result = media.convert_bytes(path.read_bytes(), format="mp4", config=config, **kwargs)

        self.assertTrue(file_result.success, file_result.error)
        self.assertEqual(asdict(file_result), asdict(byte_result))
        self.assertEqual((file_result.source.location, file_result.source.media_id,
                          file_result.source.media_version, file_result.source.audio_stream_index),
                         ("training:combined", "training", "v2", 1))
        self.assertEqual(file_result.source.sha256,
                         next(s["sha256"] for s in MANIFEST["samples"] if s["filename"] == path.name))
        self.assertEqual((file_result.task, file_result.question, file_result.status),
                         ("both", QUESTION, "content"))
        self.assertEqual([(s.kind, s.text, s.status, s.requested_model, s.response_model, s.prompt_version)
                          for s in file_result.segments],
                         [("audio", TRANSCRIPT, "content", "stepaudio-2.5-asr", None, None),
                          ("video", VISUAL, "content", "step-5-preview", "step-5-preview-actual", "video-v1")])
        for segment in file_result.segments:
            self.assertEqual((segment.start_seconds, segment.time_precision, segment.speaker),
                             (0, "segment", None))
        self.assertIn(TRANSCRIPT, file_result.text)
        self.assertIn(VISUAL, file_result.text)
        self.assertTrue(file_result.requires_review)
        self.assertTrue(file_result.warnings)

    def test_different_slice_lengths_keep_delayed_video_and_audio_on_original_time(self):
        with media_server(asr={"text": ""}) as (config, requests):
            result = media.convert_file(
                SAMPLES / "video_extra_delayed.mp4", task="both", config=config,
                options=media.ProcessingOptions(audio_segment_seconds=2.5, video_segment_seconds=2))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source.duration_seconds, 6)
        self.assertEqual(result.status, "content")
        self.assertTrue(result.requires_review)
        self.assertEqual([s.kind for s in result.segments], ["audio", "video", "audio", "video", "audio"])
        self.assertEqual([r["path"] for r in requests],
                         ["/v1/audio/transcriptions", "/v1/chat/completions", "/v1/audio/transcriptions",
                          "/v1/chat/completions", "/v1/audio/transcriptions"])
        self.assertEqual([(s.start_seconds, s.end_seconds) for s in result.segments if s.kind == "video"],
                         [(1.25, 3.25), (3.25, 5.25)])
        audio_end, audio_samples, video_index = 0, 0, 0
        with TemporaryDirectory() as directory:
            for segment, request in zip(result.segments, requests, strict=True):
                self.assertEqual((segment.time_precision, segment.speaker), ("segment", None))
                if segment.kind == "audio":
                    with wave.open(BytesIO(request["media_bytes"])) as handle:
                        samples, rate = handle.getnframes(), handle.getframerate()
                    self.assertEqual((segment.status, segment.text), ("no_text", ""))
                    self.assertEqual(segment.start_seconds, audio_end)
                    self.assertAlmostEqual(segment.end_seconds - segment.start_seconds,
                                           samples / rate, delta=1 / 16000)
                    audio_end = segment.end_seconds
                    audio_samples += samples
                else:
                    path = Path(directory) / "clip.mp4"
                    path.write_bytes(request["media_bytes"])
                    pixel = subprocess.check_output([
                        "ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
                    self.assertEqual(len(pixel), 3)
                    channel = (0, 2)[video_index]
                    self.assertGreater(pixel[channel], 2 * max(pixel[(channel + 1) % 3],
                                                               pixel[(channel + 2) % 3]))
                    video_index += 1
        self.assertEqual((audio_end, audio_samples), (6, 96000))

    def test_video_failure_after_successful_audio_discards_all_combined_content(self):
        path = SAMPLES / "video_extra_delayed.mp4"
        kwargs = dict(source="training:failed-combined", task="both", question=QUESTION,
                      media_id="training", media_version="v3",
                      options=media.ProcessingOptions(audio_segment_seconds=2.5, video_segment_seconds=2))
        with media_server(fail_at=4) as (config, requests):
            file_result = media.convert_file(path, config=config, **kwargs)
            file_requests = list(requests)
            requests.clear()
            byte_result = media.convert_bytes(path.read_bytes(), format="mp4", config=config, **kwargs)

        self.assertEqual(asdict(file_result), asdict(byte_result))
        for sent in (file_requests, requests):
            self.assertEqual([r["path"] for r in sent],
                             ["/v1/audio/transcriptions", "/v1/chat/completions",
                              "/v1/audio/transcriptions", "/v1/chat/completions"])
        self.assertFalse(file_result.success)
        self.assertEqual(file_result.status, "failed")
        self.assertIsNone(file_result.text)
        self.assertEqual(file_result.segments, [])
        self.assertEqual((file_result.error.code, file_result.error.stage,
                          file_result.error.start_seconds, file_result.error.http_status),
                         ("service_error", "video", 3.25, 503))
        self.assertEqual((file_result.source.location, file_result.source.media_id,
                          file_result.source.media_version, file_result.source.audio_stream_index,
                          file_result.source.duration_seconds),
                         ("training:failed-combined", "training", "v3", 1, 6))
        self.assertEqual(file_result.source.sha256,
                         "1690dcf6a6910eb3e7f6501a6ac06f97adf2340a309ceaa86084949071821d7c")
        self.assertEqual(file_result.question, QUESTION)

    def test_combined_cli_passes_question_slice_lengths_and_independent_runtime_models(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                record = {"path": self.path, "authorization": self.headers.get("Authorization")}
                if self.path == "/v1/audio/transcriptions":
                    message = BytesParser(policy=default).parsebytes(
                        ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode() + raw)
                    parts = {p.get_param("name", header="Content-Disposition"): p.get_payload(decode=True)
                             for p in message.iter_parts()}
                    record["model"] = parts["model"].decode("utf-8")
                    reply = {"text": TRANSCRIPT}
                else:
                    record["body"] = json.loads(raw)
                    reply = video_reply()
                requests.append(record)
                data = json.dumps(reply).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        environment = {k: v for k, v in os.environ.items() if not k.startswith("STEP_")}
        environment.update(STEP_API_KEY="runtime-test-key", STEP_MODEL="runtime-video-model")
        with image_server(Handler) as url, TemporaryDirectory() as directory:
            env_file = Path(directory) / "combined-cli.env"
            env_file.write_text(
                f"STEP_API_KEY=file-test-key\nSTEP_BASE_URL={url}\n"
                "STEP_ASR_MODEL=file-asr-model\nSTEP_MODEL=file-video-model\n", encoding="utf-8")
            run = subprocess.run([
                sys.executable, "-m", media.__name__, str(SAMPLES / "video_extra_delayed.mp4"),
                "--task", "both", "--env-file", str(env_file), "--question", QUESTION,
                "--source", "cli:combined", "--format", "mp4", "--audio-seconds", "2.5",
                "--video-seconds", "2", "--timeout", "2"],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                capture_output=True, encoding="utf-8", timeout=15, check=False)

        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual((result["task"], result["question"], result["source"]["location"]),
                         ("both", QUESTION, "cli:combined"))
        self.assertEqual([s["kind"] for s in result["segments"]],
                         ["audio", "video", "audio", "video", "audio"])
        self.assertEqual([(s["start_seconds"], s["end_seconds"]) for s in result["segments"]
                          if s["kind"] == "video"], [(1.25, 3.25), (3.25, 5.25)])
        self.assertEqual(len(requests), 5)
        for segment, request in zip(result["segments"], requests, strict=True):
            self.assertEqual(request["authorization"], "Bearer runtime-test-key")
            if segment["kind"] == "audio":
                self.assertEqual(request["path"], "/v1/audio/transcriptions")
                self.assertEqual((segment["requested_model"], request["model"]),
                                 ("file-asr-model", "file-asr-model"))
            else:
                self.assertEqual(request["path"], "/v1/chat/completions")
                self.assertEqual((segment["requested_model"], request["body"]["model"]),
                                 ("runtime-video-model", "runtime-video-model"))
                self.assertIn(QUESTION, request["body"]["messages"][0]["content"][1]["text"])
        self.assertIn(TRANSCRIPT, result["text"])
        self.assertIn(VISUAL, result["text"])
        self.assertTrue(result["review_issues"])
        self.assertNotIn("runtime-test-key", run.stdout + run.stderr)
        self.assertNotIn("file-test-key", run.stdout + run.stderr)

    def test_combined_cli_honors_timeout_and_returns_failed_json_without_partial_content(self):
        environment = {k: v for k, v in os.environ.items() if not k.startswith("STEP_")}
        with media_server(delay=0.15) as (config, requests), TemporaryDirectory() as directory:
            env_file = Path(directory) / "combined-cli.env"
            env_file.write_text(
                f"STEP_API_KEY=test-key\nSTEP_BASE_URL={config.base_url}\n"
                "STEP_ASR_MODEL=stepaudio-2.5-asr\nSTEP_MODEL=step-5-preview\n", encoding="utf-8")
            run = subprocess.run([
                sys.executable, "-m", media.__name__, str(SAMPLES / "media_rules.mp4"),
                "--task", "both", "--env-file", str(env_file), "--source", "cli:timeout",
                "--timeout", "0.03"], cwd=Path(__file__).resolve().parents[1], env=environment,
                capture_output=True, encoding="utf-8", timeout=15, check=False)

        self.assertEqual(run.returncode, 1, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["text"])
        self.assertEqual(result["segments"], [])
        self.assertEqual((result["error"]["code"], result["error"]["stage"], result["error"]["start_seconds"]),
                         ("timeout", "audio", 0))
        self.assertEqual(result["source"]["location"], "cli:timeout")
        self.assertEqual(result["source"]["sha256"],
                         next(s["sha256"] for s in MANIFEST["samples"] if s["filename"] == "media_rules.mp4"))
        self.assertEqual([r["path"] for r in requests], ["/v1/audio/transcriptions"])
        self.assertNotIn("test-key", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
