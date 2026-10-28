import base64
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests.test_image_ocr import RULES, step_server
from tests.test_image_provenance import provenance_server
from tests.test_image_understanding import CLEAR_ANSWER, QUESTION, envelope, step_server as understanding_server


MODULE = "app.modules.1_documentIngestionAndParsing.8_zipContainers"
zips = importlib.import_module(MODULE)
images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "tests/testFile"
MANIFEST = json.loads((SAMPLES / "zip_image_samples.json").read_text(encoding="utf-8"))
ARCHIVES = {record["archive"]: record for record in MANIFEST["archives"]}


class ZipImageTests(unittest.TestCase):
    def test_cli_accepts_image_task_with_environment_config_and_reports_all_three_exit_states(self):
        with step_server() as config:
            environment = os.environ | {"STEP_API_KEY": config.api_key, "STEP_BASE_URL": config.base_url,
                                        "STEP_MODEL": config.model}
            for archive, options, status, code in (
                ("zip_image_ocr.zip", {"task": "ocr"}, "success", 0),
                ("zip_image_formats.zip", {}, "partial_success", 2),
                ("zip_image_ocr.zip", {}, "failed", 1),
                ("zip_image_formats.zip", {"task": "ocr", "private-option-key-42": "private-option-value-42"},
                 "partial_success", 2),
            ):
                with self.subTest(status=status, options=options):
                    completed = subprocess.run(
                        [sys.executable, "-m", MODULE, str(SAMPLES / archive), "--source", "CLI.zip",
                         "--parser-options", json.dumps({"image": options})],
                        cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(completed.returncode, code, completed.stderr)
                    self.assertEqual(completed.stderr, "")
                    report = json.loads(completed.stdout)
                    self.assertEqual(report["status"], status)
                    self.assertEqual(report["source"], "CLI.zip")
                    self.assertNotIn("test-key", completed.stdout)
                    self.assertNotIn(config.base_url, completed.stdout)
                    self.assertNotIn("private-option-key-42", completed.stdout)
                    self.assertNotIn("private-option-value-42", completed.stdout)
                    if status == "success":
                        result = report["members"][0]["result"]
                        self.assertEqual(result["text"], RULES)
                        self.assertTrue(result["success"])
                        self.assertTrue(result["requires_review"])
                        self.assertEqual(result["source"]["location"], "CLI.zip!/rules.png#1")

    def test_timeout_connection_and_decode_failures_have_no_local_fallback(self):
        with step_server(delay=0.15) as config:
            timeout = zips.convert_file(SAMPLES / "zip_image_ocr.zip", parser_options={
                "image": {"task": "ocr", "config": replace(config, timeout=0.03)},
            })
        disconnected = zips.convert_file(SAMPLES / "zip_image_ocr.zip", parser_options={
            "image": {"task": "ocr", "config": replace(config, timeout=5)},
        })
        with patch.dict(os.environ, {}, clear=True):
            corrupt = zips.convert_file(SAMPLES / "zip_image_corrupt.zip", parser_options={"image": {"task": "ocr"}})
        for result, code in ((timeout, "timeout"), (disconnected, "network_error"), (corrupt, "image_decode_error")):
            with self.subTest(code=code):
                failed = next(member for member in result.members if member.status == "failed")
                self.assertEqual(failed.result.error.code, code)
                self.assertIsNone(failed.result.text)
                self.assertTrue(failed.result.source.sha256)
                self.assertFalse(result.success)
        self.assertEqual(corrupt.status, "partial_success")
        self.assertEqual(corrupt.members[-1].result.markdown, "after.txt\n")

    def test_api_and_protocol_failures_preserve_image_identity_and_successful_text_siblings(self):
        for http_status, reply, code in (
            (401, b"test-key private upstream response", "authentication_error"),
            (403, b"test-key private upstream response", "authentication_error"),
            (429, b"test-key private upstream response", "rate_limited"),
            (503, b"test-key private upstream response", "service_error"),
            (400, b"test-key private upstream response", "http_error"),
            (200, b"not JSON test-key private upstream response", "protocol_error"),
            (200, {"error": "test-key private upstream response"}, "protocol_error"),
            (200, envelope(text=""), "protocol_error"),
        ):
            with self.subTest(code=code, status=http_status), step_server(reply, http_status=http_status) as config:
                result = zips.convert_file(SAMPLES / "zip_image_formats.zip",
                                          parser_options={"image": {"task": "ocr", "config": config}})
            self.assertEqual(result.status, "partial_success")
            self.assertEqual(result.counts["success"], 2)
            self.assertEqual(result.counts["failed"], 4)
            self.assertEqual(result.members[-1].result.markdown, "after.txt\n")
            for member, expected in zip(result.members[1:5], ARCHIVES["zip_image_formats.zip"]["members"][1:5]):
                self.assertEqual(member.result.error.code, code)
                self.assertEqual(member.result.error.http_status, http_status if http_status != 200 else None)
                self.assertEqual(member.result.source.sha256, expected["sha256"])
                self.assertEqual((member.result.source.width, member.result.source.height), (1100, 340))
                self.assertIsNone(member.result.text)
            report = json.dumps(result.to_dict())
            self.assertNotIn("test-key", report)
            self.assertNotIn("private upstream response", report)

    def test_missing_task_question_configuration_and_plain_config_are_visible_member_failures(self):
        for options, code in (
            ({}, "invalid_options"),
            ({"task": "understand"}, "invalid_options"),
            ({"task": "ocr", "question": "不应作为 OCR 问题"}, "invalid_options"),
            ({"task": "ocr"}, "missing_config"),
            ({"task": "ocr", "config": {"api_key": "test-key"}}, "invalid_config"),
            ({"task": "ocr", "config": images.StepFunConfig(
                api_key="test-key", base_url="invalid-url-42", model="step-5-preview",
            )}, "invalid_config"),
        ):
            with self.subTest(code=code), patch.dict(os.environ, {}, clear=True):
                result = zips.convert_file(SAMPLES / "zip_image_formats.zip", parser_options={"image": options})
            self.assertEqual(result.status, "partial_success")
            self.assertEqual(result.counts["success"], 2)
            for member in result.members[1:5]:
                self.assertEqual(member.status, "failed")
                self.assertEqual(member.reason, "parse_error")
                self.assertEqual(member.result.error.code, code)
                self.assertEqual(member.error, member.result.error.message)
                self.assertIsNone(member.result.text)
            self.assertEqual(result.members[0].result.markdown, "before.txt\n")
            self.assertEqual(result.members[-1].result.markdown, "after.txt\n")
            report = json.dumps(result.to_dict())
            for private in ("test-key", "invalid-url-42"):
                self.assertNotIn(private, report)

    def test_document_and_original_crop_mapping_survive_success_and_failure_without_reinterpreting_coordinates(self):
        document = images.DocumentSource("payment-policy", "approved-2026-10", images.DocumentPosition("pdf_page", 3))
        crop = images.CropMapping("archive/payment-rules/source-image-01", 1200, 600, (120, 180, 1120, 440))
        path = SAMPLES / "zip_image_crop.zip"
        for status in (200, 503):
            with self.subTest(status=status), provenance_server(http_status=status) as config:
                options = {"image": {"task": "ocr", "config": config, "document": document,
                                     "crop": crop, "is_cropped": True}}
                result = zips.convert_file(path, source="policy.zip", parser_options=options)
                data = zips.convert_bytes(path.read_bytes(), source="policy.zip", parser_options=options)
            self.assertEqual(result, data)
            native = result.members[0].result
            self.assertEqual(result.success, status == 200)
            self.assertIs(native.source.document, document)
            self.assertIs(native.source.crop, crop)
            self.assertEqual(native.source.location, "policy.zip!/crop.png#1")
            self.assertEqual((native.source.width, native.source.height), (1000, 260))
            self.assertEqual(native.source.sha256, ARCHIVES[path.name]["members"][0]["sha256"])
            report = json.loads(json.dumps(result.to_dict()))["members"][0]
            self.assertEqual(report["source"], {"container": "policy.zip", "member_path": "crop.png", "entry_index": 1})
            self.assertEqual(report["result"]["source"]["document"], {
                "document_id": "payment-policy", "business_version": "approved-2026-10",
                "position": {"kind": "pdf_page", "index": 3},
            })
            self.assertEqual(report["result"]["source"]["crop"]["bbox"], [120, 180, 1120, 440])
            self.assertEqual(report["result"]["source"]["crop"]["original_image_id"], crop.original_image_id)

    def test_empty_ocr_and_uncertain_understanding_remain_successful_and_require_review_in_json(self):
        for archive, options, status, text, notes in (
            ("zip_image_blank.zip", {"task": "ocr"}, "no_text", "", ["未取得可辨认文字"]),
            ("zip_image_uncertain.zip", {"task": "understand", "question": QUESTION}, "uncertain",
             "金额超过1万元的条件可辨，但底部终点被截断，无法确认审批人对应关系。", ["审批节点被截去"]),
        ):
            with self.subTest(status=status), understanding_server(
                envelope(status=status, text=text, notes=notes),
            ) as (config, _):
                result = zips.convert_file(SAMPLES / archive, parser_options={"image": options | {"config": config}})
            self.assertTrue(result.success, result.to_dict())
            self.assertEqual(result.counts["failed"], 0)
            native = result.members[0].result
            self.assertEqual((native.status, native.text), (status, text))
            self.assertEqual(native.review_issues[1].message, notes[0])
            report = json.loads(json.dumps(result.to_dict()))
            self.assertTrue(report["success"])
            self.assertTrue(report["requires_review"])
            self.assertTrue(report["members"][0]["result"]["success"])
            self.assertTrue(report["members"][0]["result"]["requires_review"])
            self.assertEqual(report["members"][0]["result"]["text"], text)
            self.assertEqual(native.source.sha256, ARCHIVES[archive]["members"][0]["sha256"])
            if status == "no_text":
                self.assertIn("不证明图片没有文字", native.warnings[0])

    def test_description_and_understanding_preserve_native_outputs_and_real_request_content(self):
        for archive, task, text, question, prompt_version in (
            ("zip_image_describe.zip", "describe", "湖边有橙色帐篷、山脉、树木和太阳。", None, "describe-v1"),
            ("zip_image_understand.zip", "understand", CLEAR_ANSWER, QUESTION, "understand-v2"),
        ):
            sample = ARCHIVES[archive]["members"][0]
            image_data = (SAMPLES / sample["source_sample"]).read_bytes()
            with self.subTest(task=task), understanding_server(envelope(text=text)) as (config, requests):
                options = {"task": task, "question": question, "config": config}
                file = zips.convert_file(SAMPLES / archive, source="tasks.zip", parser_options={"image": options})
                data = zips.convert_bytes((SAMPLES / archive).read_bytes(), source="tasks.zip",
                                          parser_options={"image": options})
                native = images.convert_bytes(image_data, format=Path(sample["member_path"]).suffix,
                                              source=f"tasks.zip!/{sample['member_path']}#1", **options)
            self.assertEqual(file, data)
            self.assertTrue(file.success, file.to_dict())
            result = file.members[0].result
            self.assertEqual(result, native)
            self.assertEqual(result.question, question)
            self.assertEqual(result.task, task)
            self.assertEqual(result.text, text)
            self.assertEqual(result.prompt_version, prompt_version)
            self.assertEqual(result.source.sha256, sample["sha256"])
            self.assertTrue(file.to_dict()["members"][0]["result"]["requires_review"])
            request = requests[0]
            self.assertEqual(request["path"], "/v1/chat/completions")
            body = request["body"]
            self.assertEqual(body["model"], "step-5-preview")
            self.assertTrue(body["response_format"]["json_schema"]["strict"])
            parts = body["messages"][0]["content"]
            mime, encoded = parts[1]["image_url"]["url"].split(";base64,")
            self.assertEqual(mime, "data:image/webp" if task == "describe" else "data:image/png")
            self.assertEqual(base64.b64decode(encoded, validate=True), image_data)
            self.assertIn(question if question else "描述", parts[0]["text"])

    def test_unknown_image_option_is_a_visible_member_error_without_echoing_its_name_or_value(self):
        path = SAMPLES / "zip_image_formats.zip"
        result = zips.convert_file(path, parser_options={
            "image": {"task": "ocr", "private-option-key-42": "private-option-value-42"},
        })
        self.assertEqual(result.status, "partial_success")
        self.assertEqual(result.counts["success"], 2)
        self.assertEqual(result.counts["failed"], 4)
        for member in result.members[1:5]:
            self.assertEqual(member.status, "failed")
            self.assertTrue(member.error)
            self.assertEqual(member.result_kind, "image")
            self.assertEqual(member.result.error.code, "invalid_options")
        report = json.dumps(result.to_dict())
        self.assertNotIn("private-option-key-42", report)
        self.assertNotIn("private-option-value-42", report)

    def test_file_and_bytes_keep_native_ocr_for_all_static_formats_and_member_sources(self):
        path = SAMPLES / "zip_image_formats.zip"
        with step_server() as config:
            options = {"image": {"task": "ocr", "config": config}}
            file = zips.convert_file(path, source="上传.zip", parser_options=options)
            data = zips.convert_bytes(path.read_bytes(), source="上传.zip", parser_options=options)
        self.assertEqual(file, data)
        self.assertTrue(file.success, file.to_dict())
        self.assertEqual(file.counts, {"total": 6, "success": 6, "failed": 0, "ignored": 0, "unprocessed": 0})
        self.assertTrue(file.requires_review)
        for member, expected in zip(file.members[1:5], ARCHIVES[path.name]["members"][1:5]):
            with self.subTest(member=member.source.member_path):
                self.assertIsInstance(member.result, images.ConversionResult)
                self.assertEqual(member.result_kind, "image")
                self.assertEqual(member.source.container, "上传.zip")
                self.assertEqual(member.source.member_path, expected["member_path"])
                self.assertEqual(member.source.entry_index, expected["entry_index"])
                self.assertEqual(member.result.source.location,
                                 f"上传.zip!/{expected['member_path']}#{expected['entry_index']}")
                self.assertEqual(member.result.source.sha256, expected["sha256"])
                self.assertEqual((member.result.source.width, member.result.source.height), (1100, 340))
                self.assertEqual(member.result.text, RULES)
                self.assertEqual(member.result.task, "ocr")
                self.assertEqual(member.result.prompt_version, "ocr-v1")
                self.assertEqual(member.result.requested_model, "step-5-preview")
                self.assertEqual(member.result.response_model, "step-5-preview-actual")


if __name__ == "__main__":
    unittest.main()
