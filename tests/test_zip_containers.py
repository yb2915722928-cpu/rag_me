import importlib
import json
from pathlib import Path
import unittest


zip_containers = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.8_zipContainers"
)
SAMPLES = Path(__file__).parent / "testFile"


class ZipContainerTests(unittest.TestCase):
    def test_json_projection_retains_native_success_warnings_and_excludes_options(self):
        result = zip_containers.convert_file(
            SAMPLES / "zip_lightweight.zip",
            parser_options={"csv": {"encoding": "gb18030", "delimiter": ";"},
                            "document": {"unused_marker": "DO_NOT_ECHO_CONFIG"}},
        )
        report = result.to_dict()
        encoded = json.dumps(report, ensure_ascii=False)

        self.assertEqual(report["status"], "success")
        self.assertTrue(report["success"])
        self.assertFalse(report["requires_review"])
        self.assertEqual(report["counts"]["success"], 4)
        native = report["members"][2]["result"]
        self.assertTrue(native["success"])
        self.assertFalse(native["requires_review"])
        self.assertEqual(native["tables"][0]["rows"][0]["cells"][1]["raw_value"], "00500")
        self.assertTrue(native["warnings"])
        self.assertNotIn("DO_NOT_ECHO_CONFIG", encoded)
        self.assertNotIn("parser_options", encoded)

    def test_legacy_member_names_and_text_encoding_are_independent(self):
        result = zip_containers.convert_file(
            SAMPLES / "zip_legacy_names.zip", metadata_encoding="gb18030",
            parser_options={"text": {"encoding": "utf-16"}},
        )
        self.assertTrue(result.success, result)
        self.assertEqual(result.members[0].source.member_path, "资料.txt")
        self.assertEqual(result.members[0].result.markdown, "独立正文编码")
        self.assertEqual(result.members[0].result.encoding, "utf-16")
        default_names = zip_containers.convert_file(SAMPLES / "zip_legacy_names.zip")
        self.assertNotEqual(default_names.members[0].source.member_path, "资料.txt")
        utf8_names = zip_containers.convert_file(SAMPLES / "zip_text.zip", metadata_encoding="gb18030")
        self.assertEqual(utf8_names.members[0].source.member_path, "资料/说明.txt")

    def test_invalid_inputs_and_options_return_diagnostics_before_parsing(self):
        data = (SAMPLES / "zip_text.zip").read_bytes()
        for options, diagnostic in (
            ({"source": " "}, "source"), ({"source": 12}, "source"),
            ({"limits": {}}, "ZipLimits"),
            ({"metadata_encoding": "not-a-codec"}, "encoding"),
            ({"parser_options": []}, "parser_options"),
            ({"parser_options": {"unknown": {}}}, "category"),
            ({"parser_options": {"text": None}}, "mapping"),
            ({"parser_options": {"text": {"source": "override"}}}, "source"),
            ({"parser_options": {"text": {"format": "html"}}}, "format"),
            ({"parser_options": {"document": {"limits": {}}}}, "limits"),
            ({"limits": zip_containers.ZipLimits(max_members=0)}, "max_members"),
            ({"limits": zip_containers.ZipLimits(max_member_bytes=True)}, "max_member_bytes"),
            ({"limits": zip_containers.ZipLimits(timeout_seconds=float("nan"))}, "timeout_seconds"),
        ):
            with self.subTest(diagnostic=diagnostic, options=options):
                result = zip_containers.convert_bytes(data, **({"source": "test.zip"} | options))
                self.assertFalse(result.success)
                self.assertIn(diagnostic, result.error)
                self.assertEqual(result.members, [])
        for data in (None, "zip", bytearray(b"zip")):
            result = zip_containers.convert_bytes(data, source="invalid.zip")
            self.assertIn("bytes", result.error)
        for path in (None, 12, SAMPLES, SAMPLES / "zip_missing.zip"):
            result = zip_containers.convert_file(path)
            self.assertEqual(result.status, "failed")
            self.assertTrue(result.error)
            self.assertEqual(result.members, [])

    def test_empty_metadata_failed_and_corrupt_archives_never_report_success(self):
        for name, counts in (
            ("zip_empty.zip", dict(total=0, success=0, failed=0, ignored=0, unprocessed=0)),
            ("zip_metadata.zip", dict(total=3, success=0, failed=0, ignored=3, unprocessed=0)),
            ("zip_all_failed.zip", dict(total=2, success=0, failed=2, ignored=0, unprocessed=0)),
            ("zip_corrupt.zip", dict(total=0, success=0, failed=0, ignored=0, unprocessed=0)),
        ):
            with self.subTest(name=name):
                result = zip_containers.convert_file(SAMPLES / name)
                self.assertEqual(result.status, "failed")
                self.assertFalse(result.success)
                self.assertEqual(result.counts, counts)
                self.assertFalse(result.requires_review)
                if name in ("zip_empty.zip", "zip_metadata.zip"):
                    self.assertIn("No processable documents", result.error)
        self.assertIn("ZIP", result.error)

    def test_dangerous_encrypted_crc_and_read_failures_are_isolated(self):
        result = zip_containers.convert_file(SAMPLES / "zip_rejected.zip")

        self.assertEqual(result.status, "partial_success")
        self.assertEqual(result.counts, dict(total=11, success=1, failed=10, ignored=0, unprocessed=0))
        self.assertEqual([member.reason for member in result.members[:7]], ["unsafe_path"] * 7)
        self.assertEqual(result.members[3].source.member_path, "C:\\drive.txt")
        self.assertEqual(result.members[7].reason, "encrypted_member")
        self.assertEqual(result.members[8].reason, "read_error")
        self.assertIn("CRC", result.members[8].error)
        self.assertEqual(result.members[9].reason, "read_error")
        self.assertIn("header", result.members[9].error)
        self.assertEqual(result.members[-1].result.markdown, "后续正常")
        for member in result.members[:-1]:
            self.assertIsNone(member.result)
            self.assertTrue(member.error)

    def test_partial_success_preserves_duplicates_hidden_documents_and_native_failures(self):
        result = zip_containers.convert_file(SAMPLES / "zip_members.zip")

        self.assertEqual(result.status, "partial_success")
        self.assertFalse(result.success)
        self.assertEqual(result.counts, dict(total=13, success=6, failed=3, ignored=4, unprocessed=0))
        self.assertEqual([result.members[i].result.markdown for i in (1, 2, 3, 4, 8, 12)],
                         ["目录 A", "目录 B", "首次", "再次", "合法隐藏文档", "仍然成功"])
        self.assertEqual(result.members[3].source.member_path, result.members[4].source.member_path)
        self.assertNotEqual(result.members[3].source.entry_index, result.members[4].source.entry_index)
        self.assertEqual(result.members[9].reason, "nested_zip")
        self.assertEqual(result.members[10].reason, "unsupported_format")
        failure = result.members[11]
        self.assertEqual(failure.reason, "parse_error")
        self.assertIn("Invalid JSON", failure.error)
        self.assertFalse(failure.result.success)
        self.assertIsNone(failure.result.markdown)
        self.assertEqual(failure.result.sources, [])

    def test_structured_nodes_and_csv_cells_keep_native_relations_and_category_options(self):
        result = zip_containers.convert_file(
            SAMPLES / "zip_lightweight.zip", source="structure.zip",
            parser_options={"text": {"encoding": "gb18030"},
                            "csv": {"encoding": "gb18030", "delimiter": ";", "mode": "rows"}},
        )

        self.assertTrue(result.success, result)
        json_member, xml_member, csv_member, text_member = result.members
        self.assertEqual([m.result_kind for m in result.members], ["structured", "structured", "csv", "text"])
        self.assertEqual([s.node_path for s in json_member.result.sources], ["", "/rules", "/rules/0", "/rules/0/city", "/rules/0/amount"])
        self.assertEqual([s.node_path for s in xml_member.result.sources], ["/rules[1]", "/rules[1]/city[1]"])
        self.assertIn('<!--保留-->', xml_member.result.markdown)
        table = csv_member.result.tables[0]
        self.assertEqual([c.name for c in table.columns], ["城市", "额度"])
        self.assertEqual([c.raw_value for c in table.rows[0].cells], ["北京", "00500"])
        self.assertEqual(table.rows[0].cells[1].source.column_start, 2)
        self.assertEqual(table.rows[0].source.row_start, 2)
        self.assertEqual(table.source.source.location, "structure.zip!/rates.csv#3")
        self.assertIn("额度：00500", csv_member.result.markdown)
        self.assertTrue(csv_member.result.warnings)
        self.assertNotIn(csv_member.result.warnings[0], csv_member.result.markdown)
        self.assertEqual(text_member.result.markdown, "正文编码独立于文件名。")

    def test_file_and_bytes_preserve_text_members_and_container_provenance(self):
        path = SAMPLES / "zip_text.zip"
        result = zip_containers.convert_file(path, source="uploaded.zip")
        from_bytes = zip_containers.convert_bytes(path.read_bytes(), source="uploaded.zip")

        self.assertEqual(result, from_bytes)
        self.assertEqual(result.status, "success")
        self.assertTrue(result.success)
        self.assertEqual(result.counts, dict(total=2, success=2, failed=0, ignored=0, unprocessed=0))
        self.assertEqual([member.source.member_path for member in result.members], ["资料/说明.txt", "guide.MD"])
        self.assertEqual([member.source.entry_index for member in result.members], [1, 2])
        self.assertEqual(result.members[0].source.container, "uploaded.zip")
        self.assertEqual(result.members[0].result.markdown, "ZIP 容器示例\n两行原文\n")
        self.assertEqual(result.members[1].result.markdown, "# 使用方法\n\n保留 **强调**。\n")
        self.assertEqual(result.members[0].result.source.location, "uploaded.zip!/资料/说明.txt#1")
        self.assertEqual([member.result_kind for member in result.members], ["text", "text"])


if __name__ == "__main__":
    unittest.main()
