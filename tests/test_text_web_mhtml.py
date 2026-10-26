import importlib
from pathlib import Path
import tempfile
import unittest


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)
SAMPLES = Path(__file__).parent / "testFile"


class MhtmlConversionTests(unittest.TestCase):
    def test_chromium_multi_frame_bytes_select_top_frame_without_merging_frames(self):
        result = content.convert_bytes(
            (SAMPLES / "chromium_multi_frames_contentid.mht").read_bytes(),
            format="mhtml", source="uploaded-multiple-frames", mode="full",
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source.location, "uploaded-multiple-frames")
        self.assertEqual(result.source.format, "mhtml")
        self.assertEqual(result.source.content_location, "http://localhost/top_frame.html")
        self.assertIsNone(result.source.content_id)
        self.assertEqual(result.source.mime_index, 1)
        self.assertEqual(result.encoding, "iso8859-1")
        self.assertEqual(result.source.encoding, "iso8859-1")
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("Verify the selected page", result.warnings[0])
        self.assertIn("This page contains several frames.", result.markdown)
        self.assertIn("And a red square:", result.markdown)
        for frame_text in ("The first frame!", "The second frame!", "The third frame!", "This is frame 4!"):
            self.assertNotIn(frame_text, result.markdown)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "selected-page.md"
            content.export_markdown(result, output)
            self.assertEqual(output.read_bytes(), result.markdown.encode("utf-8"))

    def test_explicit_root_ignores_unselected_decode_error_but_fallback_requires_all_counts(self):
        selected = content.convert_file(SAMPLES / "mhtml_start_ignores_unselected_decode_error.mhtml")
        fallback = content.convert_file(SAMPLES / "mhtml_fallback_decode_error.mhtml")

        self.assertTrue(selected.success, selected.error)
        self.assertEqual(selected.markdown, "Only the selected HTML needs decoding.\n")
        self.assertEqual(selected.source.content_id, "<valid>")
        self.assertEqual(selected.source.mime_index, 2)
        self.assertEqual(selected.warnings, [])
        self.assert_failed_and_not_exportable(fallback, "decoding failed")

    def test_unusable_explicit_root_and_incomplete_mime_fail_clearly(self):
        for name, error_fragment in (("unmatched_start", "start"), ("truncated_mime", "CloseBoundaryNotFoundDefect")):
            with self.subTest(name=name):
                result = content.convert_file(SAMPLES / f"mhtml_{name}.mhtml")

                self.assert_failed_and_not_exportable(result, error_fragment)

    def test_largest_html_without_body_does_not_switch_to_a_readable_smaller_frame(self):
        result = content.convert_file(SAMPLES / "mhtml_empty_largest.mhtml")

        self.assert_failed_and_not_exportable(result, "No usable HTML body")
        self.assertEqual(result.source.content_id, "<empty-largest>")
        self.assertEqual(result.source.mime_index, 2)
        self.assertEqual(len(result.warnings), 1)

    def test_mime_and_html_declarations_strictly_decode_chinese_and_warn_independently(self):
        for name, warning_count in (
            ("declared_gb18030", 0), ("meta_gb18030", 0), ("invalid_declaration", 1),
        ):
            with self.subTest(name=name):
                result = content.convert_file(SAMPLES / f"mhtml_{name}.mhtml")

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.markdown, "长江流经武汉，黄河流经兰州。\n")
                self.assertEqual(result.encoding, "gb18030")
                self.assertEqual(result.source.encoding, "gb18030")
                self.assertEqual(len(result.warnings), warning_count)
                for warning in result.warnings:
                    self.assertNotIn(warning, result.markdown)

    def test_explicit_encoding_bom_and_mime_html_declaration_priority(self):
        for name, requested, used, expected in (
            ("utf8_bom_conflict", None, "utf-8-sig", "长江流经武汉，黄河流经兰州。\n"),
            ("utf16_bom_conflict", None, "utf-16", "长江流经武汉，黄河流经兰州。\n"),
            ("utf8_bom_conflict", "utf-8", "utf-8", "长江流经武汉，黄河流经兰州。\n"),
            ("declared_gb18030", "GB18030", "gb18030", "长江流经武汉，黄河流经兰州。\n"),
            ("declaration_before_utf8", None, "iso8859-1", "cafÃ©\n"),
            ("declaration_before_utf8", "utf-8", "utf-8", "café\n"),
            ("utf8_no_declaration", None, "utf-8", "长江流经武汉，黄河流经兰州。\n"),
        ):
            with self.subTest(name=name, requested=requested):
                result = content.convert_file(SAMPLES / f"mhtml_{name}.mhtml", encoding=requested)

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.markdown, expected)
                self.assertEqual(result.encoding, used)
                self.assertEqual(result.source.encoding, used)
                self.assertEqual(result.warnings, [])

    def test_detected_legacy_encoding_exports_complete_chinese_without_diagnostics(self):
        result = content.convert_file(SAMPLES / "mhtml_detected_gb18030.mhtml")

        self.assertTrue(result.success, result.error)
        self.assertIn("长江流经武汉，黄河流经兰州。", result.markdown)
        self.assertIn("北京是中国的首都，故宫位于北京市中心。", result.markdown)
        self.assertEqual(result.source.encoding, result.encoding)
        self.assertTrue(result.warnings)
        self.assertIn(result.encoding, " ".join(result.warnings))
        self.assertNotIn("\ufffd", result.markdown)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "chinese.md"
            content.export_markdown(result, output)
            self.assertEqual(output.read_bytes(), result.markdown.encode("utf-8"))
            for warning in result.warnings:
                self.assertNotIn(warning, output.read_text(encoding="utf-8"))

    def test_charset_decode_failures_do_not_fall_back_or_export(self):
        for name, encoding in (
            ("declared_gb18030", "utf-8"),
            ("declared_gb18030", "no-such-text-codec"),
            ("utf16_bom_conflict", "utf-8"),
            ("undecodable", None),
            ("truncated_utf16", None),
        ):
            with self.subTest(name=name, encoding=encoding):
                result = content.convert_file(SAMPLES / f"mhtml_{name}.mhtml", encoding=encoding)

                self.assert_failed_and_not_exportable(result, "decoding failed")

    def test_no_html_or_attachment_only_archive_has_no_exportable_body(self):
        for filename in ("mhtml_no_html.mhtml", "mhtml_html_attachment.mhtml"):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename)

                self.assert_failed_and_not_exportable(result, "No HTML")

    def test_selected_script_shell_fails_without_switching_to_readable_frame(self):
        result = content.convert_file(SAMPLES / "mhtml_empty_root.mhtml")

        self.assert_failed_and_not_exportable(result, "No usable HTML body")
        self.assertEqual(result.source.content_id, "<empty-root>")
        self.assertEqual(result.source.mime_index, 2)
        self.assertEqual(result.encoding, "utf-8")
        self.assertEqual(result.warnings, [])

    def test_damaged_or_unknown_transfer_encoding_fails_without_export(self):
        for name in (
            "qp_truncated", "qp_bad_escape", "base64_truncated",
            "base64_invalid", "unknown_transfer",
        ):
            with self.subTest(name=name):
                result = content.convert_file(SAMPLES / f"mhtml_{name}.mhtml")

                self.assert_failed_and_not_exportable(result, "MHTML")

    def test_explicit_start_selects_shorter_html_for_bytes_and_article_full_modes(self):
        data = (SAMPLES / "mhtml_start_shorter.mhtml").read_bytes()
        source = content.Source("uploaded-archive")

        article = content.convert_bytes(data, format=".MHTML", source=source)
        full = content.convert_bytes(data, format="mht", source="uploaded-archive", mode="full")

        for result in (article, full):
            self.assertTrue(result.success, result.error)
            self.assertEqual(result.source.location, "uploaded-archive")
            self.assertEqual(result.source.content_id, "<main-page>")
            self.assertEqual(result.source.content_location, "https://example.test/main")
            self.assertEqual(result.source.mime_index, 2)
            self.assertEqual(result.encoding, "utf-8")
            self.assertEqual(result.source.encoding, "utf-8")
            self.assertEqual(result.warnings, [])
            self.assertIn("# Main page", result.markdown)
            self.assertIn("Start chooses this shorter page.", result.markdown)
            self.assertNotIn("Unselected large frame", result.markdown)
        self.assertNotIn("Archive navigation", article.markdown)
        self.assertIn("Archive navigation", full.markdown)
        self.assertEqual(source, content.Source("uploaded-archive"))

    def test_selection_uses_original_decoded_character_count_before_html_conversion(self):
        for filename, expected_id, expected_text in (
            ("mhtml_character_count.mhtml", "<characters-winner>", "A" * 50),
            ("mhtml_raw_html_count.mhtml", "<raw-winner>", "Raw markup winner"),
            ("mhtml_character_tie.mhtml", "<first>", "First tied page"),
            ("mhtml_original_crlf_count.mhtml", "<original-winner>", "CRLF winner"),
        ):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename, mode="full")

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.source.content_id, expected_id)
                self.assertIn(expected_text, result.markdown)
                self.assertEqual(len(result.warnings), 1)

    def test_chromium_single_page_file_decodes_mime_and_exports_only_body(self):
        path = SAMPLES / "chromium_simple_page_unmht.mht"

        result = content.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source.location, str(path))
        self.assertEqual(result.source.format, "mht")
        self.assertIsNone(result.source.content_id)
        self.assertEqual(result.source.content_location, "http://localhost/simple_page.html")
        self.assertEqual(result.source.mime_index, 1)
        self.assertEqual(result.encoding, "iso8859-1")
        self.assertEqual(result.source.encoding, result.encoding)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("decoded HTML character count", result.warnings[0])
        self.assertIn("# This is a very simple page", result.markdown)
        self.assertIn("Very **basic** page.", result.markdown)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "page.md"
            self.assertEqual(content.export_markdown(result, output), output)
            self.assertEqual(output.read_bytes(), result.markdown.encode("utf-8"))
            self.assertNotIn(result.warnings[0], output.read_text(encoding="utf-8"))
            self.assertNotIn(result.source.content_location, result.markdown)

    def assert_failed_and_not_exportable(self, result, error_fragment):
        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertIn(error_fragment, result.error)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed.md"
            with self.assertRaises(ValueError):
                content.export_markdown(result, output)
            self.assertFalse(output.exists())
            output.write_bytes(b"existing document")
            with self.assertRaises(ValueError):
                content.export_markdown(result, output)
            self.assertEqual(output.read_bytes(), b"existing document")


if __name__ == "__main__":
    unittest.main()
