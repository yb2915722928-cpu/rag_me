from hashlib import sha256
import importlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave
from zipfile import ZipFile

from tests.test_audio_video import QUESTION, TRANSCRIPT, VISUAL, media_server, video_reply


zip_containers = importlib.import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
SAMPLES = Path(__file__).parent / "testFile"
MANIFEST = json.loads((SAMPLES / "zip_media_samples.json").read_text(encoding="utf-8"))


class ZipMediaTests(unittest.TestCase):
    def setUp(self):
        environment = {k: v for k, v in os.environ.items() if not k.startswith("STEP_")}
        self.enterContext(patch.dict(os.environ, environment, clear=True))

    def test_audio_formats_preserve_native_transcript_identity_and_member_source(self):
        with media_server() as (config, requests):
            result = zip_containers.convert_file(
                SAMPLES / "zip_media_audio.zip", source="training.zip",
                parser_options={"media": {"task": "transcribe", "config": config,
                                          "media_id": "course", "media_version": "v2"}})

        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.counts, dict(total=6, success=6, failed=0, ignored=0, unprocessed=0))
        expected = MANIFEST["archives"][0]["members"]
        self.assertEqual(len(requests), 5)
        for index, member in enumerate(result.members[:-1], 1):
            native = member.result
            self.assertEqual(member.result_kind, "media")
            self.assertEqual((member.source.container, member.source.entry_index), ("training.zip", index))
            self.assertEqual(native.source.location, f"training.zip!/{member.source.member_path}#{index}")
            self.assertEqual(native.source.sha256, expected[index - 1]["sha256"])
            self.assertEqual((native.source.media_id, native.source.media_version), ("course", "v2"))
            self.assertEqual((native.task, native.status), ("transcribe", "content"))
            self.assertEqual(native.segments[0].text, TRANSCRIPT)
            self.assertEqual((native.segments[0].kind, native.segments[0].speaker,
                              native.segments[0].time_precision), ("audio", None, "segment"))
            self.assertTrue(native.warnings)
            self.assertTrue(native.requires_review)
        self.assertEqual(result.members[-1].result.markdown, "其他成员仍可独立读取。")

    def test_json_options_and_file_bytes_keep_real_delayed_combined_ranges(self):
        path = SAMPLES / "zip_media_delayed.zip"
        with media_server() as (config, requests):
            options = {"media": {"task": "both", "question": QUESTION,
                                  "config": {"api_key": "test-key", "base_url": config.base_url,
                                             "video_model": "step-5-preview", "timeout": 2},
                                  "options": {"audio_segment_seconds": 2.5, "video_segment_seconds": 2}}}
            file_result = zip_containers.convert_file(path, source="delayed.zip", parser_options=options)
            byte_result = zip_containers.convert_bytes(
                path.read_bytes(), source="delayed.zip", parser_options=options)

        self.assertTrue(file_result.success, file_result.to_dict())
        self.assertEqual(file_result.to_dict(), byte_result.to_dict())
        native = file_result.members[0].result
        self.assertEqual((native.task, native.question, native.source.duration_seconds), ("both", QUESTION, 6))
        self.assertEqual([s.kind for s in native.segments], ["audio", "video", "audio", "video", "audio"])
        self.assertEqual([(s.start_seconds, s.end_seconds) for s in native.segments if s.kind == "video"],
                         [(1.25, 3.25), (3.25, 5.25)])
        audio_end = 0
        video_index = 0
        for segment, request in zip(native.segments, requests[:5], strict=True):
            if segment.kind == "audio":
                with wave.open(BytesIO(request["media_bytes"])) as handle:
                    duration = handle.getnframes() / handle.getframerate()
                self.assertEqual(segment.start_seconds, audio_end)
                self.assertAlmostEqual(segment.end_seconds - segment.start_seconds, duration, delta=1 / 16000)
                audio_end = segment.end_seconds
            else:
                with TemporaryDirectory() as directory:
                    clip = Path(directory) / "clip.mp4"
                    clip.write_bytes(request["media_bytes"])
                    pixel = subprocess.check_output([
                        "ffmpeg", "-v", "error", "-i", str(clip), "-frames:v", "1",
                        "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
                self.assertEqual(len(pixel), 3)
                channel = (0, 2)[video_index]
                self.assertGreater(pixel[channel], 2 * max(pixel[(channel + 1) % 3], pixel[(channel + 2) % 3]))
                video_index += 1
        self.assertEqual(audio_end, 6)
        self.assertIn(TRANSCRIPT, native.text)
        self.assertIn(VISUAL, native.text)
        for segment in native.segments:
            self.assertEqual((segment.time_precision, segment.speaker), ("segment", None))
            self.assertEqual(segment.requested_model,
                             "stepaudio-2.5-asr" if segment.kind == "audio" else "step-5-preview")
        self.assertEqual([r["path"] for r in requests[:5]],
                         ["/v1/audio/transcriptions", "/v1/chat/completions", "/v1/audio/transcriptions",
                          "/v1/chat/completions", "/v1/audio/transcriptions"])
        self.assertIn(QUESTION, requests[1]["body"]["messages"][0]["content"][1]["text"])
        report = file_result.to_dict()
        self.assertTrue(report["requires_review"])
        self.assertTrue(report["members"][0]["result"]["requires_review"])
        self.assertTrue(report["members"][0]["result"]["success"])
        self.assertNotIn("test-key", json.dumps(report))

    def test_missing_task_question_or_config_fails_only_media_member(self):
        with media_server() as (config, requests):
            for media_options, code, message in (
                ({"config": config}, "invalid_options", "task"),
                ({"task": "video", "config": config}, "invalid_options", "question"),
                ({"task": "both", "config": config}, "invalid_options", "question"),
                ({"task": "transcribe"}, "missing_config", "STEP_API_KEY"),
                ({"task": "video", "question": QUESTION,
                  "config": {"api_key": "test-key", "base_url": config.base_url}},
                 "missing_config", "STEP_MODEL"),
            ):
                with self.subTest(code=code, message=message):
                    result = zip_containers.convert_file(
                        SAMPLES / "zip_media_delayed.zip", parser_options={"media": media_options})
                    member = result.members[0]
                    self.assertEqual(result.status, "partial_success")
                    self.assertEqual((member.status, member.result_kind), ("failed", "media"))
                    self.assertEqual(member.result.error.code, code)
                    self.assertIn(message, member.error)
                    self.assertEqual(member.result.segments, [])
                    self.assertIsNone(member.result.text)
                    self.assertEqual(result.members[1].status, "success")
        self.assertEqual(len(requests), 0)

    def test_video_formats_preserve_uncertain_native_state_and_json_review(self):
        text = "只能看到局部画面，无法确认分支关系。"
        with media_server(video=video_reply(text, "uncertain", ["需对照原始画面"])) as (config, requests):
            result = zip_containers.convert_bytes(
                (SAMPLES / "zip_media_video.zip").read_bytes(), source="video.zip",
                parser_options={"media": {"task": "video", "question": QUESTION, "config": config}})

        self.assertTrue(result.success, result.to_dict())
        self.assertEqual([m.format for m in result.members[:-1]], ["mp4", "mov", "mkv"])
        self.assertEqual(len(requests), 3)
        for member in result.to_dict()["members"][:-1]:
            native = member["result"]
            self.assertEqual((member["status"], native["status"], native["task"]),
                             ("success", "uncertain", "video"))
            self.assertTrue(native["success"])
            self.assertTrue(native["requires_review"])
            segment = native["segments"][0]
            self.assertEqual((segment["kind"], segment["text"], segment["review_notes"]),
                             ("video", text, ["需对照原始画面"]))
            self.assertEqual((segment["start_seconds"], segment["end_seconds"], segment["time_precision"]),
                             (0, 6, "segment"))
            self.assertEqual((segment["requested_model"], segment["response_model"], segment["prompt_version"]),
                             ("step-5-preview", "step-5-preview-actual", "video-v1"))

    def test_empty_transcription_remains_success_and_requires_review(self):
        with media_server(asr={"text": ""}) as (config, _):
            result = zip_containers.convert_file(
                SAMPLES / "zip_media_silence.zip",
                parser_options={"media": {"task": "transcribe", "config": config}})
        self.assertTrue(result.success, result.to_dict())
        native = result.members[0].result
        self.assertEqual((native.status, native.text, native.segments[0].status), ("no_text", "", "no_text"))
        self.assertTrue(native.requires_review)
        self.assertTrue(native.warnings)

    def test_later_api_failure_discards_all_segments_for_each_task_and_keeps_sibling(self):
        for task, fail_at, stage, start in (("transcribe", 2, "audio", 2.56),
                                           ("video", 2, "video", 3.25),
                                           ("both", 4, "video", 3.25)):
            with self.subTest(task=task), media_server(fail_at=fail_at) as (config, requests):
                result = zip_containers.convert_bytes(
                    (SAMPLES / "zip_media_delayed.zip").read_bytes(), source="failed.zip",
                    parser_options={"media": {"task": task, "config": config,
                                              "question": None if task == "transcribe" else QUESTION,
                                              "options": {"audio_segment_seconds": 2.5,
                                                          "video_segment_seconds": 2}}})
            self.assertEqual(result.status, "partial_success")
            native = result.members[0].result
            self.assertIsNone(native.text)
            self.assertEqual(native.segments, [])
            self.assertEqual((native.error.code, native.error.stage, native.error.http_status),
                             ("service_error", stage, 503))
            self.assertAlmostEqual(native.error.start_seconds, start)
            self.assertEqual(native.source.sha256, "1690dcf6a6910eb3e7f6501a6ac06f97adf2340a309ceaa86084949071821d7c")
            self.assertEqual(len(requests), fail_at)
            self.assertEqual(result.members[1].status, "success")
            self.assertEqual(result.members[1].result.markdown, "其他成员仍可独立读取。")

    def test_probe_and_remux_failures_keep_following_media_member(self):
        with media_server() as (config, requests):
            result = zip_containers.convert_file(
                SAMPLES / "zip_media_failures.zip",
                parser_options={"media": {"task": "video", "question": QUESTION, "config": config}})
        self.assertEqual(result.status, "partial_success")
        self.assertEqual([m.status for m in result.members], ["failed", "failed", "success", "success"])
        self.assertEqual([m.result.error.stage for m in result.members[:2]], ["probe", "prepare"])
        for member in result.members[:2]:
            self.assertEqual(member.result.error.code, "media_tool_error")
            self.assertIsNone(member.result.text)
            self.assertEqual(member.result.segments, [])
        self.assertEqual(result.members[2].result.segments[0].text, VISUAL)
        self.assertEqual(len(requests), 1)

    def test_cli_uses_runtime_models_and_cleans_temporary_input_and_clips(self):
        for fail_at, tool_option, expected_exit, error_stage in (
            (None, {}, 0, None), (4, {}, 2, "video"),
            (None, {"ffprobe": "zip-media-missing-ffprobe"}, 2, "probe"),
            (None, {"ffmpeg": "zip-media-missing-ffmpeg"}, 2, "prepare"),
        ):
            with self.subTest(fail_at=fail_at, stage=error_stage), media_server(fail_at=fail_at) as (config, requests), TemporaryDirectory() as directory:
                environment = dict(os.environ, STEP_API_KEY="test-key", STEP_BASE_URL=config.base_url,
                                   STEP_MODEL="step-5-preview", TMP=directory, TEMP=directory, TMPDIR=directory)
                options = {"media": {"task": "both", "question": QUESTION,
                                      "options": {"audio_segment_seconds": 2.5, "video_segment_seconds": 2,
                                                  **tool_option}}}
                run = subprocess.run([
                    sys.executable, "-m", zip_containers.__name__, str(SAMPLES / "zip_media_delayed.zip"),
                    "--source", "cli.zip", "--parser-options", json.dumps(options)],
                    cwd=Path(__file__).resolve().parents[1], env=environment,
                    capture_output=True, encoding="utf-8", timeout=20, check=False)
                self.assertEqual(run.returncode, expected_exit, run.stderr)
                report = json.loads(run.stdout)
                native = report["members"][0]["result"]
                self.assertEqual(native["source"]["location"], "cli.zip!/片段/延迟.mp4#1")
                self.assertEqual(native["task"], "both")
                self.assertEqual(report["members"][1]["status"], "success")
                if error_stage:
                    self.assertEqual((native["text"], native["segments"]), (None, []))
                    self.assertEqual(native["error"]["stage"], error_stage)
                else:
                    self.assertTrue(native["success"])
                    self.assertEqual(native["segments"][0]["requested_model"], "stepaudio-2.5-asr")
                    self.assertEqual(native["segments"][1]["requested_model"], "step-5-preview")
                self.assertEqual(list(Path(directory).iterdir()), [])
                self.assertNotIn("test-key", run.stdout + run.stderr)
                self.assertNotIn(config.base_url, run.stdout + run.stderr)
                self.assertEqual(len(requests), 0 if tool_option else 4 if fail_at else 5)

    def test_invalid_mapping_options_fail_visibly_without_echoing_configuration(self):
        for extra in ({"config": {"unexpected": "DO_NOT_ECHO"}},
                      {"options": {"unexpected": "DO_NOT_ECHO"}},
                      {"options": {"audio_segment_seconds": 0}}):
            with self.subTest(option=next(iter(extra))):
                result = zip_containers.convert_file(
                    SAMPLES / "zip_media_delayed.zip",
                    parser_options={"media": {"task": "transcribe", **extra}})
                self.assertEqual(result.status, "partial_success")
                self.assertEqual(result.members[0].result.error.code, "invalid_options")
                self.assertNotIn("DO_NOT_ECHO", json.dumps(result.to_dict()))

    def test_fixed_archives_and_member_versions_match_manifest(self):
        for archive in MANIFEST["archives"]:
            path = SAMPLES / archive["filename"]
            with self.subTest(archive=path.name), ZipFile(path) as container:
                self.assertEqual((path.stat().st_size, sha256(path.read_bytes()).hexdigest()),
                                 (archive["bytes"], archive["sha256"]))
                self.assertEqual(container.namelist(), [m["member_path"] for m in archive["members"]])
                for member in archive["members"]:
                    data = container.read(member["member_path"])
                    self.assertEqual((len(data), sha256(data).hexdigest()), (member["bytes"], member["sha256"]))
                    if member["original"]:
                        self.assertEqual(data, (SAMPLES / member["original"]).read_bytes())


if __name__ == "__main__":
    unittest.main()
