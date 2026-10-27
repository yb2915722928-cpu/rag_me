import importlib
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
)
SAMPLES = Path(__file__).parent / "testFile"
HISTORY = [
    {"type": "text", "text": "Disconnect power before maintenance.", "page_idx": 0},
    {"type": "text", "text": "Inspect every month.", "page_idx": 0},
]


@contextmanager
def mineru_server(blocks=HISTORY, input_name="pdf_scanned_teaching.pdf", failure=None):
    pdf = (SAMPLES / input_name).read_bytes()
    archive = BytesIO()
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("full.md", "Unpaginated service Markdown")
        if failure != "missing-list":
            zipped.writestr("generated_content_list.json", json.dumps(blocks))

    class Handler(BaseHTTPRequestHandler):
        polls = 0

        def log_message(self, *args):
            pass

        def reply(self, value, status=200):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if failure == "apply-http":
                return self.reply(b"unavailable", 503)
            if failure == "quota":
                return self.reply({"code": -50001, "msg": "quota exhausted"})
            if failure == "invalid-json":
                return self.reply(b"not JSON")
            if failure == "bad-envelope":
                return self.reply({"unexpected": True})
            if failure == "bad-apply":
                return self.reply({"code": 0, "data": {"batch_id": "test-batch"}})
            if (self.path != "/api/v4/file-urls/batch"
                    or self.headers.get("Authorization") != "Bearer test-token"
                    or data["model_version"] != "vlm"
                    or not data["files"][0]["is_ocr"]):
                return self.reply({"code": -1, "msg": "invalid apply request"}, 400)
            Handler.polls = 0
            self.reply({"code": 0, "data": {
                "batch_id": "test-batch", "file_urls": [base + "/signed-upload"]
            }})

        def do_PUT(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            if failure == "upload-http":
                return self.reply(b"unavailable", 503)
            if (self.path != "/signed-upload" or data != pdf
                    or self.headers.get("Authorization")
                    or self.headers.get("Content-Type")):
                return self.reply(b"invalid raw upload", 400)
            self.reply(b"")

        def do_GET(self):
            if self.path == "/signed-result":
                if failure == "download-http":
                    return self.reply(b"unavailable", 503)
                if failure == "invalid-zip":
                    return self.reply(b"not a ZIP")
                if self.headers.get("Authorization"):
                    return self.reply(b"unexpected credentials on download", 400)
                return self.reply(archive.getvalue())
            if (self.path != "/api/v4/extract-results/batch/test-batch"
                    or self.headers.get("Authorization") != "Bearer test-token"):
                return self.reply({"code": -1}, 400)
            Handler.polls += 1
            if failure == "poll-http":
                return self.reply(b"unavailable", 503)
            if failure == "bad-poll":
                return self.reply({"code": 0, "data": {}})
            if failure == "unknown-state" and Handler.polls == 1:
                return self.reply({"code": 0, "data": {"extract_result": [{"state": "unknown"}]}})
            if failure in {"failed", "sensitive-failure"} and Handler.polls == 1:
                return self.reply({"code": 0, "data": {"extract_result": [{
                    "state": "failed", "err_msg": (
                        "engine unavailable" if failure == "failed" else
                        "test-token rejected https://storage.invalid/file?signature=private"
                    ),
                }]}})
            self.reply({"code": 0, "data": {"extract_result": [{
                "state": "pending" if Handler.polls == 1 else "done",
                "full_zip_url": base + "/signed-result",
            }]}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield content.MinerUConfig(
            api_base=base + "/api/v4", token="test-token", poll_interval=0,
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class ScannedPdfConversionTests(unittest.TestCase):
    def test_omitted_config_token_is_read_from_the_environment(self):
        with patch.dict(os.environ, {"MINERU_API_TOKEN": "test-token"}):
            with mineru_server() as api:
                api.token = None
                result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)
        self.assertTrue(result.success, result.error)

    def test_images_and_empty_ocr_text_are_not_a_success_body(self):
        for blocks in ([], [{"type": "image", "img_path": "images/page.jpg", "page_idx": 0}],
                       [{"type": "text", "text": " ", "page_idx": 0}]):
            with self.subTest(blocks=blocks):
                with mineru_server(blocks) as api:
                    result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn("page 1", result.error)

    def test_invalid_api_configuration_is_an_entry_error_for_file_and_bytes(self):
        path = SAMPLES / "pdf_scanned_teaching.pdf"
        results = (
            content.convert_file(path, mineru="invalid"),
            content.convert_bytes(path.read_bytes(), format="pdf", source="scan.pdf", mineru="invalid"),
        )
        for result in results:
            self.assertFalse(result.success)
            self.assertIsNone(result.markdown)
            self.assertIn("MinerUConfig", result.error)

    def test_invalid_upload_and_poll_protocol_returns_diagnostics(self):
        for failure in ("bad-envelope", "bad-apply", "bad-poll", "unknown-state"):
            with self.subTest(failure=failure):
                with mineru_server(failure=failure) as api:
                    result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertIn("MinerU", result.error)

    def test_content_list_validates_actual_page_indices_and_text_at_the_http_boundary(self):
        invalid = [
            {}, [None],
            [{"type": "text", "text": "wrong page", "page_idx": 1}],
            [{"type": "text", "text": "wrong page", "page_idx": -1}],
            [{"type": "text", "text": "missing page"}],
            [{"type": "text", "text": 12, "page_idx": 0}],
            [{"type": "text", "text": "title", "text_level": "1", "page_idx": 0}],
        ]
        for blocks in invalid:
            with self.subTest(blocks=blocks):
                with mineru_server(blocks) as api:
                    result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn("content_list", result.error)

    def test_invalid_remote_json_zip_and_missing_content_list_are_explicit_failures(self):
        for failure, expected in (("invalid-json", "JSON"), ("invalid-zip", "ZIP"),
                                  ("missing-list", "content_list")):
            with self.subTest(failure=failure):
                with mineru_server(failure=failure) as api:
                    result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn(expected, result.error)

    def test_service_business_failure_is_not_treated_as_http_success(self):
        with mineru_server(failure="quota") as api:
            result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertIn("-50001", result.error)
        self.assertIn("quota exhausted", result.error)

    def test_image_only_table_warns_relationships_were_not_recovered(self):
        for body in ("", "Pump Monthly Valve Quarterly"):
            with self.subTest(body=body):
                blocks = HISTORY + [{"type": "table", "img_path": "images/table.jpg",
                                     "table_body": body, "page_idx": 0}]
                with mineru_server(blocks) as api:
                    result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)
                self.assertTrue(result.success, result.error)
                self.assertNotIn("images/", result.markdown)
                self.assertTrue(any("page 1" in w and "table relationships" in w for w in result.warnings))

    def test_missing_scan_page_is_not_reported_as_a_complete_two_page_document(self):
        with mineru_server(HISTORY, "pdf_scanned_maintenance_table.pdf") as api:
            result = content.convert_file(SAMPLES / "pdf_scanned_maintenance_table.pdf", mineru=api)

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertEqual(result.sources, [])
        self.assertIn("page 2", result.error)

    def test_http_errors_at_each_system_boundary_return_failure_diagnostics(self):
        for stage in ("apply-http", "upload-http", "poll-http", "download-http"):
            with self.subTest(stage=stage):
                with mineru_server(failure=stage) as api:
                    result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn("503", result.error)
                self.assertIn("1", result.error)

    def test_remote_diagnostics_do_not_expose_credentials_or_signed_urls(self):
        with mineru_server(failure="sensitive-failure") as api:
            result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)

        self.assertFalse(result.success)
        self.assertNotIn("test-token", result.error)
        self.assertNotIn("https://", result.error)
        self.assertNotIn("signature=", result.error)

    def test_pending_task_has_a_bounded_wait_instead_of_indefinite_polling(self):
        with mineru_server() as api:
            api.max_wait = 0.01
            api.poll_interval = 0.02
            result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertIn("timed out", result.error)
        self.assertIn("1", result.error)

    def test_remote_failure_returns_page_diagnostic_without_partial_success_body(self):
        with mineru_server(failure="failed") as api:
            result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertEqual(result.sources, [])
        self.assertIn("page", result.error)
        self.assertIn("1", result.error)
        self.assertIn("engine unavailable", result.error)

    def test_scanned_table_stays_between_rules_and_restart_with_real_page_sources(self):
        table = ("<table><tr><th>Equipment</th><th>Interval</th></tr>"
                 "<tr><td>Pump</td><td>Monthly</td></tr>"
                 "<tr><td>Valve</td><td>Quarterly</td></tr></table>")
        blocks = [
            {"type": "text", "text": "Equipment Maintenance", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "Disconnect power before maintenance.", "page_idx": 0},
            {"type": "table", "table_body": table, "page_idx": 0},
            {"type": "text", "text": "Restart after inspection.", "page_idx": 0},
            {"type": "text", "text": "Temperature must not exceed 60 C.", "page_idx": 1},
        ]
        with mineru_server(blocks, "pdf_scanned_maintenance_table.pdf") as api:
            result = content.convert_file(SAMPLES / "pdf_scanned_maintenance_table.pdf", mineru=api)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.markdown,
                         "# Equipment Maintenance\n\nDisconnect power before maintenance.\n\n"
                         + table + "\n\nRestart after inspection.\n\n"
                         "Temperature must not exceed 60 C.\n")
        self.assertEqual([s.pdf_page_number for s in result.sources], [1, 2])
        first, second = result.sources
        self.assertIn(table, result.markdown[first.markdown_start:first.markdown_end])
        self.assertEqual(result.markdown[second.markdown_start:second.markdown_end],
                         "Temperature must not exceed 60 C.\n")

    def test_missing_token_is_page_specific_failure_without_body(self):
        with mineru_server() as api:
            api.token = ""
            result = content.convert_file(SAMPLES / "pdf_scanned_teaching.pdf", mineru=api)

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertEqual(result.sources, [])
        self.assertIn("MINERU_API_TOKEN", result.error)
        self.assertIn("1", result.error)
        self.assertTrue(any("page 1" in w for w in result.warnings))

    def test_scan_file_and_bytes_upload_poll_and_return_known_body_with_page_source(self):
        path = SAMPLES / "pdf_scanned_teaching.pdf"
        with mineru_server() as api:
            from_file = content.convert_file(path, source="history.pdf", mineru=api)
            from_bytes = content.convert_bytes(
                path.read_bytes(), format="pdf", source="history.pdf", mineru=api,
            )

        self.assertTrue(from_file.success, from_file.error)
        self.assertEqual(from_file, from_bytes)
        self.assertEqual(from_file.markdown,
                         "Disconnect power before maintenance.\n\nInspect every month.\n")
        self.assertEqual(from_file.source.location, "history.pdf")
        self.assertEqual([s.pdf_page_number for s in from_file.sources], [1])
        page = from_file.sources[0]
        self.assertEqual(page.extraction_method, "mineru_api")
        self.assertEqual(from_file.markdown[page.markdown_start:page.markdown_end],
                         from_file.markdown)


if __name__ == "__main__":
    unittest.main()
