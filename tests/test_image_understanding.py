import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import threading
import unittest


images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
SAMPLES = Path(__file__).parent / "testFile"
MANIFEST = json.loads((SAMPLES / "image_understanding_constructed.json").read_text(encoding="utf-8"))
QUESTION = MANIFEST["question"]
CLEAR_ANSWER = "金额超过1万元时，沿“是”箭头由负责人审批；其他情况沿“否”箭头由财务审批。"


def envelope(*, status="content", text=CLEAR_ANSWER, notes=None):
    return {"model": "step-5-preview-actual", "choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"status": status, "text": text, "review_notes": notes or []})}}]}


@contextmanager
def step_server(reply=None, *, status=200):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append({"path": self.path, "authorization": self.headers.get("Authorization"),
                             "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            payload = json.dumps(envelope() if reply is None else reply).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield images.StepFunConfig(api_key="test-key", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                                   model="step-5-preview", timeout=2), requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class ImageUnderstandingTests(unittest.TestCase):
    def test_file_read_failure_keeps_valid_question_without_a_partial_answer(self):
        result = images.convert_file(SAMPLES / "image_understanding_missing.png", task="understand",
                                     question=QUESTION)
        self.assertFalse(result.success)
        self.assertIsNone(result.text)
        self.assertEqual(result.error.code, "file_read_error")
        self.assertEqual(result.question, QUESTION)

    def test_api_failures_keep_question_and_image_identity_separate_from_body(self):
        path = SAMPLES / "image_understanding_clear.png"
        for status, code in ((401, "authentication_error"), (503, "service_error")):
            with self.subTest(status=status), step_server(
                {"error": "test-key private upstream details"}, status=status,
            ) as (config, requests):
                result = images.convert_bytes(path.read_bytes(), format="png", source=path.name,
                                              task="understand", question=QUESTION, config=config)
            self.assertEqual(result.status, "failed")
            self.assertFalse(result.success)
            self.assertIsNone(result.text)
            self.assertEqual(result.error.code, code)
            self.assertEqual(result.error.http_status, status)
            self.assertNotIn("test-key", str(result.error))
            self.assertEqual(result.question, QUESTION)
            self.assertEqual(result.source.sha256, MANIFEST["samples"][0]["sha256"])
            self.assertEqual((result.source.width, result.source.height), (1200, 850))
            self.assertEqual(len(requests), 1)

    def test_uncertain_response_requires_a_reason_and_invalid_responses_have_no_partial_answer(self):
        path = SAMPLES / "image_understanding_blurred.png"
        replies = [envelope(status="uncertain", text="可见两个审批节点，但无法确认条件与节点的对应。"),
                   envelope(status="no_text", text=""), envelope(status="content", text=" "),
                   envelope(status="uncertain", text="", notes=["箭头模糊"]),
                   envelope(notes=[9])]
        for content in ("null", "[]", "not JSON", json.dumps({
            "status": "uncertain", "text": "连线模糊", "review_notes": "无法确认"}), json.dumps({
            "status": "uncertain", "text": "连线模糊", "review_notes": ["箭头模糊"], "confidence": 1})):
            reply = envelope()
            reply["choices"][0]["message"]["content"] = content
            replies.append(reply)
        for index, reply in enumerate(replies):
            with self.subTest(reply=index), step_server(reply) as (config, requests):
                result = images.convert_file(path, task="understand", question=QUESTION, config=config)
                self.assertFalse(result.success)
                self.assertIsNone(result.text)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.error.code, "protocol_error")
                self.assertEqual(result.question, QUESTION)
                self.assertEqual(result.source.sha256, MANIFEST["samples"][1]["sha256"])
                self.assertEqual(len(requests), 1)

    def test_blurred_and_truncated_images_keep_known_content_reason_and_source_as_normal_uncertain(self):
        cases = [
            ("blurred", "可见金额条件及两个审批节点，但无法确认两条分支分别对应哪个审批人，因为中段连线及箭头模糊。", "关键连线及箭头模糊"),
            ("truncated", "可见金额条件和是/否起点，但无法确认分支终点与审批人，因为截图截断了下半部分。", "审批节点及箭头终点被截去"),
        ]
        for index, (name, text, reason) in enumerate(cases, start=1):
            path = SAMPLES / f"image_understanding_{name}.png"
            with self.subTest(sample=name), step_server(envelope(
                status="uncertain", text=text, notes=[reason],
            )) as (config, requests):
                result = images.convert_file(path, task="understand", question=QUESTION, config=config)
                other = images.convert_bytes(path.read_bytes(), format="png", source=str(path),
                                             task="understand", question=QUESTION, config=config)
            self.assertEqual(result, other)
            self.assertTrue(result.success, result.error)
            self.assertEqual((result.status, result.text), ("uncertain", text))
            self.assertTrue(result.requires_review)
            self.assertEqual((result.review_issues[1].code, result.review_issues[1].message),
                             ("model_uncertainty", reason))
            self.assertIsNone(result.error)
            self.assertEqual(result.warnings, [])
            self.assertEqual(result.question, QUESTION)
            self.assertEqual(result.source.sha256, MANIFEST["samples"][index]["sha256"])
            for request in requests:
                url = request["body"]["messages"][0]["content"][1]["image_url"]["url"]
                self.assertEqual(base64.b64decode(url.split(";base64,")[1]), path.read_bytes())

    def test_missing_blank_or_non_string_question_fails_at_both_public_entries_before_http(self):
        path = SAMPLES / "image_understanding_clear.png"
        with step_server() as (config, requests):
            for question in (None, "", " \n\t", 3, True, [QUESTION], {"question": QUESTION}):
                with self.subTest(question=question):
                    results = (
                        images.convert_file(path, task="understand", question=question, config=config),
                        images.convert_bytes(path.read_bytes(), format="png", source=path.name,
                                             task="understand", question=question, config=config),
                    )
                    for result in results:
                        self.assertFalse(result.success)
                        self.assertEqual(result.status, "failed")
                        self.assertIsNone(result.text)
                        self.assertEqual(result.error.code, "invalid_options")
        self.assertEqual(len(requests), 0)

    def test_file_and_bytes_answer_with_this_image_and_original_question_in_one_request(self):
        path = SAMPLES / "image_understanding_clear.png"
        question = "  " + QUESTION + "\n"
        with step_server() as (config, requests):
            result = images.convert_file(path, task="understand", question=question, config=config)
            other = images.convert_bytes(path.read_bytes(), format="png", source=str(path),
                                         task="understand", question=question, config=config)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result, other)
        self.assertEqual((result.task, result.status, result.text), ("understand", "content", CLEAR_ANSWER))
        self.assertEqual(result.question, question)
        self.assertEqual(result.prompt_version, "understand-v2")
        self.assertEqual((result.requested_model, result.response_model),
                         ("step-5-preview", "step-5-preview-actual"))
        self.assertTrue(result.requires_review)
        self.assertEqual(result.review_issues[0].code, "unverified_model_output")
        self.assertIsNone(result.error)
        self.assertEqual(result.source.sha256, MANIFEST["samples"][0]["sha256"])
        self.assertEqual((result.source.width, result.source.height), (1200, 850))
        self.assertEqual(result.source.location, str(path))
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(request["path"], "/v1/chat/completions")
            self.assertEqual(request["authorization"], "Bearer test-key")
            body = request["body"]
            self.assertEqual(body["model"], "step-5-preview")
            self.assertEqual(len(body["messages"]), 1)
            parts = body["messages"][0]["content"]
            self.assertEqual(len(parts), 2)
            self.assertEqual(parts[0]["type"], "text")
            self.assertIn(question, parts[0]["text"])
            self.assertIn("视觉理解", parts[0]["text"])
            self.assertNotIn("负责人", parts[0]["text"])
            self.assertNotIn("财务", parts[0]["text"])
            self.assertNotIn(path.name, parts[0]["text"])
            picture = parts[1]["image_url"]
            mime, encoded = picture["url"].split(";base64,")
            self.assertEqual(mime, "data:image/png")
            self.assertEqual(base64.b64decode(encoded, validate=True), path.read_bytes())
            schema = body["response_format"]["json_schema"]
            self.assertTrue(schema["strict"])
            self.assertEqual(schema["schema"]["properties"]["status"]["enum"], ["content", "uncertain"])
            self.assertEqual(set(schema["schema"]["required"]), {"status", "text", "review_notes"})


if __name__ == "__main__":
    unittest.main()
