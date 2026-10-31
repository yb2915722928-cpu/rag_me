import copy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.test_audio_video import QUESTION as MEDIA_QUESTION, TRANSCRIPT, VISUAL, media_server, video_reply
from tests.test_image_provenance import CROP, TEXT, provenance_server
from tests.test_image_understanding import CLEAR_ANSWER, QUESTION, envelope, step_server


images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
media = importlib.import_module("app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding")
handoff = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.unifiedDocumentHandoff"
)
SAMPLES = Path(__file__).parent / "testFile"


class DerivedHandoffTests(unittest.TestCase):
    def roundtrip(self, native, **identity):
        before = copy.deepcopy(native)
        report = handoff.adapt_result(native, **identity)
        with TemporaryDirectory() as directory:
            saved = json.loads(handoff.export_json(report, Path(directory) / "派生文字.json").read_bytes())
        self.assertEqual(native, before)
        document = saved["documents"][0]
        self.assertEqual(saved["status"], native.status)
        self.assertEqual(document["status"], native.status)
        self.assertEqual(document["body"], native.text)
        self.assertEqual(document["body_format"], "text")
        self.assertEqual(document["requires_review"], native.requires_review)
        all_ids = [document["id"]] + [item["id"] for item in document["sources"] + document["units"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        source_ids = {source["id"] for source in document["sources"]}
        for unit in document["units"]:
            self.assertTrue(set(unit["source_ids"]) <= source_ids)
            self.assertIsNone(unit["body_span"])
            self.assertIsNone(unit["parent_id"])
        for diagnostic in document["diagnostics"]:
            self.assertEqual(diagnostic["document_id"], document["id"])
            self.assertIn(diagnostic["source_id"], source_ids)
            if diagnostic["unit_id"] is not None:
                self.assertIn(diagnostic["unit_id"], {unit["id"] for unit in document["units"]})
        return document

    def test_image_ocr_keeps_full_text_and_original_crop_evidence(self):
        with provenance_server() as config:
            native = images.convert_file(
                CROP, task="ocr", config=config,
                document=images.DocumentSource("付款制度", "业务版二", images.DocumentPosition("pdf_page", 3)),
                crop=images.CropMapping("原图一", 1200, 600, (120, 180, 1120, 440)),
                is_cropped=True,
            )
        self.assertTrue(native.success, native.error)
        document = self.roundtrip(native)
        self.assertEqual(document["body"], TEXT)
        self.assertIsNone(document["business_id"])
        self.assertIsNone(document["version"])
        source = document["sources"][0]
        self.assertEqual(source["kind"], "image")
        self.assertEqual(source["locator"], json.loads(json.dumps(asdict(native.source))))
        self.assertEqual(source["locator"]["crop"]["bbox"], [120, 180, 1120, 440])
        self.assertEqual(source["locator"]["document"]["position"], {"kind": "pdf_page", "index": 3})
        unit, = document["units"]
        self.assertEqual(unit["kind"], "ocr")
        self.assertEqual(unit["text"], TEXT)
        self.assertEqual(unit["source_ids"], [source["id"]])
        self.assertEqual(unit["alignment"], "document")

    def test_image_generated_tasks_keep_question_and_generation_context_without_new_requests(self):
        for task in ("describe", "understand"):
            with self.subTest(task=task), step_server(envelope(text=CLEAR_ANSWER)) as (config, requests):
                native = images.convert_file(
                    SAMPLES / "image_understanding_clear.png", task=task, config=config,
                    question=QUESTION if task == "understand" else None,
                )
                self.assertTrue(native.success, native.error)
                self.assertEqual(len(requests), 1)
                document = self.roundtrip(native, business_id="审批图", version="修订三")
                self.assertEqual(len(requests), 1)
                self.assertEqual(document["units"][0]["kind"], task)
                self.assertEqual(document["metadata"], {
                    "task": task, "question": QUESTION if task == "understand" else None,
                    "requested_model": "step-5-preview", "response_model": "step-5-preview-actual",
                    "prompt_version": native.prompt_version,
                })
                self.assertEqual((document["business_id"], document["version"]), ("审批图", "修订三"))
                self.assertIsNone(document["sources"][0]["locator"]["document"])
                self.assertIsNone(document["sources"][0]["locator"]["crop"])

    def test_uncertain_image_keeps_review_reasons_linked_to_derived_content(self):
        text = "可见两个审批节点，但无法确认箭头归属。"
        with step_server(envelope(status="uncertain", text=text, notes=["箭头被截断"])) as (config, requests):
            native = images.convert_file(
                SAMPLES / "image_understanding_truncated.png", task="understand", question=QUESTION, config=config,
            )
            self.assertEqual(native.status, "uncertain", native.error)
            document = self.roundtrip(native)
            self.assertEqual(len(requests), 1)
        self.assertTrue(document["requires_review"])
        unit, = document["units"]
        self.assertEqual(unit["status"], "uncertain")
        self.assertEqual(unit["text"], text)
        reviews = [item for item in document["diagnostics"] if item["level"] == "review"]
        self.assertEqual([(item["code"], item["message"]) for item in reviews],
                         [(item.code, item.message) for item in native.review_issues])
        for item in reviews:
            self.assertEqual(item["document_id"], document["id"])
            self.assertEqual(item["unit_id"], unit["id"])
            self.assertEqual(item["source_id"], unit["source_ids"][0])

    def test_image_no_text_keeps_empty_content_and_warning_without_becoming_failure(self):
        with step_server(envelope(status="no_text", text="")) as (config, requests):
            native = images.convert_file(SAMPLES / "image_ocr_blank.png", task="ocr", config=config)
            self.assertEqual(native.status, "no_text", native.error)
            document = self.roundtrip(native)
            self.assertEqual(len(requests), 1)
        self.assertTrue(document["requires_review"])
        self.assertEqual(document["body"], "")
        self.assertEqual(document["units"][0]["status"], "no_text")
        warnings = [item for item in document["diagnostics"] if item["level"] == "warning"]
        self.assertEqual([item["message"] for item in warnings], native.warnings)
        self.assertIn("不证明图片没有文字", warnings[0]["message"])
        self.assertEqual(warnings[0]["source_id"], document["sources"][0]["id"])

    def test_failed_image_exports_source_and_http_error_without_a_content_unit(self):
        with step_server(status=503) as (config, requests):
            native = images.convert_file(
                CROP, task="understand", question=QUESTION, config=config,
                document=images.DocumentSource("付款制度", "业务版二", images.DocumentPosition("slide", 3)),
                crop=images.CropMapping("原图一", 1200, 600, (120, 180, 1120, 440)),
            )
            self.assertEqual(native.status, "failed")
            document = self.roundtrip(native)
            self.assertEqual(len(requests), 1)
        self.assertIsNone(document["body"])
        self.assertEqual(document["units"], [])
        self.assertEqual(document["metadata"]["question"], QUESTION)
        self.assertIsNotNone(document["sources"][0]["locator"]["sha256"])
        error, = document["diagnostics"]
        self.assertEqual((error["level"], error["code"]), ("error", "service_error"))
        self.assertEqual(error["message"], native.error.message)
        self.assertEqual(error["details"]["http_status"], 503)
        self.assertEqual(error["document_id"], document["id"])
        self.assertEqual(error["source_id"], document["sources"][0]["id"])
        self.assertIsNone(error["unit_id"])

    def test_media_keeps_complete_body_and_actual_audio_video_segments(self):
        with media_server() as (config, requests):
            native = media.convert_file(
                SAMPLES / "media_rules.mp4", task="both", question=MEDIA_QUESTION, config=config,
                media_id="审批培训", media_version="录制版二",
                options=media.ProcessingOptions(audio_segment_seconds=5, video_segment_seconds=6),
            )
            self.assertTrue(native.success, native.error)
            self.assertGreater(len(native.segments), 2)
            count = len(requests)
            document = self.roundtrip(native)
            self.assertEqual(len(requests), count)
        self.assertIn(TRANSCRIPT, document["body"])
        self.assertIn(VISUAL, document["body"])
        self.assertEqual(document["metadata"], {"task": "both", "question": MEDIA_QUESTION})
        self.assertIsNone(document["business_id"])
        self.assertIsNone(document["version"])
        self.assertEqual(document["sources"][0]["kind"], "media")
        self.assertEqual(document["sources"][0]["locator"], asdict(native.source))
        self.assertEqual(document["structure"]["segments"], [asdict(item) for item in native.segments])
        self.assertEqual(len(document["units"]), len(native.segments))
        sources = {source["id"]: source for source in document["sources"]}
        for unit, segment in zip(document["units"], native.segments, strict=True):
            self.assertEqual((unit["kind"], unit["text"], unit["status"]),
                             (segment.kind, segment.text, segment.status))
            self.assertEqual(unit["alignment"], "unmapped")
            source, = [sources[source_id] for source_id in unit["source_ids"]]
            self.assertEqual(source["kind"], "media_segment")
            self.assertEqual(source["locator"]["start_seconds"], segment.start_seconds)
            self.assertEqual(source["locator"]["end_seconds"], segment.end_seconds)
            self.assertEqual(source["locator"]["sha256"], native.source.sha256)
            self.assertEqual(source["locator"]["media_version"], "录制版二")
            self.assertEqual(source["locator"]["time_precision"], "segment")
            self.assertIsNone(source["locator"]["speaker"])
            self.assertEqual(unit["metadata"]["requested_model"], segment.requested_model)
            self.assertEqual(unit["metadata"]["response_model"], segment.response_model)
            self.assertEqual(unit["metadata"]["prompt_version"], segment.prompt_version)
            self.assertIsNone(unit["metadata"]["speaker"])

    def test_uncertain_video_review_stays_with_its_segment(self):
        with media_server(video=video_reply("终点被截断，无法确认审批人。", "uncertain", ["缺少终点"])) as (config, requests):
            native = media.convert_file(
                SAMPLES / "media_uncertain.mp4", task="video", question=MEDIA_QUESTION, config=config,
            )
            self.assertEqual(native.status, "uncertain", native.error)
            document = self.roundtrip(native)
            self.assertEqual(len(requests), 1)
        self.assertTrue(document["requires_review"])
        unit, = document["units"]
        self.assertEqual(unit["status"], "uncertain")
        self.assertEqual(unit["metadata"]["review_notes"], ["缺少终点"])
        reviews = [item for item in document["diagnostics"] if item["level"] == "review"]
        global_reviews = [item for item in reviews if item["unit_id"] is None]
        self.assertEqual([item["message"] for item in global_reviews], native.review_issues)
        segment_reviews = [item for item in reviews if item["unit_id"] == unit["id"]]
        self.assertEqual([item["message"] for item in segment_reviews], ["缺少终点"])
        self.assertEqual(segment_reviews[0]["source_id"], unit["source_ids"][0])
        self.assertEqual(segment_reviews[0]["document_id"], document["id"])

    def test_silent_audio_retains_no_text_segment_and_unverified_warning(self):
        with media_server(asr={"text": ""}) as (config, requests):
            native = media.convert_bytes(
                (SAMPLES / "media_silence.wav").read_bytes(), format="wav", source="静音录制",
                task="transcribe", config=config,
            )
            self.assertEqual(native.status, "no_text", native.error)
            document = self.roundtrip(native)
            self.assertEqual(len(requests), 1)
        self.assertEqual(document["body"], "")
        self.assertTrue(document["requires_review"])
        unit, = document["units"]
        self.assertEqual((unit["text"], unit["kind"], unit["status"]), ("", "audio", "no_text"))
        self.assertIsNone(unit["metadata"]["speaker"])
        self.assertIsNone(unit["metadata"]["response_model"])
        warnings = [item for item in document["diagnostics"] if item["level"] == "warning"]
        self.assertEqual([item["message"] for item in warnings], native.warnings)
        self.assertTrue(all(item["source_id"] == document["sources"][0]["id"] for item in warnings))

    def test_midway_media_failure_keeps_error_time_and_never_exposes_partial_content(self):
        with media_server(fail_at=2) as (config, requests):
            native = media.convert_file(
                SAMPLES / "media_rules.wav", task="transcribe", config=config,
                options=media.ProcessingOptions(audio_segment_seconds=5),
            )
            self.assertEqual(native.status, "failed")
            self.assertEqual(len(requests), 2)
            document = self.roundtrip(native)
            self.assertEqual(len(requests), 2)
        self.assertIsNone(document["body"])
        self.assertEqual(document["units"], [])
        self.assertEqual(document["structure"]["segments"], [])
        self.assertEqual(len(document["sources"]), 1)
        error, = document["diagnostics"]
        self.assertEqual((error["level"], error["code"]), ("error", "service_error"))
        self.assertEqual(error["details"], asdict(native.error))
        self.assertEqual(error["details"]["stage"], "audio")
        self.assertGreater(error["details"]["start_seconds"], 0)
        self.assertEqual(error["details"]["http_status"], 503)
        self.assertEqual(error["source_id"], document["sources"][0]["id"])
        self.assertEqual(error["document_id"], document["id"])
        self.assertIsNone(error["unit_id"])


if __name__ == "__main__":
    unittest.main()
