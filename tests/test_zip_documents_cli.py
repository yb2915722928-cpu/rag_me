from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tests.zip_document_support import SAMPLES, SERVICE_MARKDOWN, document_server


ROOT = Path(__file__).resolve().parents[1]
MODULE = "app.modules.1_documentIngestionAndParsing.8_zipContainers"


class ZipDocumentCliTests(unittest.TestCase):
    def test_cli_accepts_plain_mineru_configuration_and_reports_document_without_configuration(self):
        for failure, fixture, code, status in (
            (None, "zip_document_pdf.zip", 0, "success"),
            ("auth", "zip_document_pdf.zip", 2, "partial_success"),
            ("format", "zip_document_office.zip", 1, "failed"),
        ):
            with self.subTest(status=status), document_server(failure=failure) as service:
                completed = subprocess.run(
                    [sys.executable, "-m", MODULE, str(SAMPLES / fixture), "--parser-options",
                     json.dumps({"document": {"mineru": asdict(service.config)}})],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(completed.returncode, code, completed.stderr)
                self.assertEqual(completed.stderr, "")
                report = json.loads(completed.stdout)
                self.assertEqual(report["status"], status)
                self.assertNotIn("test-token", completed.stdout)
                self.assertNotIn("api_base", completed.stdout)
                self.assertNotIn("private.invalid", completed.stdout)
                self.assertNotIn("/upload", completed.stdout)
                if not failure:
                    self.assertEqual(report["members"][0]["result"]["markdown"], SERVICE_MARKDOWN)
                    self.assertTrue(report["members"][0]["result"]["success"])
                else:
                    self.assertIn("A0202" if failure == "auth" else "-60001", report["members"][0]["error"])


if __name__ == "__main__":
    unittest.main()
