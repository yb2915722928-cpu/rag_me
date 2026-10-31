import importlib
from io import BytesIO
from pathlib import Path
import unittest

from pypdf import PdfReader

from tests.test_pdf_word_mineru import mineru_server


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.pdfAndDocxExtraction"
)
SAMPLES = Path(__file__).parent / "testFile"
SCAN_BLOCKS = [
    {"type": "text", "text": "Equipment Maintenance", "text_level": 1, "page_idx": 0},
    {"type": "text", "text": "Disconnect power before maintenance.", "page_idx": 0},
    {"type": "text", "text": "Temperature must not exceed 60 C.", "page_idx": 1},
]


class MixedPdfConversionTests(unittest.TestCase):
    def test_selected_page_missing_from_ocr_cannot_fall_back_to_its_page_number(self):
        path = SAMPLES / "pdf_mixed_numbered_scan.pdf"
        blocks = [{"type": "text", "text": "Temperature must not exceed 60 C.", "page_idx": 1}]
        with mineru_server(blocks, path.name, inspect_upload=lambda data: True) as api:
            results = (
                content.convert_file(path, mineru=api, ocr_pages=(2,)),
                content.convert_bytes(path.read_bytes(), format="pdf", source=path.name,
                                      mineru=api, ocr_pages=(2,)),
            )
        for result in results:
            self.assertFalse(result.success)
            self.assertIsNone(result.markdown)
            self.assertEqual(result.sources, [])
            self.assertEqual(result.error, "No usable OCR body for PDF page 2")

    def test_selected_numbered_scan_replaces_text_layer_and_keeps_other_digital_pages(self):
        path = SAMPLES / "pdf_mixed_numbered_scan.pdf"
        table = ("<table><tr><th>Equipment</th><th>Interval</th></tr>"
                 "<tr><td>Pump</td><td>Monthly</td></tr>"
                 "<tr><td>Valve</td><td>Quarterly</td></tr></table>")
        blocks = [
            {"type": "text", "text": "Equipment Maintenance", "text_level": 1, "page_idx": 0},
            {"type": "list", "list_items": ["Disconnect power before maintenance.",
                                            "Do not service while power is on.",
                                            "Inspect every 30 days."], "page_idx": 0},
            {"type": "table", "table_body": table, "page_idx": 0},
            {"type": "text", "text": "Restart after inspection.", "page_idx": 0},
            {"type": "text", "text": "Printed page 41", "page_idx": 0},
            {"type": "text", "text": "Temperature must not exceed 60 C.", "page_idx": 1},
        ]
        uploads = []

        def inspect_upload(data):
            uploads.append(PdfReader(BytesIO(data)))
            return True

        with mineru_server(blocks, path.name, inspect_upload=inspect_upload) as api:
            results = (
                content.convert_file(path, source="numbered.pdf", mineru=api, ocr_pages=(2,)),
                content.convert_bytes(path.read_bytes(), format="pdf", source="numbered.pdf",
                                      mineru=api, ocr_pages=(2,)),
            )
        self.assertEqual(results[0], results[1])
        page_bodies = [
            "Digital Intake\nAsset code: PUMP-A17.\nPrinted page 90\n",
            "# Equipment Maintenance\n\nDisconnect power before maintenance.\n"
            "Do not service while power is on.\nInspect every 30 days.\n\n" + table
            + "\n\nRestart after inspection.\n\nPrinted page 41\n",
            "Digital Release\nTorque setting: 12 Nm.\nPrinted page 12\n",
            "Temperature must not exceed 60 C.\n",
        ]
        for result in results:
            self.assertTrue(result.success, result.error)
            self.assertEqual(result.source.location, "numbered.pdf")
            self.assertEqual(result.markdown, "\n".join(page_bodies))
            self.assertEqual(result.markdown.count("Printed page 41"), 1)
            self.assertEqual([s.pdf_page_number for s in result.sources], [1, 2, 3, 4])
            self.assertEqual([s.extraction_method for s in result.sources],
                             ["text_layer", "mineru_api", "text_layer", "mineru_api"])
            self.assertEqual([result.markdown[s.markdown_start:s.markdown_end] for s in result.sources],
                             page_bodies)
        self.assertEqual(len(uploads), 2)
        original = PdfReader(path)
        for uploaded in uploads:
            self.assertEqual(len(uploaded.pages), 2)
            self.assertEqual([p.extract_text().strip() for p in uploaded.pages], ["Printed page 41", ""])
            for page, original_page in zip(uploaded.pages, [original.pages[1], original.pages[3]]):
                self.assertEqual(page.get_contents().get_data(), original_page.get_contents().get_data())

    def test_nonempty_page_number_is_not_a_text_layer_quality_guarantee(self):
        path = SAMPLES / "pdf_mixed_numbered_scan.pdf"
        blocks = [{"type": "text", "text": "Temperature must not exceed 60 C.", "page_idx": 0}]
        with mineru_server(blocks, path.name, inspect_upload=lambda data: True) as api:
            results = (
                content.convert_file(path, mineru=api),
                content.convert_bytes(path.read_bytes(), format="pdf", source=str(path), mineru=api),
            )
        self.assertEqual(results[0], results[1])
        for result in results:
            self.assertTrue(result.success, result.error)
            page = result.sources[1]
            self.assertEqual(page.pdf_page_number, 2)
            self.assertEqual(page.extraction_method, "text_layer")
            self.assertEqual(result.markdown[page.markdown_start:page.markdown_end], "Printed page 41\n")
            self.assertNotIn("Disconnect power", result.markdown)
            self.assertTrue(any("Nonempty text" in w and "quality" in w for w in result.warnings))

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
                images = page["/Resources"]["/XObject"]
                original_images = original_page["/Resources"]["/XObject"]
                self.assertEqual(set(images), set(original_images))
                for name in images:
                    image = images[name].get_object()
                    original_image = original_images[name].get_object()
                    self.assertEqual(image["/Subtype"], "/Image")
                    self.assertEqual(image.get_data(), original_image.get_data())
        for warning in from_file.warnings:
            self.assertNotIn(warning, from_file.markdown)


if __name__ == "__main__":
    unittest.main()
