import importlib
from pathlib import Path
import time
import unittest

from tests.zip_document_support import SERVICE_MARKDOWN, document_server


SAMPLES = Path(__file__).parent / "testFile"


class HostedDocumentTests(unittest.TestCase):
    def test_document_bytes_can_be_parsed_and_handed_off_without_a_container(self):
        hosted = importlib.import_module(
            "app.modules.1_documentIngestionAndParsing.hosted_documents"
        )
        handoff = importlib.import_module(
            "app.modules.1_documentIngestionAndParsing.unifiedDocumentHandoff"
        )
        budget = importlib.import_module(
            "app.modules.1_documentIngestionAndParsing.archive_budget"
        )
        data = (SAMPLES / "pdf_digital_page_order.pdf").read_bytes()
        with document_server() as service:
            result = hosted.convert_bytes(
                data, format="pdf", source="manual.pdf", mineru=service.config,
                limits=budget.ArchiveLimits(), deadline=time.monotonic() + 30,
            )
            self.assertTrue(result.success, result.error)
            report = handoff.adapt_result(result, business_id="manual", version="v1")
        self.assertEqual(service.uploads, [data])
        self.assertEqual(len(service.requests), 1)
        self.assertEqual(result.markdown, SERVICE_MARKDOWN)
        self.assertEqual(result.source, "manual.pdf")
        self.assertEqual(result.sources[0].pdf_page_number, 1)
        self.assertEqual(result.sources[0].page_origin, "uploaded_pdf")
        self.assertTrue(result.requires_review)
        self.assertEqual(report.status, "success")
        document = report.documents[0]
        self.assertEqual(document.body, SERVICE_MARKDOWN)
        self.assertEqual(document.business_id, "manual")
        self.assertEqual(document.version, "v1")
        self.assertEqual(document.sources[0].locator, {"location": "manual.pdf", "format": "pdf"})
        self.assertTrue(document.requires_review)


if __name__ == "__main__":
    unittest.main()
