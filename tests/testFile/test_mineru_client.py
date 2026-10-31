from dataclasses import asdict
import importlib
import unittest

from tests.test_pdf_word_mineru import HISTORY, mineru_server
from tests.zip_document_support import SAMPLES, document_server


ROOT = "app.modules.1_documentIngestionAndParsing"
legacy = importlib.import_module(f"{ROOT}.3_pdfAndWordParsing.mineru")


class MinerUClientCompatibilityTests(unittest.TestCase):
    def test_legacy_configuration_is_accepted_by_canonical_pdf_client(self):
        canonical = importlib.import_module(f"{ROOT}.pdfAndDocxExtraction.mineru")
        self.assertIs(canonical.MinerUConfig, legacy.MinerUConfig)
        self.assertIs(canonical.MinerUError, legacy.MinerUError)
        self.assertIs(canonical.MinerUClient, legacy.MinerUClient)
        data = (SAMPLES / "pdf_scanned_teaching.pdf").read_bytes()
        with mineru_server() as config:
            legacy_config = legacy.MinerUConfig(**asdict(config))
            blocks = canonical.MinerUClient(legacy_config).extract(data, 1)
        self.assertEqual(blocks, HISTORY)

    def test_legacy_configuration_is_accepted_by_shared_document_client(self):
        shared = importlib.import_module(f"{ROOT}.mineru_client")
        hosted = importlib.import_module(f"{ROOT}.hosted_documents")
        pdf = importlib.import_module(f"{ROOT}.3_pdfAndWordParsing")
        self.assertIs(shared.MinerUConfig, legacy.MinerUConfig)
        self.assertIs(shared.MinerUConfig, hosted.MinerUConfig)
        self.assertIs(shared.MinerUConfig, pdf.MinerUConfig)
        self.assertIs(shared.MinerUError, legacy.MinerUError)
        data = (SAMPLES / "docx_sections.docx").read_bytes()
        with document_server() as service:
            archive = shared.MinerUClient(service.config).extract_document(
                data, filename="document.docx",
            )
        self.assertEqual(archive, (SAMPLES / "zip_document_result.zip").read_bytes())
        self.assertEqual(service.requests, [{
            "files": [{"name": "document.docx"}], "model_version": "vlm",
            "language": "ch", "enable_table": True,
        }])
        self.assertEqual(service.uploads, [data])

    def test_shared_client_returns_opaque_result_bytes_for_html(self):
        shared = importlib.import_module(f"{ROOT}.mineru_client")
        result = b"opaque service result interpreted by the caller"
        data = b"<html><body>original document</body></html>"
        with document_server(result_bytes=result) as service:
            archive = shared.MinerUClient(service.config).extract_document(
                data, filename="document.html", model_version="MinerU-HTML",
                is_ocr=True, max_archive_bytes=len(result),
            )
        self.assertEqual(archive, result)
        self.assertEqual(service.requests, [{
            "files": [{"name": "document.html"}], "model_version": "MinerU-HTML",
        }])
        self.assertEqual(service.uploads, [data])

    def test_shared_failures_remain_legacy_errors_without_retries(self):
        shared = importlib.import_module(f"{ROOT}.mineru_client")
        cases = (
            ("auth", "MinerU API A0202", 0, 0),
            ("quota", "MinerU API -50001", 0, 0),
            ("apply-http", "MinerU request HTTP 503", 0, 0),
            ("upload", "MinerU upload HTTP 503", 1, 0),
            ("failed", "MinerU parsing failed:", 1, 1),
        )
        for failure, error, uploads, polls in cases:
            with self.subTest(failure=failure):
                with document_server(failure=failure) as service:
                    with self.assertRaisesRegex(legacy.MinerUError, error):
                        shared.MinerUClient(service.config).extract_document(
                            b"original document", filename="document.docx",
                        )
                self.assertEqual(len(service.requests), 1)
                self.assertEqual(len(service.uploads), uploads)
                self.assertEqual(service.polls, polls)

    def test_shared_download_keeps_size_and_deadline_contracts(self):
        shared = importlib.import_module(f"{ROOT}.mineru_client")
        result = b"opaque service result"
        with document_server(result_bytes=result, no_length=True) as service:
            with self.assertRaisesRegex(legacy.MinerUError, "exceeds max_archive_bytes"):
                shared.MinerUClient(service.config).extract_document(
                    b"original document", filename="document.docx",
                    max_archive_bytes=len(result) - 1,
                )

        class DeadlineReached(Exception):
            pass

        stopped = DeadlineReached("caller deadline reached")
        checks = []

        def check_deadline():
            checks.append(True)
            if len(checks) == 2:
                raise stopped

        with document_server(result_bytes=result, no_length=True) as service:
            with self.assertRaises(DeadlineReached) as caught:
                shared.MinerUClient(service.config).extract_document(
                    b"original document", filename="document.docx",
                    max_archive_bytes=len(result), check_result_deadline=check_deadline,
                )
        self.assertIs(caught.exception, stopped)
        self.assertEqual(len(checks), 2)


if __name__ == "__main__":
    unittest.main()
