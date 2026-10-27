from importlib import import_module
from pathlib import Path
import tempfile
import unittest


content = import_module("app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments")
SAMPLES = Path(__file__).parent / "testFile"


class PresentationConversionTests(unittest.TestCase):
    def test_file_and_bytes_keep_original_slide_membership_notes_and_paragraph_levels(self):
        path = SAMPLES / "pptx_refund.pptx"
        file_result = content.convert_file(path, source="refund-upload.pptx")
        bytes_result = content.convert_bytes(path.read_bytes(), format=".PPTX", source="refund-upload.pptx")

        self.assertTrue(file_result.success, file_result.error)
        self.assertEqual(file_result, bytes_result)
        self.assertEqual(file_result.source, content.Source("refund-upload.pptx", "pptx"))
        self.assertTrue(file_result.requires_review)
        pages = [item for item in file_result.sources if item.kind == "slide"]
        self.assertEqual([item.slide_number for item in pages], list(range(1, 9)))
        self.assertEqual(pages[-1].slide_title, "退款审批流程")
        self.assertEqual(len([issue for issue in file_result.review_issues if issue.code == "reading_order_unverified"]), 8)
        finance = next(item for item in file_result.sources if item.paragraph_number is not None and "财务审核" in file_result.markdown[item.markdown_start:item.markdown_end])
        self.assertEqual((finance.slide_number, finance.slide_title, finance.paragraph_number, finance.level), (8, "退款审批流程", 3, 1))
        notes = [item for item in file_result.sources if item.kind == "notes_paragraph"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].slide_number, 8)
        self.assertIn("仅适用于企业订单", file_result.markdown[notes[0].markdown_start:notes[0].markdown_end])
        self.assertIn("企业订单超过1万元", file_result.markdown)
        self.assertIn("客服审核", file_result.markdown)
        self.assertIsNone(file_result.encoding)
        self.assertEqual(file_result.warnings, [])

    def test_columns_are_separate_objects_and_are_not_sorted_into_an_invented_reading_order(self):
        result = content.convert_file(SAMPLES / "pptx_refund.pptx")

        enterprise = next(item for item in result.sources if item.paragraph_number == 1 and "企业订单" in result.markdown[item.markdown_start:item.markdown_end])
        ordinary = next(item for item in result.sources if item.paragraph_number == 1 and "普通订单" in result.markdown[item.markdown_start:item.markdown_end])
        self.assertNotEqual(enterprise.shape_path, ordinary.shape_path)
        self.assertEqual(enterprise.shape_path, (3,))
        self.assertEqual(enterprise.shape_name, "TextBox 2")
        self.assertEqual(enterprise.bounds_emu, (5486400, 1371600, 2743200, 1371600))
        self.assertGreater(enterprise.bounds_emu[0], ordinary.bounds_emu[0])
        self.assertLess(enterprise.markdown_start, ordinary.markdown_start)
        issue = next(item for item in result.review_issues if item.code == "reading_order_unverified" and item.source.slide_number == 8)
        self.assertIn("z-order", issue.message)
        connector = next(item for item in result.review_issues if item.code == "connector_unverified")
        self.assertEqual(connector.source.slide_number, 8)
        self.assertTrue(connector.source.shape_path)
        self.assertIsNone(connector.source.markdown_start)

    def test_group_table_and_visual_objects_keep_locations_and_specific_review_issues(self):
        result = content.convert_file(SAMPLES / "pptx_visual.pptx")

        self.assertTrue(result.success, result.error)
        self.assertIsNone(next(item for item in result.sources if item.kind == "slide").slide_title)
        grouped_text = next(item for item in result.sources if item.paragraph_number == 1 and "组合内说明" in result.markdown[item.markdown_start:item.markdown_end])
        self.assertEqual(len(grouped_text.shape_path), 2)
        self.assertEqual(grouped_text.shape_path, (2, 3))
        self.assertEqual(grouped_text.bounds_emu, (457200, 457200, 2743200, 1371600))
        group = next(item for item in result.sources if item.kind == "group")
        self.assertEqual(group.bounds_emu, (1371600, 685800, 4114800, 1371600))
        finance = next(item for item in result.sources if item.kind == "table_cell" and item.row_number == 2 and item.column_number == 2)
        self.assertIn("财务审核", result.markdown[finance.markdown_start:finance.markdown_end])
        self.assertIn('<td rowspan="1" colspan="2">企业专属追加审批</td>', result.markdown)
        codes = {item.code for item in result.review_issues}
        self.assertTrue({"group_relationships_unverified", "picture_unverified", "chart_unverified", "shape_relationships_unverified", "merged_table_unverified", "unsupported_object_unverified"}.issubset(codes))
        self.assertIn(r"\#不是标题 \<b\>原文\</b\>", result.markdown)
        for item in result.sources:
            if item.markdown_start is not None:
                self.assertLessEqual(0, item.markdown_start)
                self.assertLess(item.markdown_start, item.markdown_end)
                self.assertLessEqual(item.markdown_end, len(result.markdown))
        for issue in result.review_issues:
            self.assertIn(issue.source, result.sources)
            self.assertNotIn(issue.message, result.markdown)
            self.assertEqual(issue.source.slide_number, 1)
            if issue.code != "reading_order_unverified":
                self.assertTrue(issue.source.shape_path)
                self.assertTrue(issue.source.shape_name)
            if issue.source.kind in ("group", "picture", "chart", "unsupported_object"):
                self.assertIsNone(issue.source.markdown_start)
                self.assertIsNone(issue.source.markdown_end)

    def test_tables_keep_literal_cells_spans_and_grid_sources_without_assuming_headers(self):
        result = content.convert_file(SAMPLES / "pptx_tables.pptx")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.markdown.count("<table>"), 2)
        self.assertNotIn("<th", result.markdown)
        self.assertIn("<td>订单类型</td><td>审核部门</td>", result.markdown)
        self.assertIn("<td>客服 &lt;审核&gt; &amp; 退款<br>原文说明</td>", result.markdown)
        self.assertIn('<td rowspan="2" colspan="1">企业订单</td>', result.markdown)
        cells = [item for item in result.sources if item.kind == "table_cell"]
        self.assertEqual([(item.shape_path, item.row_number, item.column_number) for item in cells], [
            ((2,), 1, 1), ((2,), 1, 2), ((2,), 2, 1), ((2,), 2, 2),
            ((3,), 1, 1), ((3,), 1, 2), ((3,), 2, 2),
        ])
        self.assertEqual(result.markdown[cells[-1].markdown_start:cells[-1].markdown_end], "<td>超过1万元追加负责人审批</td>")
        merged_issue = next(issue for issue in result.review_issues if issue.code == "merged_table_unverified")
        self.assertEqual(merged_issue.source.shape_path, (3,))

    def test_image_only_slide_is_reviewable_without_claiming_ocr_text(self):
        result = content.convert_file(SAMPLES / "pptx_image_only.pptx")

        self.assertTrue(result.success, result.error)
        self.assertTrue(result.requires_review)
        self.assertEqual(result.markdown, "# 第 1 页\n\n")
        self.assertTrue(any(item.code == "picture_unverified" for item in result.review_issues))

    def test_corruption_and_no_slides_fail_atomically_without_export(self):
        for name in ("pptx_corrupt.pptx", "pptx_empty.pptx", "pptx_atomic_failure.pptx", "pptx_atomic_shape_failure.pptx", "pptx_corrupt_compression.pptx"):
            with self.subTest(name=name):
                path = SAMPLES / name
                result = content.convert_bytes(path.read_bytes(), format="pptx", source=name)

                self.assertEqual(result, content.convert_file(path, source=name))
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertEqual(result.review_issues, [])
                self.assertIn("PPTX", result.error)
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "existing.md"
                    output.write_bytes(b"existing")
                    with self.assertRaises(ValueError):
                        content.export_markdown(result, output)
                    self.assertEqual(output.read_bytes(), b"existing")
                    missing = Path(directory) / "missing.md"
                    with self.assertRaises(ValueError):
                        content.export_markdown(result, missing)
                    self.assertFalse(missing.exists())

    def test_explicit_format_overrides_the_extension_and_preserves_the_input_path(self):
        path = SAMPLES / "pptx_override.bin"
        inferred = content.convert_file(path)
        result = content.convert_file(path, format=" .PPTX ")
        from_bytes = content.convert_bytes(path.read_bytes(), format="pptx", source=str(path))

        self.assertFalse(inferred.success)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result, from_bytes)
        self.assertEqual(result.source, content.Source(str(path), "pptx"))

    def test_public_options_and_file_errors_return_failures(self):
        results = [
            content.convert_file(SAMPLES / "missing.pptx"),
            content.convert_file(SAMPLES / "pptx_refund.pptx", encoding="utf-8"),
            content.convert_bytes(b"", format="ppt", source="old.ppt"),
            content.convert_bytes("not bytes", format="pptx", source="upload.pptx"),
            content.convert_bytes(b"", format="pptx", source=""),
            content.convert_bytes(b"", format=None, source="upload.pptx"),
        ]
        for result in results:
            self.assertFalse(result.success)
            self.assertIsNone(result.markdown)
            self.assertTrue(result.error)
            self.assertEqual(result.sources, [])

    def test_damaged_compression_returns_failure_instead_of_raising(self):
        path = SAMPLES / "pptx_corrupt_compression.pptx"
        file_result = content.convert_file(path)
        bytes_result = content.convert_bytes(path.read_bytes(), format="pptx", source=str(path))

        self.assertEqual(file_result, bytes_result)
        self.assertFalse(file_result.success)
        self.assertIsNone(file_result.markdown)
        self.assertEqual(file_result.sources, [])
        self.assertEqual(file_result.review_issues, [])
        self.assertIn("PPTX", file_result.error)

    def test_export_contains_only_successful_markdown(self):
        result = content.convert_file(SAMPLES / "pptx_refund.pptx")

        with tempfile.TemporaryDirectory() as directory:
            output = content.export_markdown(result, Path(directory) / "refund.md")
            self.assertEqual(output.read_bytes(), result.markdown.encode("utf-8"))
            for issue in result.review_issues:
                self.assertNotIn(issue.message, output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
