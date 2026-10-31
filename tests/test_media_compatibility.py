"""Consumer contracts for the canonical and compatibility media package names."""
from __future__ import annotations

import copy
from dataclasses import asdict
from importlib import import_module
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from tests.test_audio_video import QUESTION, SAMPLES, media_server, video_reply


ROOT = Path(__file__).resolve().parents[1]
OLD_MEDIA = "app.modules.1_documentIngestionAndParsing.7_audioAndVideoProcessing"
NEW_MEDIA = "app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding"


class MediaImportCompatibilityTests(unittest.TestCase):
    def test_fresh_import_orders_share_public_types_functions_and_submodules(self):
        script = r'''
import importlib
import json
import sys
import warnings

old_name = "app.modules.1_documentIngestionAndParsing.7_audioAndVideoProcessing"
new_name = "app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding"
submodules = ("models", "client", "media", "assembly", "prompts", "__main__")
with warnings.catch_warnings(record=True) as observed:
    warnings.simplefilter("always")
    for package in sys.argv[1:]:
        importlib.import_module(package)
        for suffix in submodules:
            importlib.import_module(package + "." + suffix)
    old = importlib.import_module(old_name)
    new = importlib.import_module(new_name)
    expected_exports = ["convert_file", "convert_bytes", "StepFunConfig", "ProcessingOptions",
                        "ConversionResult", "Source", "Segment", "Diagnostic"]
    assert old.__all__ == new.__all__ == expected_exports
    for name in expected_exports + ["StepFunError", "MediaError"]:
        assert getattr(old, name) is getattr(new, name), name
    for suffix in submodules:
        legacy = importlib.import_module(old_name + "." + suffix)
        canonical = importlib.import_module(new_name + "." + suffix)
        if suffix == "__main__":
            assert legacy.main is canonical.main
        else:
            assert legacy is canonical, suffix
    assert new.ConversionResult.__module__ == new_name + ".models"
    assert new.StepFunConfig.__module__ == new_name + ".client"
    assert new.ProcessingOptions().audio_segment_seconds == 30
    assert new.ProcessingOptions().video_segment_seconds == 60
    assert new.ProcessingOptions().media_timeout == 300
    assert new.StepFunConfig.__dataclass_fields__["timeout"].default == 180
    assert not observed, [str(item.message) for item in observed]
print(json.dumps({"exports": expected_exports, "warnings": len(observed)}))
'''
        for first, second in ((OLD_MEDIA, NEW_MEDIA), (NEW_MEDIA, OLD_MEDIA)):
            with self.subTest(first=first):
                completed = subprocess.run(
                    [sys.executable, "-c", script, first, second], cwd=ROOT,
                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["warnings"], 0)


class MediaResultCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.old = import_module(OLD_MEDIA)
        self.new = import_module(NEW_MEDIA)
        self.ingestion = import_module("app.modules.1_documentIngestionAndParsing")
        self.handoff = import_module(
            "app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff",
        )
        self.path = SAMPLES / "video_extra_delayed.mp4"
        self.identity = {"business_id": "培训业务", "version": "业务三"}

    def convert_entries(self, task, **server_options):
        natives, reports = [], []
        kwargs = {
            "task": task, "source": "training:compat", "media_id": "培训录制",
            "media_version": "录制二",
        }
        if task == "both":
            kwargs["question"] = QUESTION
        for module in (self.old, self.new):
            options = module.ProcessingOptions(audio_segment_seconds=2.5, video_segment_seconds=2)
            for entry in ("file", "bytes"):
                with self.subTest(module=module.__name__, entry=entry, task=task), \
                        media_server(**server_options) as (config, _):
                    if entry == "file":
                        native = module.convert_file(self.path, config=config, options=options, **kwargs)
                    else:
                        native = module.convert_bytes(
                            self.path.read_bytes(), format="mp4", config=config, options=options, **kwargs,
                        )
                    before = copy.deepcopy(asdict(native))
                    report = self.handoff.adapt_result(native, **self.identity)
                    self.assertEqual(asdict(native), before)
                    natives.append(native)
                    reports.append(report)
        for entry in ("file", "bytes"):
            with media_server(**server_options) as (config, _):
                options = self.new.ProcessingOptions(audio_segment_seconds=2.5, video_segment_seconds=2)
                if entry == "file":
                    report = self.ingestion.convert_file(
                        self.path, config=config, options=options, **kwargs, **self.identity,
                    )
                else:
                    report = self.ingestion.convert_bytes(
                        self.path.read_bytes(), format="mp4", config=config, options=options,
                        **kwargs, **self.identity,
                    )
                reports.append(report)
        self.assertTrue(all(asdict(item) == asdict(natives[0]) for item in natives))
        expected = reports[0].to_dict()
        for report in reports:
            self.assertEqual(report.to_dict(), expected)
            self.assertEqual(json.loads(json.dumps(report.to_dict(), ensure_ascii=False)), expected)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "media.json"
            self.ingestion.export_json(reports[0], output)
            self.assertEqual(json.loads(output.read_bytes()), expected)
        return natives[0], reports[0]

    def test_video_transcribe_and_both_preserve_complete_reports_across_names_and_entries(self):
        for task in ("transcribe", "both"):
            with self.subTest(task=task):
                native, report = self.convert_entries(task)
                self.assertEqual(native.status, "content", native.error)
                self.assertTrue(native.requires_review)
                self.assertEqual(native.source.audio_stream_index, 1)
                document = report.documents[0]
                self.assertEqual((document.business_id, document.version), ("培训业务", "业务三"))
                self.assertEqual(document.body, native.text)
                self.assertEqual(document.sources[0].locator, asdict(native.source))
                self.assertEqual(document.structure["segments"], [asdict(item) for item in native.segments])
                audio = [item for item in native.segments if item.kind == "audio"]
                self.assertEqual([item.start_seconds for item in audio], [0, 2.56, 5.12])
                self.assertTrue(all(item.speaker is None and item.time_precision == "segment" for item in audio))
                self.assertTrue(all(item.requested_model == "stepaudio-2.5-asr" for item in audio))
                video = [item for item in native.segments if item.kind == "video"]
                if task == "both":
                    self.assertEqual([(item.start_seconds, item.end_seconds) for item in video],
                                     [(1.25, 3.25), (3.25, 5.25)])
                    self.assertTrue(all(item.response_model == "step-5-preview-actual" for item in video))
                    self.assertTrue(all(item.prompt_version == "video-v1" for item in video))
                else:
                    self.assertEqual(video, [])
                segment_sources = [item for item in document.sources if item.kind == "media_segment"]
                self.assertEqual(len(segment_sources), len(native.segments))
                for segment, source, unit in zip(native.segments, segment_sources, document.units):
                    self.assertEqual(source.locator, {
                        **asdict(native.source), "kind": segment.kind,
                        "start_seconds": segment.start_seconds, "end_seconds": segment.end_seconds,
                        "time_precision": segment.time_precision, "speaker": segment.speaker,
                    })
                    self.assertEqual(unit.source_ids, [source.id])
                    self.assertEqual(unit.text, segment.text)
                    self.assertEqual(unit.alignment, "unmapped")

    def test_combined_uncertainty_empty_asr_and_review_diagnostics_survive_both_names(self):
        note = "终点缺失，需复核原片段。"
        native, report = self.convert_entries(
            "both", asr={"text": ""}, video=video_reply("终点被截断。", "uncertain", [note]),
        )
        self.assertEqual(native.status, "uncertain", native.error)
        self.assertEqual([item.status for item in native.segments],
                         ["no_text", "uncertain", "no_text", "uncertain", "no_text"])
        self.assertEqual(len(native.review_issues), 2)
        self.assertEqual(len(native.warnings), 3)
        document = report.documents[0]
        self.assertEqual(document.status, "uncertain")
        self.assertTrue(document.requires_review)
        uncertainty = [item for item in document.diagnostics if item.code == "model_uncertainty"]
        self.assertEqual([item.message for item in uncertainty], [note, note])
        for diagnostic in uncertainty:
            self.assertIn(diagnostic.source_id, {item.id for item in document.sources})
            self.assertIn(diagnostic.unit_id, {item.id for item in document.units})

    def test_midway_failures_preserve_stage_offsets_diagnostics_and_discard_partial_content(self):
        for task, fail_at, stage, start in (("transcribe", 2, "audio", 2.56), ("both", 4, "video", 3.25)):
            with self.subTest(task=task):
                native, report = self.convert_entries(task, fail_at=fail_at)
                self.assertEqual(native.status, "failed")
                self.assertIsNone(native.text)
                self.assertEqual(native.segments, [])
                self.assertEqual(asdict(native.error), {
                    "code": "service_error", "message": "StepFun request HTTP 503",
                    "stage": stage, "start_seconds": start, "http_status": 503,
                })
                document = report.documents[0]
                self.assertIsNone(document.body)
                self.assertEqual(document.units, [])
                self.assertEqual(document.diagnostics[-1].details, asdict(native.error))

    def test_handoff_accepts_native_subclasses_from_both_names_and_rejects_lookalikes(self):
        source = self.old.Source(location="upload:media", format="mp4")
        segment = self.old.Segment(
            kind="audio", start_seconds=1.25, end_seconds=3.25, text="原录制文字。",
            status="content", requested_model="stepaudio-2.5-asr", response_model=None, prompt_version=None,
        )
        native = self.old.ConversionResult("原录制文字。", source, "transcribe", status="content", segments=[segment])
        expected = self.handoff.adapt_result(native).to_dict()
        for module in (self.old, self.new):
            class CustomResult(module.ConversionResult):
                pass

            subclass = CustomResult(**vars(native))
            self.assertIsInstance(subclass, self.new.ConversionResult)
            self.assertEqual(self.handoff.adapt_result(subclass).to_dict(), expected)
        with self.assertRaisesRegex(TypeError, "Unsupported result type: SimpleNamespace"):
            self.handoff.adapt_result(SimpleNamespace(**vars(native), success=True, requires_review=False))


