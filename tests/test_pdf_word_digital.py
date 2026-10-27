import importlib
from pathlib import Path
import unittest


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
)
SAMPLES = Path(__file__).parent / "testFile"


class DigitalPdfConversionTests(unittest.TestCase):
    def test_blank_pdf_has_no_body_or_invented_page_source(self):
        path = SAMPLES / "pdf_digital_blank.pdf"
        results = (
            content.convert_file(path),
            content.convert_bytes(path.read_bytes(), format="pdf", source=str(path)),
        )
        for result in results:
            with self.subTest(result=result):
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn("body", result.error.lower())
                self.assertTrue(any("page 1" in warning for warning in result.warnings))

    def test_damaged_second_page_does_not_return_first_page_as_complete_body(self):
        result = content.convert_file(SAMPLES / "pdf_digital_damaged_page.pdf")

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertEqual(result.sources, [])
        self.assertIn("PDF page 2", result.error)
        self.assertIn("failed", result.error)

    def test_text_layer_limits_are_reported_outside_verified_body(self):
        result = content.convert_file(SAMPLES / "pdf_digital_teaching.pdf")

        self.assertTrue(result.success, result.error)
        self.assertTrue(any("heading" in warning for warning in result.warnings))
        self.assertTrue(any("column" in warning for warning in result.warnings))
        self.assertTrue(any("table" in warning for warning in result.warnings))
        for warning in result.warnings:
            self.assertNotIn(warning, result.markdown)

    def test_scanned_pdf_requires_ocr_instead_of_image_placeholder_success(self):
        path = SAMPLES / "pdf_scanned_teaching.pdf"
        results = (
            content.convert_file(path, mineru=content.MinerUConfig(token="")),
            content.convert_bytes(path.read_bytes(), format="pdf", source=str(path),
                                  mineru=content.MinerUConfig(token="")),
        )
        for result in results:
            with self.subTest(result=result):
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn("OCR", result.error)
                self.assertTrue(any("page 1" in warning for warning in result.warnings))

    def test_corrupt_pdf_fails_through_file_and_bytes_without_success_body(self):
        path = SAMPLES / "pdf_digital_corrupt.pdf"
        results = (
            content.convert_file(path),
            content.convert_bytes(path.read_bytes(), format="pdf", source=str(path)),
        )
        for result in results:
            with self.subTest(result=result):
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn("PDF", result.error)
                self.assertIn("failed", result.error)
                self.assertEqual(result.source.location, str(path))

    def test_file_input_failures_return_diagnostics_instead_of_error_body(self):
        path = SAMPLES / "pdf_digital_teaching.pdf"
        for arguments, diagnostic in (
            ({"path": SAMPLES / "missing.pdf"}, "read"),
            ({"path": SAMPLES, "format": "pdf"}, "read"),
            ({"path": None}, "path"),
            ({"path": 12}, "path"),
            ({"path": path, "format": "doc"}, "format"),
            ({"path": path, "format": 12}, "format"),
            ({"path": path, "source": " "}, "source"),
        ):
            with self.subTest(arguments=arguments):
                result = content.convert_file(**arguments)

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn(diagnostic, result.error.lower())

    def test_invalid_bytes_options_fail_without_body_or_content_sources(self):
        valid = dict(
            data=(SAMPLES / "pdf_digital_teaching.pdf").read_bytes(),
            format="pdf", source="upload.pdf",
        )
        for name, value in (
            ("data", "decoded text"),
            ("format", None),
            ("format", " "),
            ("format", "doc"),
            ("source", " "),
            ("source", 12),
        ):
            with self.subTest(argument=name, value=value):
                result = content.convert_bytes(**(valid | {name: value}))

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn(name, result.error.lower())

    def test_page_order_and_body_ranges_do_not_use_printed_page_numbers(self):
        result = content.convert_file(SAMPLES / "pdf_digital_page_order.pdf")

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "Maintenance Start\nDisconnect power before maintenance.\nPrinted page 41\n\n"
            "Maintenance Finish\nInspect every month.\nPrinted page 7\n",
        )
        self.assertEqual([page.pdf_page_number for page in result.sources], [1, 2])
        self.assertEqual(
            [result.markdown[page.markdown_start:page.markdown_end]
             for page in result.sources],
            ["Maintenance Start\nDisconnect power before maintenance.\nPrinted page 41\n",
             "Maintenance Finish\nInspect every month.\nPrinted page 7\n"],
        )

    def test_file_and_existing_bytes_share_explicit_format_and_source_behavior(self):
        path = SAMPLES / "pdf_digital_teaching.pdf"

        from_bytes = content.convert_bytes(
            path.read_bytes(), format=" .PDF ", source="upload:maintenance"
        )
        from_file = content.convert_file(
            path, format="pdf", source="upload:maintenance"
        )

        self.assertTrue(from_bytes.success, from_bytes.error)
        self.assertEqual(from_file, from_bytes)
        self.assertEqual(from_bytes.source.location, "upload:maintenance")
        self.assertEqual(from_bytes.source.format, "pdf")
        self.assertNotIn("upload:maintenance", from_bytes.markdown)

    def test_teaching_pdf_preserves_title_rules_and_actual_page_source(self):
        path = SAMPLES / "pdf_digital_teaching.pdf"

        result = content.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "Equipment Maintenance\n"
            "Disconnect power before maintenance.\n"
            "Inspect every month.\n",
        )
        self.assertEqual(result.source.location, str(path))
        self.assertEqual(result.source.format, "pdf")
        self.assertEqual(len(result.sources), 1)
        page = result.sources[0]
        self.assertEqual(page.pdf_page_number, 1)
        self.assertEqual(page.extraction_method, "text_layer")
        self.assertEqual(
            result.markdown[page.markdown_start:page.markdown_end], result.markdown
        )
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
