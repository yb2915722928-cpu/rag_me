import importlib
from pathlib import Path
import unittest


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.pdfAndDocxExtraction"
)
SAMPLES = Path(__file__).parent / "testFile"


class DocxConversionTests(unittest.TestCase):
    def test_ocr_page_selection_is_rejected_for_docx(self):
        path = SAMPLES / "docx_teaching.docx"
        results = (
            content.convert_file(path, ocr_pages=(1,)),
            content.convert_bytes(path.read_bytes(), format="docx", source=str(path), ocr_pages=(1,)),
        )
        for result in results:
            self.assertFalse(result.success)
            self.assertIsNone(result.markdown)
            self.assertEqual(result.sources, [])
            self.assertIn("ocr_pages", result.error)
            self.assertIn("PDF", result.error)

    def test_heading_depth_beyond_markdown_retains_native_level_and_reports_flattening(self):
        result = content.convert_file(SAMPLES / "docx_deep_headings.docx")

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown, "###### 六级标题\n\n###### 七级标题\n\n###### 九级标题\n"
        )
        self.assertEqual([block.heading_level for block in result.sources], [6, 7, 9])
        self.assertEqual(result.sources[-1].section_path, ("六级标题", "七级标题", "九级标题"))
        self.assertTrue(any("block 2" in warning and "level 7" in warning for warning in result.warnings))
        self.assertTrue(any("block 3" in warning and "level 9" in warning for warning in result.warnings))
        for warning in result.warnings:
            self.assertNotIn(warning, result.markdown)

    def test_docx_support_limits_are_warnings_outside_the_markdown(self):
        result = content.convert_file(SAMPLES / "docx_teaching.docx")

        self.assertTrue(result.success, result.error)
        self.assertTrue(any("simple" in warning and "table" in warning for warning in result.warnings))
        self.assertTrue(any("image" in warning for warning in result.warnings))
        self.assertTrue(any("header" in warning for warning in result.warnings))
        for warning in result.warnings:
            self.assertNotIn(warning, result.markdown)

    def test_native_outline_and_inherited_styles_define_headings_instead_of_style_names(self):
        result = content.convert_file(SAMPLES / "docx_outline_headings.docx")

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "# 维护规程\n\n## 例行检查\n\n### 停机规则\n\n名称含 Heading 的普通说明。\n",
        )
        self.assertEqual(
            [block.section_path for block in result.sources],
            [("维护规程",), ("维护规程", "例行检查"),
             ("维护规程", "例行检查", "停机规则"), ("维护规程", "例行检查", "停机规则")],
        )
        self.assertEqual(
            [block.section_block_number for block in result.sources], [1, 1, 1, 2]
        )
        self.assertEqual(result.sources[-1].block_type, "paragraph")

    def test_cell_pipes_backslashes_and_line_breaks_do_not_change_column_relations(self):
        path = SAMPLES / "docx_table_cells.docx"
        result = content.convert_bytes(path.read_bytes(), format="docx", source=str(path))

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "# 周期表\n\n| 设备 \\| 部件 | 周期 |\n| --- | --- |\n"
            "| 泵\\\\备用 | 每月<br>断电检查 |\n| 阀门 | 每季度<br>记录结果 |\n",
        )
        self.assertEqual(len(result.sources), 2)
        self.assertEqual(result.sources[1].body_block_number, 2)
        self.assertEqual(result.sources[1].section_block_number, 2)

    def test_empty_paragraphs_headings_and_table_do_not_become_usable_body(self):
        path = SAMPLES / "docx_empty.docx"
        results = (
            content.convert_file(path),
            content.convert_bytes(path.read_bytes(), format="docx", source=str(path)),
        )

        for result in results:
            with self.subTest(result=result):
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIn("No usable text body", result.error)
                self.assertEqual(result.source.format, "docx")

    def test_corrupt_docx_returns_diagnostic_without_partial_or_error_body(self):
        for filename in ("docx_corrupt.docx", "docx_invalid_xml.docx", "docx_missing_part.docx"):
            path = SAMPLES / filename
            with self.subTest(filename=filename):
                results = (
                    content.convert_file(path),
                    content.convert_bytes(path.read_bytes(), format="docx", source=str(path)),
                )
                for result in results:
                    self.assertFalse(result.success)
                    self.assertIsNone(result.markdown)
                    self.assertEqual(result.sources, [])
                    self.assertIn("DOCX", result.error)
                    self.assertIn("failed", result.error)
                    self.assertEqual(result.source.location, str(path))
                    self.assertEqual(result.source.format, "docx")

    def test_two_device_relations_and_heading_sections_keep_body_block_positions(self):
        result = content.convert_file(SAMPLES / "docx_sections.docx")

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "文档说明。\n\n# 设备维护\n\n维护前必须断电。\n\n"
            "| 设备 | 周期 |\n| --- | --- |\n| 泵 | 每月 |\n| 阀门 | 每季度 |\n\n"
            "检查后重新启动。\n\n## 例行检查\n\n记录检查结果。\n\n"
            "### 注意事项\n\n不得带电维护。\n\n## 停机检查\n\n确认阀门关闭。\n\n"
            "# 设备维护\n\n下轮维护沿用周期表。\n",
        )
        self.assertEqual(
            [(block.body_block_number, block.section_path, block.section_block_number)
             for block in result.sources],
            [(1, (), 1), (2, ("设备维护",), 1), (3, ("设备维护",), 2),
             (4, ("设备维护",), 3), (5, ("设备维护",), 4),
             (6, ("设备维护", "例行检查"), 1), (8, ("设备维护", "例行检查"), 3),
             (9, ("设备维护", "例行检查", "注意事项"), 1),
             (10, ("设备维护", "例行检查", "注意事项"), 2),
             (11, ("设备维护", "停机检查"), 1), (12, ("设备维护", "停机检查"), 2),
             (13, ("设备维护",), 1), (14, ("设备维护",), 2)],
        )
        table_source = result.sources[3]
        self.assertEqual(table_source.block_type, "table")
        self.assertEqual(
            result.markdown[table_source.markdown_start:table_source.markdown_end],
            "| 设备 | 周期 |\n| --- | --- |\n| 泵 | 每月 |\n| 阀门 | 每季度 |\n",
        )
        self.assertTrue(all(block.pdf_page_number is None for block in result.sources))

    def test_file_and_bytes_map_each_block_to_its_section_without_page_numbers(self):
        path = SAMPLES / "docx_teaching.docx"
        result = content.convert_bytes(
            path.read_bytes(), format=" .DOCX ", source="upload:maintenance"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result,
            content.convert_file(path, format="docx", source="upload:maintenance"),
        )
        self.assertEqual(result.source.location, "upload:maintenance")
        self.assertEqual(result.source.format, "docx")
        self.assertEqual(len(result.sources), 4)
        self.assertEqual(
            [result.markdown[block.markdown_start:block.markdown_end]
             for block in result.sources],
            ["# Equipment Maintenance\n", "Disconnect power before maintenance.\n",
             "| Equipment | Interval |\n| --- | --- |\n| Pump | Monthly |\n",
             "Restart after inspection.\n"],
        )
        self.assertEqual([block.body_block_number for block in result.sources], [1, 2, 3, 4])
        self.assertEqual([block.section_block_number for block in result.sources], [1, 2, 3, 4])
        self.assertEqual(
            [block.block_type for block in result.sources],
            ["heading", "paragraph", "table", "paragraph"],
        )
        for block in result.sources:
            self.assertEqual(block.section_path, ("Equipment Maintenance",))
            self.assertEqual(block.extraction_method, "docx_native")
            self.assertIsNone(block.pdf_page_number)
        self.assertNotIn("upload:maintenance", result.markdown)

    def test_teaching_docx_retains_heading_and_table_between_explanations(self):
        path = SAMPLES / "docx_teaching.docx"

        result = content.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "# Equipment Maintenance\n\n"
            "Disconnect power before maintenance.\n\n"
            "| Equipment | Interval |\n| --- | --- |\n| Pump | Monthly |\n\n"
            "Restart after inspection.\n",
        )
        self.assertEqual(result.source.location, str(path))
        self.assertEqual(result.source.format, "docx")
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
