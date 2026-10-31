from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ingestion = import_module("app.modules.1_documentIngestionAndParsing")
handoff = import_module(ingestion.__name__ + ".9_unifiedOutputAndChunkingHandoff")
text_web = import_module(ingestion.__name__ + ".2_textAndWebContent")
structured = import_module(ingestion.__name__ + ".5_presentationsAndStructuredDocuments")


class IngestionExportTests(unittest.TestCase):
    def test_existing_markdown_entries_share_the_same_export(self):
        self.assertIs(text_web.export_markdown, structured.export_markdown)
        native = structured.convert_bytes(b'{"city": "Wuhan"}', format="json", source="城市")
        self.assertTrue(native.success, native.error)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "正文.md"
            self.assertEqual(structured.export_markdown(native, output), output)
            self.assertEqual(output.read_bytes(), native.markdown.encode("utf-8"))

    def test_json_public_entries_share_utf8_failure_report_export(self):
        self.assertIs(ingestion.export_json, handoff.export_json)
        report = handoff.HandoffReport("failed", metadata={"原因": "未读取"})
        expected = (
            '{\n  "status": "failed",\n  "documents": [],\n  "diagnostics": [],\n'
            '  "metadata": {\n    "原因": "未读取"\n  }\n}\n'
        ).encode("utf-8")
        with TemporaryDirectory() as directory:
            output = Path(directory) / "报告.json"
            output.write_bytes(b"old report")
            self.assertEqual(ingestion.export_json(report, output), output)
            self.assertEqual(output.read_bytes(), expected)

    def test_serialization_fails_before_overwriting_a_report(self):
        report = handoff.HandoffReport("failed", metadata={"unsupported": object()})
        with TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_bytes(b"keep existing")
            with self.assertRaises(TypeError):
                ingestion.export_json(report, output)
            self.assertEqual(output.read_bytes(), b"keep existing")

    def test_export_write_errors_propagate_through_existing_public_entries(self):
        native = text_web.convert_bytes("正文\n".encode("utf-8"), format="txt", source="输入")
        report = handoff.adapt_result(native)
        with TemporaryDirectory() as directory:
            for target in (Path(directory), Path(directory) / "missing" / "output"):
                for export, value in ((ingestion.export_json, report),
                                      (handoff.export_json, report),
                                      (text_web.export_markdown, native)):
                    with self.subTest(export=export.__name__, target=target), self.assertRaises(OSError):
                        export(value, target)


if __name__ == "__main__":
    unittest.main()