class MediaCliCompatibilityTests(unittest.TestCase):
    def test_literal_old_and_new_cli_commands_emit_complete_success_and_failed_json_without_warnings(self):
        canonical = import_module(NEW_MEDIA)
        path = SAMPLES / "video_extra_delayed.mp4"
        for task in ("transcribe", "both"):
            for failed in (False, True):
                with self.subTest(task=task, failed=failed), \
                        media_server(http_status=503 if failed else 200) as (config, _), \
                        TemporaryDirectory() as directory:
                    root = Path(directory)
                    env_file = root / "media.env"
                    env_file.write_text("\n".join([
                        "STEP_API_KEY=" + config.api_key, "STEP_BASE_URL=" + config.base_url,
                        "STEP_ASR_MODEL=stepaudio-2.5-asr", "STEP_MODEL=step-5-preview", "",
                    ]), encoding="utf-8")
                    temporary_media = root / "temporary-media"
                    temporary_media.mkdir()
                    env = {key: value for key, value in os.environ.items() if not key.startswith("STEP_")}
                    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONWARNINGS": "always",
                                "TMP": str(temporary_media), "TEMP": str(temporary_media),
                                "TMPDIR": str(temporary_media)})
                    options = canonical.ProcessingOptions(audio_segment_seconds=2.5, video_segment_seconds=2)
                    expected = asdict(canonical.convert_file(
                        path, source="cli:compat", task=task, config=config, options=options,
                    ))
                    outputs = []
                    for command in (
                        "app.modules.1_documentIngestionAndParsing.7_audioAndVideoProcessing",
                        "app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding",
                    ):
                        completed = subprocess.run([
                            sys.executable, "-m", command, str(path), "--task", task,
                            "--env-file", str(env_file), "--source", "cli:compat", "--format", "mp4",
                            "--audio-seconds", "2.5", "--video-seconds", "2", "--timeout", "2",
                        ], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
                        self.assertEqual(completed.returncode, 1 if failed else 0, completed.stderr)
                        self.assertEqual(completed.stderr, "")
                        payload = json.loads(completed.stdout)
                        self.assertEqual(payload, expected)
                        self.assertEqual(list(temporary_media.iterdir()), [])
                        outputs.append(payload)
                    self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
