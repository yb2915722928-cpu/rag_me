import importlib
from io import BytesIO
from pathlib import Path
import unittest

from pypdf import PdfReader

from tests.test_pdf_word_mineru import mineru_server


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
)
SAMPLES = Path(__file__).parent / "testFile"
SCAN_BLOCKS = [
    {"type": "text", "text": "Equipment Maintenance", "text_level": 1, "page_idx": 0},
    {"type": "text", "text": "Disconnect power before maintenance.", "page_idx": 0},
    {"type": "text", "text": "Temperature must not exceed 60 C.", "page_idx": 1},
]


class MixedPdfConversionTests(unittest.TestCase):
    def test_table_loss_warning_uses_original_page_without_claiming_relationship_recovery(self):
        path = SAMPLES / "pdf_mixed_maintenance.pdf"
        blocks = SCAN_BLOCKS + [{"type": "table", "table_body": "Pump Monthly Valve Quarterly", "page_idx": 1}]
        with mineru_server(blocks, path.name, inspect_upload=lambda data: True) as api:
            result = content.convert_file(path, mineru=api)

        self.assertTrue(result.success, result.error)
        losses = [w for w in result.warnings if "were not recovered" in w]
        self.assertEqual(losses, ["PDF page 4: table relationships were not recovered"])
        self.assertIn("Pump Monthly Valve Quarterly", result.markdown)
        self.assertNotIn("were not recovered", result.markdown)

    def test_remote_failure_names_original_scan_pages_and_keeps_diagnostics_out_of_body(self):
        path = SAMPLES / "pdf_mixed_maintenance.pdf"
        with mineru_server(input_name=path.name, failure="failed", inspect_upload=lambda data: True) as api:
            results = (
                content.convert_file(path, mineru=api),
                content.convert_bytes(path.read_bytes(), format="pdf", source=path.name, mineru=api),
            )
        for result in results:
            self.assertFalse(result.success)
            self.assertIsNone(result.markdown)
            self.assertEqual(result.sources, [])
            self.assertIn("PDF pages 2, 4", result.error)
            self.assertIn("engine unavailable", result.error)

    def test_ocr_unavailable_names_only_original_scan_pages_without_partial_body(self):
        path = SAMPLES / "pdf_mixed_maintenance.pdf"
        api = content.MinerUConfig(token="")
        results = (
            content.convert_file(path, mineru=api),
            content.convert_bytes(path.read_bytes(), format="pdf", source=path.name, mineru=api),
        )
        for result in results:
            self.assertFalse(result.success)
            self.assertIsNone(result.markdown)
            self.assertEqual(result.sources, [])
            self.assertIn("PDF pages 2, 4", result.error)
            self.assertIn("MINERU_API_TOKEN", result.error)
            unavailable = [w for w in result.warnings if "OCR unavailable" in w]
            self.assertEqual(unavailable, ["PDF page 2: OCR unavailable", "PDF page 4: OCR unavailable"])

    def test_missing_scan_body_fails_whole_document_and_names_the_original_page(self):
        path = SAMPLES / "pdf_mixed_maintenance.pdf"
        for blocks, missing_page in ((SCAN_BLOCKS[:2], 4), (SCAN_BLOCKS[2:], 2)):
            with self.subTest(missing_page=missing_page):
                with mineru_server(blocks, path.name, inspect_upload=lambda data: True) as api:
                    results = (
                        content.convert_file(path, mineru=api),
                        content.convert_bytes(path.read_bytes(), format="pdf", source=path.name, mineru=api),
                    )
                for result in results:
                    self.assertFalse(result.success)
                    self.assertIsNone(result.markdown)
                    self.assertEqual(result.sources, [])
                    self.assertEqual(result.error, f"No usable OCR body for PDF page {missing_page}")

    def test_file_and_bytes_upload_only_noncontiguous_scans_and_merge_original_page_order(self):
        path = SAMPLES / "pdf_mixed_maintenance.pdf"
        uploads = []

        def inspect_upload(data):
            uploads.append(PdfReader(BytesIO(data)))
            return True

        with mineru_server(SCAN_BLOCKS, path.name, inspect_upload=inspect_upload) as api:
            from_file = content.convert_file(path, source="mixed.pdf", mineru=api)
            from_bytes = content.convert_bytes(
                path.read_bytes(), format="pdf", source="mixed.pdf", mineru=api,
            )

        self.assertTrue(from_file.success, from_file.error)
        self.assertEqual(from_file, from_bytes)
        self.assertEqual(from_file.source.location, "mixed.pdf")
        self.assertEqual(from_file.source.format, "pdf")
        page_bodies = [
            "Digital Intake\nAsset code: PUMP-A17.\nPrinted page 90\n",
            "# Equipment Maintenance\n\nDisconnect power before maintenance.\n",
            "Digital Release\nTorque setting: 12 Nm.\nPrinted page 12\n",
            "Temperature must not exceed 60 C.\n",
        ]
        self.assertEqual(from_file.markdown, "\n".join(page_bodies))
        self.assertEqual([s.pdf_page_number for s in from_file.sources], [1, 2, 3, 4])
        self.assertEqual([s.extraction_method for s in from_file.sources],
                         ["text_layer", "mineru_api", "text_layer", "mineru_api"])
        self.assertEqual(
            [from_file.markdown[s.markdown_start:s.markdown_end] for s in from_file.sources],
            page_bodies,
        )
        self.assertEqual(len(uploads), 2)
        original = PdfReader(path)
        for uploaded in uploads:
            self.assertEqual(len(uploaded.pages), 2)
            for page, original_page in zip(uploaded.pages, [original.pages[1], original.pages[3]]):
                self.assertEqual(page.extract_text(), "")
                self.assertEqual(page.mediabox, original_page.mediabox)
                self.assertEqual(page.get_contents().get_data(), original_page.get_contents().get_data())
                self.assertEqual([image.data for image in page.images],
                                 [image.data for image in original_page.images])
        for warning in from_file.warnings:
            self.assertNotIn(warning, from_file.markdown)


if __name__ == "__main__":
    unittest.main()
