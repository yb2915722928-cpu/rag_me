import importlib
from pathlib import Path
import tempfile
import unittest


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)
SAMPLES = Path(__file__).parent / "testFile"


class TxtConversionTests(unittest.TestCase):
    def test_explicit_utf8_bom_only_input_fails_without_creating_or_overwriting_export(self):
        successful = content.convert_file(SAMPLES / "txt_utf8_layout.txt")

        with tempfile.TemporaryDirectory() as directory:
            existing = content.export_markdown(successful, Path(directory) / "existing.md")
            original = existing.read_bytes()
            missing = Path(directory) / "missing.md"

            for filename in ("txt_bom_only.txt", "md_bom_only.md"):
                path = SAMPLES / filename
                results = (
                    content.convert_file(path, encoding="utf-8"),
                    content.convert_bytes(
                        path.read_bytes(), format=path.suffix, source=str(path),
                        encoding="utf-8",
                    ),
                )
                for entry, result in zip(("file", "bytes"), results):
                    with self.subTest(filename=filename, entry=entry):
                        self.assertFalse(result.success)
                        self.assertIsNone(result.markdown)
                        self.assertEqual(result.error, "No usable text body")
                        self.assertEqual(result.encoding, "utf-8")
                        self.assertEqual(result.warnings, [])
                        for output in (missing, existing):
                            with self.assertRaises(ValueError):
                                content.export_markdown(result, output)
                        self.assertFalse(missing.exists())
                        self.assertEqual(existing.read_bytes(), original)

    def test_unusable_or_truncated_encoding_fails_without_replacement_text(self):
        for filename in ("txt_undecodable.txt", "txt_truncated_utf16.txt"):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename)

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertIn("decoding", result.error.lower())
                self.assertEqual(result.warnings, [])

    def test_explicit_encoding_takes_precedence_over_bom(self):
        result = content.convert_file(SAMPLES / "txt_utf16_le_bom.txt", encoding="utf-8")

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertIn("utf-8", result.error)

    def test_file_accepts_explicit_format_source_and_full_mode(self):
        result = content.convert_file(
            SAMPLES / "txt_utf8_layout.txt",
            format=".TXT",
            source="upload.txt",
            mode="full",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.source, content.Source("upload.txt", "txt"))
        self.assertIn("北京是中国的首都。", result.markdown)
        self.assertIn("长江流经武汉。", result.markdown)

    def test_failed_result_never_creates_or_overwrites_export(self):
        failed = content.convert_file(SAMPLES / "txt_gb18030.txt", encoding="utf-8")
        successful = content.convert_file(SAMPLES / "txt_utf8_layout.txt")

        with tempfile.TemporaryDirectory() as directory:
            existing = content.export_markdown(successful, Path(directory) / "existing.md")
            original = existing.read_bytes()
            missing = Path(directory) / "missing.md"

            for path in (existing, missing):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    content.export_markdown(failed, path)

            self.assertFalse(missing.exists())
            self.assertEqual(existing.read_bytes(), original)

    def test_export_writes_only_body_as_utf8_without_windows_newline_changes(self):
        result = content.convert_file(SAMPLES / "txt_gb18030.txt", source="archive.txt")
        self.assertTrue(result.warnings)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "converted.md"
            written_path = content.export_markdown(result, path)
            exported = path.read_bytes()

        self.assertEqual(written_path, path)
        self.assertEqual(exported, result.markdown.encode("utf-8"))
        self.assertIn("长江流经武汉，黄河流经兰州。", exported.decode("utf-8"))
        self.assertNotIn(b"\r", exported)
        self.assertFalse(exported.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"archive.txt", exported)
        for warning in result.warnings:
            self.assertNotIn(warning, exported.decode("utf-8"))

    def test_invalid_file_path_or_options_return_clear_failure(self):
        path = SAMPLES / "txt_utf8_layout.txt"
        for arguments, diagnostic in (
            ({"path": None}, "path"),
            ({"path": 12}, "path"),
            ({"path": path, "format": ""}, "format"),
            ({"path": path, "format": 12}, "format"),
            ({"path": path, "source": 12}, "source"),
            ({"path": path, "mode": "unknown"}, "mode"),
        ):
            with self.subTest(arguments=arguments):
                result = content.convert_file(**arguments)

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertIn(diagnostic, result.error.lower())

    def test_invalid_byte_entry_arguments_return_clear_failure(self):
        data = (SAMPLES / "txt_utf8_layout.txt").read_bytes()
        valid = dict(data=data, format="txt", source="upload.txt")
        cases = (
            ("data", "already decoded text"),
            ("format", None),
            ("format", 3),
            ("format", ""),
            ("format", "pdf"),
            ("source", None),
            ("source", 3),
            ("source", "  "),
            ("source", content.Source("")),
            ("encoding", 3),
            ("encoding", ""),
            ("encoding", "no-such-text-codec"),
            ("mode", "unknown"),
        )
        for name, value in cases:
            with self.subTest(argument=name, value=value):
                result = content.convert_bytes(**(valid | {name: value}))

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertTrue(result.error)
                self.assertIn(name, result.error.lower())

    def test_empty_or_whitespace_only_input_has_no_usable_body(self):
        for filename in ("txt_empty.txt", "txt_whitespace.txt", "txt_bom_only.txt"):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename)

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertIn("body", result.error.lower())
                self.assertIsNotNone(result.encoding)

    def test_unreadable_file_returns_diagnostic_separate_from_body(self):
        for path in (SAMPLES / "txt_missing.txt", SAMPLES):
            with self.subTest(path=path):
                result = content.convert_file(path, format="txt")

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertIn("read", result.error.lower())
                self.assertIn(str(path), result.error)
                self.assertEqual(result.source.location, str(path))
                self.assertIsNone(result.encoding)

    def test_detected_legacy_encoding_keeps_facts_and_reports_warning(self):
        result = content.convert_file(SAMPLES / "txt_gb18030.txt")

        self.assertTrue(result.success, result.error)
        self.assertIsNotNone(result.encoding)
        self.assertIn("长江流经武汉，黄河流经兰州。", result.markdown)
        self.assertIn("北京是中国的首都，故宫位于北京市中心。", result.markdown)
        self.assertNotIn("\ufffd", result.markdown)
        self.assertTrue(result.warnings)
        self.assertIn(result.encoding, " ".join(result.warnings))
        self.assertIsNone(result.error)

    def test_bom_selects_unicode_encoding_and_removes_signature(self):
        for filename, encoding in (
            ("txt_utf8_bom.txt", "utf-8-sig"),
            ("txt_utf16_le_bom.txt", "utf-16"),
            ("txt_utf16_be_bom.txt", "utf-16"),
            ("txt_utf32_le_bom.txt", "utf-32"),
            ("txt_utf32_be_bom.txt", "utf-32"),
        ):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename)

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.encoding, encoding)
                self.assertEqual(
                    result.markdown, "北京是中国的首都。\n\n长江流经武汉。\n"
                )
                self.assertEqual(result.warnings, [])

    def test_wrong_explicit_encoding_fails_without_fallback_or_body(self):
        result = content.convert_file(SAMPLES / "txt_gb18030.txt", encoding="utf-8")

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertIn("utf-8", result.error)
        self.assertIn("decode", result.error.lower())
        self.assertEqual(result.warnings, [])

    def test_explicit_encoding_preserves_chinese_facts(self):
        result = content.convert_file(SAMPLES / "txt_gb18030.txt", encoding="GB18030")

        self.assertTrue(result.success)
        self.assertEqual(result.encoding, "gb18030")
        self.assertEqual(result.warnings, [])
        self.assertIn("长江流经武汉，黄河流经兰州。", result.markdown)
        self.assertIn("北京是中国的首都，故宫位于北京市中心。", result.markdown)
        self.assertNotIn("\ufffd", result.markdown)

    def test_bytes_preserve_paragraphs_indentation_and_explicit_source(self):
        data = (SAMPLES / "txt_utf8_layout.txt").read_bytes()
        source = content.Source("upload.txt")

        result = content.convert_bytes(data, format="TXT", source=source)

        self.assertTrue(result.success)
        self.assertEqual(result.source, content.Source("upload.txt", "txt"))
        self.assertEqual(
            result.markdown,
            "第一段：北京是中国的首都。\n\n    保留四个空格\t和制表符。\n"
            "第二段：长江流经武汉。\n\n",
        )

    def test_file_returns_complete_known_book_and_source(self):
        path = SAMPLES / "alice_utf8.txt"

        result = content.convert_file(path)

        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(result.encoding, "utf-8")
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.source.location, str(path))
        self.assertEqual(result.source.format, "txt")
        self.assertIn("Alice’s Adventures in Wonderland", result.markdown)
        self.assertIn("CHAPTER XII.   Alice’s Evidence", result.markdown)
        self.assertIn(
            "Down the Rabbit-Hole\n\n\nAlice was beginning to get very tired",
            result.markdown,
        )
        self.assertIn("*** END OF THE PROJECT GUTENBERG EBOOK", result.markdown)


if __name__ == "__main__":
    unittest.main()
