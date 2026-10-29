import copy
import importlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)
handoff = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff"
)
SAMPLES = Path(__file__).parent / "testFile"


class TextWebHandoffTests(unittest.TestCase):
    def test_all_text_formats_keep_complete_body_and_explicit_business_identity(self):
        cases = (
            ("txt_gb18030.txt", "长江流经武汉，黄河流经兰州。"),
            ("md_list_fence.md", "- ```text\n  first  value\n\n\n  second\n  ```"),
            ("html_table_pipe.html", "| a \\| b | 普通文字中的管道 |"),
            ("mhtml_start_shorter.mhtml", "Start chooses this shorter page."),
            ("json_utf8_bom.json", '"城市": "北京"'),
        )
        for filename, evidence in cases:
            path = SAMPLES / filename
            for entry in ("file", "bytes"):
                with self.subTest(filename=filename, entry=entry):
                    if entry == "file":
                        native = content.convert_file(path)
                    else:
                        native = content.convert_bytes(path.read_bytes(), format=path.suffix, source=str(path))
                    self.assertTrue(native.success, native.error)
                    before = copy.deepcopy(native)

                    report = handoff.adapt_result(native, business_id="业务-公告", version="修订二")
                    with tempfile.TemporaryDirectory() as directory:
                        saved = json.loads(handoff.export_json(report, Path(directory) / "result.json").read_bytes())

                    document = saved["documents"][0]
                    self.assertEqual(document["body"], native.markdown)
                    self.assertIn(evidence, document["body"])
                    self.assertEqual(document["body_format"], "markdown")
                    self.assertEqual(document["business_id"], "业务-公告")
                    self.assertEqual(document["version"], "修订二")
                    self.assertEqual(len(document["units"]), 1)
                    self.assertEqual(document["units"][0]["text"], native.markdown)
                    self.assertEqual(document["sources"][0]["locator"]["format"], path.suffix[1:])
                    self.assertEqual([item["message"] for item in document["diagnostics"]], native.warnings)
                    if filename.startswith("mhtml"):
                        self.assertEqual(document["sources"][0]["locator"]["content_id"], "<main-page>")
                        self.assertEqual(document["sources"][0]["locator"]["mime_index"], 2)
                        self.assertNotIn("Unselected large frame", document["body"])
                    self.assertEqual(native, before)

    def test_export_propagates_io_errors_and_does_not_mutate_report(self):
        native = content.convert_file(SAMPLES / "txt_utf8_layout.txt")
        report = handoff.adapt_result(native)
        before = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as directory:
            for target in (Path(directory), Path(directory) / "missing" / "result.json"):
                with self.subTest(target=target), self.assertRaises(OSError):
                    handoff.export_json(report, target)
        self.assertEqual(report, before)

    def test_business_identity_requires_nonempty_strings_or_none(self):
        native = content.convert_file(SAMPLES / "txt_utf8_layout.txt")
        before = copy.deepcopy(native)
        for name in ("business_id", "version"):
            for invalid, error_type in ((0, TypeError), (False, TypeError), ([], TypeError),
                                        ("", ValueError), (" \t", ValueError)):
                with self.subTest(name=name, invalid=invalid):
                    with self.assertRaisesRegex(error_type, name):
                        handoff.adapt_result(native, **{name: invalid})
        self.assertEqual(native, before)
        with self.assertRaises(TypeError):
            handoff.adapt_result(native, business_version="v1")

    def test_unknown_result_type_is_rejected_even_with_matching_field_names(self):
        native = content.convert_file(SAMPLES / "txt_utf8_layout.txt")
        unsupported = SimpleNamespace(**vars(native), success=True)
        for value in (None, {}, "already parsed", unsupported, object()):
            with self.subTest(value=type(value).__name__):
                with self.assertRaisesRegex(TypeError, "Unsupported result type"):
                    handoff.adapt_result(value)

    def test_failed_conversion_exports_diagnostics_without_body_or_units(self):
        for filename in ("txt_empty.txt", "json_trailing_comma.json",
                         "mhtml_empty_root.mhtml", "mhtml_empty_largest.mhtml"):
            with self.subTest(filename=filename):
                native = content.convert_file(SAMPLES / filename)
                before = copy.deepcopy(native)
                self.assertFalse(native.success)

                report = handoff.adapt_result(native)
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "失败.json"
                    output.write_text("existing", encoding="utf-8")
                    saved = json.loads(handoff.export_json(report, output).read_bytes())

                self.assertEqual(saved["status"], "failed")
                document = saved["documents"][0]
                self.assertEqual(document["status"], "failed")
                self.assertIsNone(document["body"])
                self.assertEqual(document["units"], [])
                self.assertEqual(document["metadata"]["encoding"], native.encoding)
                diagnostic = document["diagnostics"][-1]
                self.assertEqual([item["message"] for item in document["diagnostics"][:-1]], native.warnings)
                self.assertEqual(diagnostic["level"], "error")
                self.assertEqual(diagnostic["code"], "upstream_error")
                self.assertEqual(diagnostic["message"], native.error)
                self.assertEqual(diagnostic["document_id"], document["id"])
                self.assertEqual(diagnostic["source_id"], document["sources"][0]["id"])
                self.assertEqual(document["sources"][0]["locator"]["location"], str(SAMPLES / filename))
                if filename == "mhtml_empty_root.mhtml":
                    self.assertEqual(document["sources"][0]["locator"]["content_id"], "<empty-root>")
                    self.assertEqual(document["sources"][0]["locator"]["mime_index"], 2)
                self.assertEqual(native, before)

    def test_mhtml_selected_part_and_warnings_remain_linked_to_document(self):
        native = content.convert_file(SAMPLES / "chromium_multi_frames_contentid.mht", mode="full")
        before = copy.deepcopy(native)
        self.assertTrue(native.success, native.error)

        report = handoff.adapt_result(native)
        with tempfile.TemporaryDirectory() as directory:
            saved = json.loads(handoff.export_json(report, Path(directory) / "mhtml.json").read_bytes())

        document = saved["documents"][0]
        source = document["sources"][0]
        self.assertEqual(document["body"], native.markdown)
        self.assertIn("This page contains several frames.", document["body"])
        self.assertNotIn("The first frame!", document["body"])
        self.assertEqual(source["locator"]["content_location"], "http://localhost/top_frame.html")
        self.assertIsNone(source["locator"]["content_id"])
        self.assertEqual(source["locator"]["mime_index"], 1)
        self.assertEqual(source["locator"]["encoding"], "iso8859-1")
        self.assertEqual(document["metadata"]["encoding"], "iso8859-1")
        self.assertEqual([item["message"] for item in document["diagnostics"]], native.warnings)
        self.assertEqual(document["diagnostics"][0]["level"], "warning")
        self.assertEqual(document["diagnostics"][0]["code"], "upstream_warning")
        self.assertEqual(document["diagnostics"][0]["document_id"], document["id"])
        self.assertEqual(document["diagnostics"][0]["source_id"], source["id"])
        self.assertNotIn(native.warnings[0], document["body"])
        report.documents[0].sources[0].locator["content_location"] = "changed"
        report.documents[0].diagnostics[0].message = "changed"
        self.assertEqual(native, before)

    def test_txt_body_and_document_source_survive_json_roundtrip(self):
        path = SAMPLES / "txt_utf8_layout.txt"
        native = content.convert_file(path, source="中文公告.txt")
        before = copy.deepcopy(native)

        report = handoff.adapt_result(native)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "交接.json"
            self.assertEqual(handoff.export_json(report, output), output)
            raw = output.read_bytes()
            saved = json.loads(raw.decode("utf-8"))

        self.assertEqual(native, before)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("中文公告.txt".encode("utf-8"), raw)
        self.assertEqual(saved["status"], "success")
        self.assertEqual(len(saved["documents"]), 1)
        document = saved["documents"][0]
        self.assertEqual(document["body"], native.markdown)
        self.assertIn("    保留四个空格\t和制表符。", document["body"])
        self.assertEqual(document["body_format"], "markdown")
        self.assertIsNone(document["business_id"])
        self.assertIsNone(document["version"])
        self.assertEqual(document["metadata"]["encoding"], "utf-8")
        self.assertFalse(document["requires_review"])
        self.assertEqual(document["diagnostics"], [])
        self.assertEqual(len(document["sources"]), 1)
        source = document["sources"][0]
        self.assertEqual(source["kind"], "document")
        self.assertEqual(source["locator"]["location"], "中文公告.txt")
        self.assertEqual(source["locator"]["format"], "txt")
        self.assertEqual(len(document["units"]), 1)
        unit = document["units"][0]
        self.assertEqual(unit["kind"], "document")
        self.assertEqual(unit["text"], document["body"])
        self.assertEqual(unit["source_ids"], [source["id"]])
        self.assertEqual(unit["alignment"], "document")
        self.assertIsNone(unit["body_span"])
        self.assertIsNone(unit["parent_id"])
        self.assertEqual(len({document["id"], source["id"], unit["id"]}), 3)


if __name__ == "__main__":
    unittest.main()
