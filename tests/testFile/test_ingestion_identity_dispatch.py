from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ingestion = import_module("app.modules.1_documentIngestionAndParsing")
handoff = import_module(ingestion.__name__ + ".unifiedDocumentHandoff")
text_web = import_module(ingestion.__name__ + ".2_textAndWebContent")
SAMPLES = Path(__file__).parent


class IngestionIdentityDispatchTests(unittest.TestCase):
    def test_invalid_identity_precedes_reading_unknown_options_and_native_validation(self):
        for name in ("business_id", "version"):
            for value, error in ((False, TypeError), ([], TypeError), ("", ValueError), (" \t", ValueError)):
                for entry in ("file", "bytes", "native"):
                    with self.subTest(name=name, value=value, entry=entry):
                        identity = {name: value}
                        with patch("pathlib.Path.open", side_effect=AssertionError("input read")), \
                                self.assertRaisesRegex(error, name + " must be a nonempty string or None"):
                            if entry == "file":
                                ingestion.convert_file(SAMPLES / "missing.txt", unrecognized_option=True, **identity)
                            elif entry == "bytes":
                                ingestion.convert_bytes(None, format="txt", source="", unrecognized_option=True, **identity)
                            else:
                                handoff.adapt_result(object(), **identity)

    def test_path_and_format_errors_keep_priority_over_identity(self):
        with self.assertRaises(TypeError):
            ingestion.convert_file(None, format="unsupported", business_id="")
        for entry in ("file", "bytes"):
            with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, "Unsupported format: unsupported"):
                if entry == "file":
                    ingestion.convert_file("missing.unsupported", business_id="")
                else:
                    ingestion.convert_bytes(b"", format="unsupported", source="", business_id="")
        with self.assertRaisesRegex(TypeError, "business_id must"):
            ingestion.convert_bytes(b"", format="txt", source="", business_id=0, version="")

    def test_valid_identity_does_not_hide_unknown_options_or_read_and_parse_failures(self):
        identity = {"business_id": " 业务 ", "version": " v2 "}
        for entry in ("file", "bytes"):
            with self.subTest(entry=entry), self.assertRaisesRegex(TypeError, "unrecognized_option"):
                if entry == "file":
                    ingestion.convert_file(SAMPLES / "missing.txt", unrecognized_option=True, **identity)
                else:
                    ingestion.convert_bytes(b"body", format="txt", source="来源", unrecognized_option=True, **identity)
        for report, diagnostic in (
            (ingestion.convert_file(SAMPLES / "missing.txt", **identity), "Could not read"),
            (ingestion.convert_bytes(b"{", format="json", source="来源", **identity), "Invalid JSON"),
        ):
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(report.status, "failed")
                document = report.documents[0]
                self.assertEqual((document.business_id, document.version), (" 业务 ", " v2 "))
                self.assertIn(diagnostic, document.diagnostics[-1].message)
                self.assertIsNone(document.body)

    def test_public_handoff_accepts_native_subclasses_and_rejects_similar_objects(self):
        native = text_web.convert_bytes("原正文\n".encode("utf-8"), format="txt", source="来源")

        class CustomTextResult(text_web.ConversionResult):
            pass

        subclass = CustomTextResult(**vars(native))
        expected = handoff.adapt_result(native).to_dict()
        self.assertEqual(handoff.adapt_result(subclass).to_dict(), expected)
        with self.assertRaisesRegex(TypeError, "Unsupported result type: SimpleNamespace"):
            handoff.adapt_result(SimpleNamespace(**vars(native), success=True))

    def test_zip_file_entry_keeps_streaming_instead_of_reading_the_entire_archive(self):
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("whole archive read")):
            report = ingestion.convert_file(SAMPLES / "zip_text.zip", business_id="容器")
        self.assertEqual(report.status, "success")
        self.assertEqual(len(report.documents), 2)
        self.assertTrue(all(document.business_id is None for document in report.documents))


if __name__ == "__main__":
    unittest.main()
