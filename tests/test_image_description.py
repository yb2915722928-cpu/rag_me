import base64
from contextlib import contextmanager
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler
import importlib
import json
from pathlib import Path
import time
import unittest

from tests.image_test_support import image_server


images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
SAMPLES = Path(__file__).parent / "testFile"
DESCRIPTION = "湖畔的露营场景，橙色帐篷周围有山峦、树木和湖水。"
HASHES = {item["filename"]: item["sha256"] for item in json.loads(
    (SAMPLES / "image_description_constructed.json").read_text(encoding="utf-8")
)["samples"]}


def envelope(text=DESCRIPTION, status="content", review_notes=None):
    return {"model": "step-5-description-actual", "choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"status": status, "text": text, "review_notes": review_notes or []})}}]}


@contextmanager
def description_server(reply=None, *, http_status=200, delay=0):
    exchanges = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            exchanges.append({"path": self.path, "authorization": self.headers.get("Authorization"),
                              "content_type": self.headers.get_content_type(),
                              "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            response = envelope() if reply is None else reply
            data = response if isinstance(response, bytes) else json.dumps(response).encode()
            time.sleep(delay)
            self.send_response(http_status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    with image_server(Handler) as base_url:
        yield images.StepFunConfig(api_key="description-test-key",
                                   base_url=base_url,
                                   model="step-5-preview", timeout=1), exchanges


class ImageDescriptionTests(unittest.TestCase):
    def test_file_and_bytes_describe_equivalently_for_each_static_format(self):
        for extension, declared, mime in (("png", ".PNG", "png"), ("jpg", " .JPG ", "jpeg"),
                                          ("webp", "WEBP", "webp")):
            path = SAMPLES / f"image_description_camping.{extension}"
            with self.subTest(format=extension), description_server() as (config, exchanges):
                from_file = images.convert_file(path, source="upload/露营", task="describe", config=config)
                from_bytes = images.convert_bytes(path.read_bytes(), format=declared, source="upload/露营",
                                                 task="describe", config=config)
            self.assertTrue(from_file.success, from_file.error)
            self.assertEqual(asdict(from_file), asdict(from_bytes))
            self.assertEqual(from_file.source.sha256, HASHES[path.name])
            self.assertEqual(from_file.source.location, "upload/露营")
            self.assertEqual(from_file.source.format, mime)
            self.assertEqual(len(exchanges), 2)
            for request in exchanges:
                parts = request["body"]["messages"][0]["content"]
                prefix, encoded = parts[1]["image_url"]["url"].split(";base64,")
                self.assertEqual(prefix, "data:image/" + mime)
                self.assertEqual(base64.b64decode(encoded, validate=True), path.read_bytes())

    def test_unusable_description_responses_are_errors_without_partial_body(self):
        replies = [b"", b"not JSON", {}, envelope(text=""), envelope(text=" \n\t"),
                   envelope(text="可见画面", status="uncertain"), envelope(text=7),
                   envelope(review_notes=[" "])]
        for content in ("not JSON", "[]", '{"status":"content","text":"画面"}',
                        '{"status":"content","text":"画面","review_notes":"note"}'):
            reply = envelope()
            reply["choices"][0]["message"]["content"] = content
            replies.append(reply)
        reply = envelope()
        reply["choices"][0]["finish_reason"] = "length"
        replies.append(reply)
        path = SAMPLES / "image_description_approval.png"
        for index, reply in enumerate(replies):
            with self.subTest(reply=index), description_server(reply) as (config, exchanges):
                result = images.convert_file(path, task="describe", config=config)
            self.assertFalse(result.success)
            self.assertEqual(result.status, "failed")
            self.assertIsNone(result.text)
            self.assertEqual(result.error.code, "protocol_error")
            self.assertEqual(result.source.sha256, HASHES[path.name])
            self.assertEqual(result.source.location, str(path))
            self.assertEqual((result.source.width, result.source.height), (1200, 780))
            self.assertEqual(result.prompt_version, "describe-v1")
            self.assertEqual(len(exchanges), 1)

    def test_service_failures_keep_description_diagnostics_separate_and_do_not_retry(self):
        path = SAMPLES / "image_description_approval.png"
        for status, code in ((401, "authentication_error"), (429, "rate_limited"), (503, "service_error")):
            with self.subTest(http_status=status), description_server(
                b"description-test-key private upstream detail", http_status=status,
            ) as (config, exchanges):
                result = images.convert_bytes(path.read_bytes(), format="png", source=path.name,
                                              task="describe", config=config)
            self.assertFalse(result.success)
            self.assertIsNone(result.text)
            self.assertEqual(result.error.code, code)
            self.assertEqual(result.error.http_status, status)
            self.assertEqual(result.source.sha256, HASHES[path.name])
            self.assertEqual((result.source.width, result.source.height), (1200, 780))
            self.assertEqual(result.requested_model, "step-5-preview")
            self.assertEqual(result.prompt_version, "describe-v1")
            self.assertNotIn("description-test-key", str(result.error))
            self.assertNotIn("private upstream", str(result.error))
            self.assertEqual(len(exchanges), 1)
        with description_server(delay=0.15) as (config, exchanges):
            result = images.convert_file(path, task="describe", config=replace(config, timeout=0.03))
        self.assertEqual(result.error.code, "timeout")
        self.assertIsNone(result.text)
        self.assertEqual(len(exchanges), 1)

    def test_describe_rejects_question_at_both_entries_without_submitting_image(self):
        path = SAMPLES / "image_description_approval.png"
        with description_server() as (config, exchanges):
            for question in ("谁负责审批？", "", " "):
                with self.subTest(question=question):
                    results = [
                        images.convert_file(path, task="describe", question=question, config=config),
                        images.convert_bytes(path.read_bytes(), format="png", source=path.name,
                                             task="describe", question=question, config=config),
                    ]
                    for result in results:
                        self.assertFalse(result.success)
                        self.assertIsNone(result.text)
                        self.assertEqual(result.error.code, "invalid_options")
                        self.assertIn("describe does not accept question", result.error.message)
            self.assertEqual(exchanges, [])

    def test_description_rejects_no_text_instead_of_borrowing_empty_ocr_semantics(self):
        path = SAMPLES / "image_description_camping.png"
        with description_server(envelope(text="", status="no_text")) as (config, exchanges):
            result = images.convert_bytes(path.read_bytes(), format="png", source=path.name,
                                          task="describe", config=config)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.text)
        self.assertEqual(result.error.code, "protocol_error")
        self.assertIn("describe", result.error.message)
        self.assertEqual(result.source.sha256, HASHES[path.name])
        self.assertEqual(result.review_issues, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(exchanges), 1)

    def test_describe_sends_only_current_image_and_returns_traceable_unverified_summary(self):
        path = SAMPLES / "image_description_camping.png"
        with description_server(envelope(review_notes=["场景细节仍需对照原图。 "])) as (config, exchanges):
            result = images.convert_file(path, task="describe", config=config)
        self.assertTrue(result.success, result.error)
        self.assertEqual((result.task, result.status, result.text), ("describe", "content", DESCRIPTION))
        self.assertEqual((result.source.location, result.source.format), (str(path), "png"))
        self.assertEqual((result.source.width, result.source.height), (960, 640))
        self.assertEqual(result.source.sha256, HASHES[path.name])
        self.assertEqual(result.requested_model, "step-5-preview")
        self.assertEqual(result.response_model, "step-5-description-actual")
        self.assertEqual(result.prompt_version, "describe-v1")
        self.assertTrue(result.requires_review)
        self.assertEqual([note.code for note in result.review_issues],
                         ["unverified_model_output", "model_uncertainty"])
        self.assertEqual(result.review_issues[1].message, "场景细节仍需对照原图。 ")
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(exchanges), 1)
        request = exchanges[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["authorization"], "Bearer description-test-key")
        self.assertEqual(request["content_type"], "application/json")
        body = request["body"]
        self.assertEqual(body["model"], "step-5-preview")
        self.assertFalse(body["stream"])
        self.assertEqual(len(body["messages"]), 1)
        parts = body["messages"][0]["content"]
        self.assertEqual([part["type"] for part in parts], ["text", "image_url"])
        self.assertIn("图像描述", parts[0]["text"])
        self.assertIn("主题", parts[0]["text"])
        self.assertIn("业务规则", parts[0]["text"])
        self.assertNotIn(DESCRIPTION, parts[0]["text"])
        picture = parts[1]["image_url"]
        self.assertEqual(picture["detail"], "high")
        mime, encoded = picture["url"].split(";base64,")
        self.assertEqual(mime, "data:image/png")
        self.assertEqual(base64.b64decode(encoded, validate=True), path.read_bytes())
        schema = body["response_format"]["json_schema"]
        self.assertTrue(schema["strict"])
        self.assertEqual(schema["schema"]["properties"]["status"]["enum"], ["content"])


if __name__ == "__main__":
    unittest.main()
