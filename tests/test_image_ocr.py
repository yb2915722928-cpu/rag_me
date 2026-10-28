import base64
from contextlib import contextmanager
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch


images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
SAMPLES = Path(__file__).parent / "testFile"
RULES = "金额超过 1 万元时，须负责人审批。\n其他情况由财务审批。\n未经批准不得付款。\n温度不得超过 60 °C；每 30 天检查一次。"
SAMPLE_HASHES = {item["filename"]: item["sha256"] for item in json.loads(
    (SAMPLES / "image_ocr_constructed.json").read_text(encoding="utf-8")
)["samples"]}


def envelope(text=RULES, status="content", review_notes=None):
    return {"model": "step-5-preview-actual", "choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"status": status, "text": text,
                                                    "review_notes": review_notes or []})}}]}


@contextmanager
def step_server(reply=None, *, http_status=200, delay=0):
    import time

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            valid = (self.path == "/v1/chat/completions"
                     and self.headers.get("Authorization") == "Bearer test-key"
                     and self.headers.get_content_type() == "application/json"
                     and body["model"] == "step-5-preview"
                     and body["stream"] is False
                     and body["response_format"]["json_schema"]["strict"] is True)
            parts = body["messages"][0]["content"]
            picture = parts[1]["image_url"]
            mime, encoded = picture["url"].split(";base64,")
            valid = valid and picture["detail"] == "high" and parts[0]["type"] == "text"
            raw = base64.b64decode(encoded, validate=True)
            valid = valid and any(
                raw == path.read_bytes() and mime == "data:image/" + kind
                for path, kind in ((SAMPLES / "image_ocr_rules.png", "png"),
                                   (SAMPLES / "image_ocr_rules.jpg", "jpeg"),
                                   (SAMPLES / "image_ocr_rules.webp", "webp"),
                                   (SAMPLES / "image_ocr_blank.png", "png"))
            )
            valid = valid and all(word in parts[0]["text"] for word in ("OCR", "否定", "数字", "单位"))
            response = envelope() if reply is None else reply
            data = response if isinstance(response, bytes) else json.dumps(response).encode()
            time.sleep(delay)
            self.send_response(http_status if valid else 400)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield images.StepFunConfig(api_key="test-key", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                                   model="step-5-preview", timeout=1)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class ImageOcrTests(unittest.TestCase):
    def test_response_model_revision_is_not_invented_when_undisclosed(self):
        reply = envelope()
        del reply["model"]
        with step_server(reply) as config:
            result = images.convert_file(SAMPLES / "image_ocr_rules.png", task="ocr", config=config)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.requested_model, "step-5-preview")
        self.assertIsNone(result.response_model)
        self.assertTrue(result.requires_review)

    def test_invalid_service_responses_never_become_normal_empty_ocr(self):
        replies = [b"", b"not JSON test-key", {}, [], {"choices": []}]
        for content in ("", "not JSON test-key", "null", "[]", "{}",
                        json.dumps({"status": "no_text", "text": "visible text", "review_notes": []}),
                        json.dumps({"status": "content", "text": " ", "review_notes": []}),
                        json.dumps({"status": "no_text", "text": "", "review_notes": "invalid"}),
                        json.dumps({"status": "no_text", "text": "", "review_notes": [1]}),
                        json.dumps({"status": "no_text", "text": "", "review_notes": [], "confidence": 1}),
                        json.dumps({"status": "other", "text": "", "review_notes": []})):
            response = envelope()
            response["choices"][0]["message"]["content"] = content
            replies.append(response)
        for field, value in (("finish_reason", "length"), ("finish_reason", "content_filter"),
                             ("message", {}), ("message", {"content": None}),
                             ("message", {"content": "{}", "refusal": "test-key"})):
            response = envelope()
            response["choices"][0][field] = value
            replies.append(response)
        path = SAMPLES / "image_ocr_rules.png"
        for index, reply in enumerate(replies):
            with self.subTest(reply=index), step_server(reply) as config:
                result = images.convert_file(path, task="ocr", config=config)
                self.assertFalse(result.success)
                self.assertEqual(result.status, "failed")
                self.assertIsNone(result.text)
                self.assertEqual(result.error.code, "protocol_error")
                self.assertEqual(result.source.sha256, SAMPLE_HASHES[path.name])
                self.assertEqual(result.requested_model, "step-5-preview")
                self.assertNotIn("test-key", str(result.error))

    def test_http_failures_timeouts_and_connection_failures_preserve_input_facts(self):
        path = SAMPLES / "image_ocr_rules.png"
        for status, code in ((401, "authentication_error"), (403, "authentication_error"),
                             (429, "rate_limited"), (503, "service_error"), (400, "http_error")):
            with self.subTest(status=status), step_server(b"test-key private upstream response", http_status=status) as config:
                result = images.convert_file(path, task="ocr", config=config)
            self.assertFalse(result.success)
            self.assertIsNone(result.text)
            self.assertEqual(result.error.code, code)
            self.assertEqual(result.error.http_status, status)
            self.assertEqual(result.source.sha256, SAMPLE_HASHES[path.name])
            self.assertEqual((result.source.width, result.source.height), (1100, 340))
            self.assertEqual(result.requested_model, "step-5-preview")
            self.assertNotIn("test-key", str(result.error))
            self.assertNotIn("private upstream", str(result.error))
        with step_server(delay=0.15) as config:
            result = images.convert_file(path, task="ocr", config=replace(config, timeout=0.03))
            self.assertEqual(result.error.code, "timeout")
        result = images.convert_file(path, task="ocr", config=replace(config, timeout=5))
        self.assertEqual(result.error.code, "network_error")
        self.assertIsNone(result.text)

    def test_configuration_uses_only_explicit_values_or_process_environment(self):
        path = SAMPLES / "image_ocr_rules.png"
        with patch.dict(os.environ, {}, clear=True):
            result = images.convert_file(path, task="ocr")
            self.assertEqual(result.error.code, "missing_config")
            self.assertEqual(result.source.sha256, SAMPLE_HASHES[path.name])
            self.assertEqual((result.source.width, result.source.height), (1100, 340))
            self.assertIsNone(result.text)
        with step_server() as config, patch.dict(os.environ, {
            "STEP_API_KEY": config.api_key, "STEP_BASE_URL": config.base_url, "STEP_MODEL": config.model,
        }):
            result = images.convert_file(path, task="ocr")
            self.assertTrue(result.success, result.error)
        for field, value in (("timeout", 0), ("timeout", float("inf")), ("timeout", True),
                             ("api_key", "test-key\n"), ("base_url", "invalid"),
                             ("model", " ")):
            values = {"api_key": "test-key", "base_url": "http://127.0.0.1:1/v1", "model": "step-5-preview"}
            with self.subTest(field=field, value=value):
                result = images.convert_file(path, task="ocr", config=images.StepFunConfig(**(values | {field: value})))
                self.assertEqual(result.error.code, "invalid_config")
                self.assertNotIn("test-key", str(result.error))
        self.assertEqual(images.convert_file(path, task="ocr", config={}).error.code, "invalid_config")

    def test_decode_rejects_corrupt_mismatched_animated_and_multiframe_images(self):
        for filename, declared, code in (
            ("image_ocr_corrupt.png", "png", "image_decode_error"),
            ("image_ocr_rules.png", "jpeg", "format_mismatch"),
            ("image_ocr_static.gif", "png", "unsupported_format"),
            ("image_ocr_multiframe.png", "png", "multiframe_image"),
            ("image_ocr_multiframe.webp", "webp", "multiframe_image"),
            ("image_ocr_multiframe.tiff", "png", "unsupported_format"),
        ):
            path = SAMPLES / filename
            with self.subTest(filename=filename):
                result = images.convert_bytes(path.read_bytes(), format=declared, source=filename, task="ocr")
                self.assertEqual(result.error.code, code)
                self.assertFalse(result.success)
                self.assertIsNone(result.text)
                self.assertEqual(result.source.location, filename)
                self.assertEqual(result.source.sha256, SAMPLE_HASHES[filename])
                self.assertIsNone(result.source.width)
                self.assertIsNone(result.source.height)
        result = images.convert_bytes(b"", format="png", source="empty", task="ocr")
        self.assertEqual(result.error.code, "image_decode_error")

    def test_static_formats_aliases_and_file_override_use_actual_image_bytes(self):
        for filename, declared, expected_format in (
            ("image_ocr_rules.jpg", " .JPG ", "jpeg"),
            ("image_ocr_rules.webp", "WEBP", "webp"),
            ("image_ocr_override.bin", "png", "png"),
        ):
            path = SAMPLES / filename
            with self.subTest(filename=filename), step_server() as config:
                result = images.convert_file(path, format=declared, task="ocr", config=config)
                other = images.convert_bytes(path.read_bytes(), format=declared, source=str(path),
                                             task="ocr", config=config)
            self.assertEqual(result, other)
            self.assertTrue(result.success, result.error)
            self.assertEqual(result.source.format, expected_format)
            self.assertEqual(result.source.sha256, SAMPLE_HASHES[filename])
            self.assertEqual((result.source.width, result.source.height), (1100, 340))

    def test_invalid_options_and_file_read_failures_are_structured(self):
        path = SAMPLES / "image_ocr_rules.png"
        cases = [
            ({}, "invalid_options"),
            ({"task": "description"}, "invalid_options"),
            ({"task": ["ocr"]}, "invalid_options"),
            ({"task": "ocr", "question": "what?"}, "invalid_options"),
            ({"task": "ocr", "format": "gif"}, "unsupported_format"),
            ({"task": "ocr", "format": None}, "invalid_options"),
            ({"task": "ocr", "source": "  "}, "invalid_options"),
        ]
        for options, code in cases:
            arguments = {"format": "png", "source": "input.png"} | options
            with self.subTest(options=options):
                result = images.convert_bytes(path.read_bytes(), **arguments)
                self.assertFalse(result.success)
                self.assertEqual(result.status, "failed")
                self.assertIsNone(result.text)
                self.assertEqual(result.error.code, code)
                self.assertIsNone(result.source.width)
        result = images.convert_bytes(bytearray(b"wrong type"), format="png", source="upload", task="ocr")
        self.assertEqual(result.error.code, "invalid_options")
        result = images.convert_file(SAMPLES / "absent.png", task="ocr")
        self.assertEqual(result.error.code, "file_read_error")
        self.assertEqual(result.source.location, str(SAMPLES / "absent.png"))
        self.assertIsNone(result.source.sha256)
        self.assertIsNone(result.source.width)
        self.assertEqual(images.convert_file(None, task="ocr").error.code, "invalid_options")

    def test_file_and_bytes_extract_traceable_unverified_text(self):
        path = SAMPLES / "image_ocr_rules.png"
        with step_server() as config:
            result = images.convert_file(path, task="ocr", config=config)
            other = images.convert_bytes(path.read_bytes(), format="png", source=str(path),
                                         task="ocr", config=config)
        self.assertEqual(result, other)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.text, RULES)
        self.assertEqual((result.task, result.status), ("ocr", "content"))
        self.assertEqual(asdict(result.source), {
            "location": str(path), "format": "png",
            "sha256": SAMPLE_HASHES[path.name],
            "width": 1100, "height": 340,
        })
        self.assertTrue(result.requires_review)
        self.assertEqual(result.review_issues[0].code, "unverified_model_output")
        self.assertEqual(result.requested_model, "step-5-preview")
        self.assertEqual(result.response_model, "step-5-preview-actual")
        self.assertEqual(result.prompt_version, "ocr-v1")
        self.assertEqual(result.warnings, [])
        self.assertIsNone(result.error)

    def test_normal_empty_ocr_is_unverified_and_keeps_uncertainty_separate(self):
        path = SAMPLES / "image_ocr_blank.png"
        with step_server(envelope("", "no_text", ["未取得可辨认文字"])) as config:
            result = images.convert_file(path, task="ocr", config=config)
        self.assertTrue(result.success, result.error)
        self.assertEqual((result.status, result.text), ("no_text", ""))
        self.assertTrue(result.requires_review)
        self.assertEqual(result.review_issues[1].message, "未取得可辨认文字")
        self.assertEqual(result.review_issues[1].code, "model_uncertainty")
        self.assertIn("不证明图片没有文字", result.warnings[0])
        self.assertEqual((result.source.width, result.source.height), (320, 240))
        self.assertEqual(result.source.sha256, SAMPLE_HASHES[path.name])


if __name__ == "__main__":
    unittest.main()
