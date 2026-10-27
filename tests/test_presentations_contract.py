import importlib
from pathlib import Path
import tempfile
import unittest


documents = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
SAMPLES = Path(__file__).parent / "testFile"


class ConversionContractTests(unittest.TestCase):
    def test_file_and_bytes_preserve_source_and_accept_normalized_format(self):
        path = SAMPLES / "json_gb18030.json"
        options = dict(format=" .JSON ", source="uploaded-rules", encoding="GB18030")

        from_file = documents.convert_file(path, **options)
        from_bytes = documents.convert_bytes(path.read_bytes(), **options)

        self.assertTrue(from_file.success, from_file.error)
        self.assertEqual(from_file, from_bytes)
        self.assertEqual(from_file.source.location, "uploaded-rules")
        self.assertEqual(from_file.source.format, "json")
        inferred = documents.convert_file(path)
        self.assertTrue(inferred.success, inferred.error)
        self.assertEqual(inferred.source.location, str(path))
        self.assertEqual(inferred.source.format, "json")

    def test_invalid_options_and_unreadable_files_return_no_partial_content(self):
        results = [
            documents.convert_file(None),
            documents.convert_file(SAMPLES / "missing.json"),
            documents.convert_file(SAMPLES),
            documents.convert_file(SAMPLES / "json_types.json", source=" "),
        ]
        for option, value, error in (
            ("format", None, "format"), ("format", 3, "format"),
            ("format", " ", "format"), ("format", "yaml", "Unsupported format"),
            ("source", None, "source"), ("source", " ", "source"),
            ("source", 3, "source"), ("encoding", " ", "encoding"),
            ("encoding", 3, "encoding"),
        ):
            with self.subTest(option=option, value=value):
                options = dict(format="json", source="upload")
                options[option] = value
                result = documents.convert_bytes(b"", **options)
                self.assertIn(error, result.error)
                results.append(result)
        for data in (None, "not bytes", bytearray(b"{}")):
            result = documents.convert_bytes(data, format="json", source="upload")
            self.assertIn("data must be bytes", result.error)
            results.append(result)
        results.append(documents.convert_bytes(b"", format="pptx", source="upload", encoding="utf-8"))

        for result in results:
            with self.subTest(error=result.error):
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertEqual(result.review_issues, [])
                self.assertFalse(result.requires_review)
                self.assertIsNone(result.encoding)
                self.assertEqual(result.warnings, [])
                self.assertTrue(result.error)

    def test_export_writes_only_utf8_body_and_propagates_io_errors(self):
        result = documents.convert_file(SAMPLES / "json_gb18030.json", source="uploaded-rules")
        self.assertTrue(result.success, result.error)
        self.assertTrue(result.warnings)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rules.md"
            self.assertEqual(documents.export_markdown(result, output), output)
            self.assertEqual(output.read_bytes(), result.markdown.encode("utf-8"))
            self.assertFalse(output.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(result.source.location, result.markdown)
            for warning in result.warnings:
                self.assertNotIn(warning, result.markdown)
            with self.assertRaises(OSError):
                documents.export_markdown(result, Path(directory))

    def test_failed_conversion_cannot_create_or_overwrite_export(self):
        failures = [
            documents.convert_file(SAMPLES / "missing.json"),
            documents.convert_file(SAMPLES / "json_nan.json"),
            documents.convert_file(SAMPLES / "json_gb18030.json", encoding="utf-8"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.md"
            existing.write_bytes(b"existing body")
            missing = Path(directory) / "missing.md"
            for result in failures:
                for output in (existing, missing):
                    with self.subTest(error=result.error, output=output):
                        with self.assertRaises(ValueError):
                            documents.export_markdown(result, output)
                self.assertEqual(existing.read_bytes(), b"existing body")
                self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
