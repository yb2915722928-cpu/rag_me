from importlib import import_module
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from tests.test_audio_video import TRANSCRIPT, media_server


INGESTION_PACKAGE = "app.modules.1_documentIngestionAndParsing"
ingestion = import_module(INGESTION_PACKAGE)
handoff = import_module(INGESTION_PACKAGE + ".unifiedDocumentHandoff")


class IngestionRoutingTests(unittest.TestCase):
    def test_all_27_format_keys_keep_native_reports_and_format_metadata(self):
        # The supported keys are the public spec, independent of the route table.
        # Invalid inputs keep alias coverage cheap; rich successful samples live in
        # test_document_ingestion and the native format suites.
        cases = (
            ("2_textAndWebContent", ("txt", "md", "markdown", "html", "htm", "mhtml", "mht"), {}),
            ("pdfAndDocxExtraction", ("pdf", "docx"), {}),
            ("4_tabularFileProcessing", ("csv", "xlsx"), {}),
            ("5_presentationsAndStructuredDocuments", ("pptx", "json", "xml"), {}),
            ("6_imageProcessing", ("png", "jpg", "jpeg", "webp"), {"task": "ocr"}),
            ("audioTranscriptionAndVideoUnderstanding", ("wav", "mp3", "m4a", "ogg", "flac", "mp4", "mov", "mkv"),
             {"task": "transcribe"}),
            ("8_zipContainers", ("zip",), {}),
        )
        identity = {"business_id": "业务", "version": "v2"}
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            for module, formats, options in cases:
                parser = import_module(INGESTION_PACKAGE + "." + module)
                for format in formats:
                    path = Path(directory) / ("missing." + format)
                    byte_options = options if format == "zip" else options | {"format": format}
                    with self.subTest(format=format):
                        reports = (
                            (ingestion.convert_file(path, format=" ." + format.upper() + " ",
                                                    source="原始来源", **identity, **options),
                             parser.convert_file(path, source="原始来源", **options)),
                            (ingestion.convert_bytes(b"", format=" ." + format.upper() + " ",
                                                     source="原始来源", **identity, **options),
                             parser.convert_bytes(b"", source="原始来源", **byte_options)),
                        )
                        for report, native in reports:
                            self.assertEqual(report.to_dict(), handoff.adapt_result(native, **identity).to_dict())
                            self.assertEqual(report.status, "failed")
                            if format != "zip":
                                self.assertEqual(report.documents[0].sources[0].locator["format"],
                                                 "jpeg" if format == "jpg" else format)

    def test_zip_member_keys_keep_context_categories_and_failure_isolation(self):
        cases = (
            ("text", ("txt", "md", "markdown")),
            ("structured", ("json", "xml")),
            ("csv", ("csv",)),
            ("document", ("pdf", "docx", "pptx", "xlsx", "html", "htm", "mhtml", "mht")),
            ("image", ("png", "jpg", "jpeg", "webp")),
            ("media", ("wav", "mp3", "m4a", "ogg", "flac", "mp4", "mov", "mkv")),
        )
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for _, formats in cases:
                for format in formats:
                    archive.writestr("empty." + format.upper(), b"")
            archive.writestr("nested.zip", b"")
            archive.writestr("unsupported.exe", b"")
            archive.writestr("no-suffix", b"")
            archive.writestr("surviving.txt", "保留兄弟成员".encode("utf-8"))
        options = {"parser_options": {
            "document": {"mineru": {"token": 123}},
            "image": {"task": "ocr"},
        }}
        native = import_module(INGESTION_PACKAGE + ".8_zipContainers").convert_bytes(
            buffer.getvalue(), source="资料包", **options,
        )
        report = ingestion.convert_bytes(buffer.getvalue(), format="zip", source="资料包", **options)
        self.assertEqual(report.to_dict(), handoff.adapt_result(native).to_dict())
        self.assertEqual(report.status, "partial_success")
        members = {member.source.member_path: member for member in native.members}
        for kind, formats in cases:
            for format in formats:
                with self.subTest(format=format):
                    member = members["empty." + format.upper()]
                    self.assertEqual(member.format, format)
                    self.assertEqual(member.result_kind, kind)
                    self.assertEqual(member.reason, "parse_error")
        self.assertEqual(members["nested.zip"].reason, "nested_zip")
        for path, error in (("unsupported.exe", "Unsupported format: exe"),
                            ("no-suffix", "Unsupported format: (no suffix)")):
            with self.subTest(path=path):
                self.assertEqual(members[path].reason, "unsupported_format")
                self.assertEqual(members[path].error, error)
        self.assertEqual(members["surviving.txt"].status, "success")
        self.assertEqual(report.documents[-1].body, "保留兄弟成员")

    def test_media_file_entry_does_not_read_the_entire_original_input(self):
        path = Path(__file__).parent / "media_rules.wav"
        original_read_bytes = Path.read_bytes

        def read_prepared_clip(candidate):
            if candidate == path:
                raise AssertionError("whole original media read")
            return original_read_bytes(candidate)

        with media_server() as (config, requests):
            with patch.object(Path, "read_bytes", read_prepared_clip):
                report = ingestion.convert_file(path, source="录音", task="transcribe", config=config)
        self.assertEqual(len(requests), 1)
        self.assertEqual(report.status, "content", report.to_dict())
        self.assertIn(TRANSCRIPT, report.documents[0].body)


if __name__ == "__main__":
    unittest.main()
