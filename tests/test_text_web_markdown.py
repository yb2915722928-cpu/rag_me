import importlib
from pathlib import Path
import tempfile
import unittest


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)
SAMPLES = Path(__file__).parent / "testFile"


class MarkdownConversionTests(unittest.TestCase):
    def test_bom_only_and_whitespace_only_markdown_have_no_usable_body(self):
        for filename in ("md_bom_only.md", "md_whitespace.md"):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename)

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.error, "No usable text body")
                self.assertIsNotNone(result.encoding)

    def test_bom_is_removed_before_normalization_and_export(self):
        result = content.convert_file(SAMPLES / "md_utf8_bom.md")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.encoding, "utf-8-sig")
        self.assertEqual(result.markdown, "# 编码\n\n正文：长江流经武汉。\n")
        self.assertEqual(result.warnings, [])

        with tempfile.TemporaryDirectory() as directory:
            output = content.export_markdown(result, Path(directory) / "bom-free.md")
            self.assertEqual(output.read_bytes(), "# 编码\n\n正文：长江流经武汉。\n".encode("utf-8"))

    def test_strict_decoding_failure_has_no_body_and_cannot_create_or_overwrite_export(self):
        failures = (
            content.convert_file(SAMPLES / "md_gb18030.markdown", encoding="utf-8"),
            content.convert_bytes(
                (SAMPLES / "md_truncated_utf16.md").read_bytes(),
                format="md", source="damaged.md",
            ),
        )
        successful = content.convert_file(SAMPLES / "md_structure.md")

        with tempfile.TemporaryDirectory() as directory:
            existing = content.export_markdown(successful, Path(directory) / "existing.md")
            original = existing.read_bytes()
            missing = Path(directory) / "missing.md"

            for failed in failures:
                with self.subTest(source=failed.source.location):
                    self.assertFalse(failed.success)
                    self.assertIsNone(failed.markdown)
                    self.assertIn("Decoding failed", failed.error)
                    self.assertEqual(failed.warnings, [])
                    for output in (missing, existing):
                        with self.assertRaises(ValueError):
                            content.export_markdown(failed, output)
                    self.assertFalse(missing.exists())
                    self.assertEqual(existing.read_bytes(), original)

    def test_detected_encoding_exports_only_normalized_chinese_body_as_utf8(self):
        result = content.convert_bytes(
            (SAMPLES / "md_gb18030.markdown").read_bytes(),
            format="md", source="legacy-upload.md",
        )

        self.assertTrue(result.success, result.error)
        self.assertTrue(result.warnings)
        self.assertIn(result.encoding, " ".join(result.warnings))
        self.assertEqual(result.source, content.Source("legacy-upload.md", "md"))
        expected = (
            "# 中文资料\n\n北京是中国的首都，故宫位于北京市中心。\n\n"
            "长江流经武汉，黄河流经兰州。\n"
        )
        self.assertEqual(result.markdown, expected)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "converted.md"
            content.export_markdown(result, output)
            exported = output.read_bytes()

        self.assertEqual(exported, expected.encode("utf-8"))
        self.assertFalse(exported.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn("legacy-upload.md", exported.decode("utf-8"))
        for warning in result.warnings:
            self.assertNotIn(warning, exported.decode("utf-8"))

    def test_public_markdown_preserves_known_heading_and_reference_links(self):
        result = content.convert_file(SAMPLES / "pypa_sampleproject.md")

        self.assertTrue(result.success, result.error)
        self.assertTrue(result.markdown.startswith("# A sample Python project\n"))
        self.assertIn("[The source for this project is available here][src].", result.markdown)
        self.assertIn("[src]: https://github.com/pypa/sampleproject\n", result.markdown)
        self.assertIn("[packaging guide]: https://packaging.python.org\n", result.markdown)
        self.assertIn("[Python Packaging User\nGuide][packaging guide]", result.markdown)
        self.assertIn(
            "[md use]: https://packaging.python.org/specifications/core-metadata/"
            "#description-content-type-optional",
            result.markdown,
        )
        self.assertIn("a simple “What's New” section", result.markdown)

    def test_markdown_alias_accepts_file_and_bytes_with_explicit_encoding(self):
        path = SAMPLES / "md_gb18030.markdown"
        source = content.Source("upload.markdown")
        results = (
            content.convert_file(path, encoding="GB18030"),
            content.convert_bytes(
                path.read_bytes(), format=".MARKDOWN", source=source,
                encoding="GB18030", mode="full",
            ),
        )

        for result, location in zip(results, (str(path), "upload.markdown")):
            with self.subTest(location=location):
                self.assertTrue(result.success, result.error)
                self.assertEqual(result.source, content.Source(location, "markdown"))
                self.assertEqual(result.encoding, "gb18030")
                self.assertEqual(result.warnings, [])
                self.assertEqual(
                    result.markdown,
                    "# 中文资料\n\n北京是中国的首都，故宫位于北京市中心。\n\n"
                    "长江流经武汉，黄河流经兰州。\n",
                )
        self.assertEqual(source, content.Source("upload.markdown"))

    def test_list_item_fence_preserves_code_blanks_and_list_relationships(self):
        result = content.convert_file(SAMPLES / "md_list_fence.md")

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "# 列表中的代码\n\n"
            "- ```text\n  first  value\n\n\n  second\n  ```\n"
            "- 后续项目\n  - 子项目\n\n"
            "结束。\n",
        )

    def test_indented_code_preserves_internal_blank_lines_and_whitespace(self):
        result = content.convert_file(SAMPLES / "md_indented_code.md")

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "# 缩进代码\n\n"
            "    value = \"\"\"first\n\n\n    second\"\"\"\n"
            "\tprint(value)\n    ```\n    \n\n\n    return value\n\n"
            "正文段落。\n\n尾段",
        )

    def test_fenced_code_retains_blank_lines_tabs_and_literal_shorter_fences(self):
        result = content.convert_file(SAMPLES / "md_fenced_code.md")

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.markdown,
            "# 围栏示例\n\n"
            "````python\n"
            "def show():\n\tprint(\"a  b\")  \n\n\n"
            "    return \"结束\"\n"
            "```\n\n\n"
            "```` trailing text\n\n\n"
            "`````\n\n"
            "~~~text\n"
            "第一行  \n\n\n\t第二行\n"
            "```\n\n\n"
            "~~~~\n\n"
            "最后一段。\n",
        )

    def test_file_normalizes_line_endings_and_redundant_blanks_without_losing_structure(self):
        path = SAMPLES / "md_structure.md"

        result = content.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source, content.Source(str(path), "md"))
        self.assertEqual(result.encoding, "utf-8")
        self.assertEqual(result.warnings, [])
        self.assertIsNone(result.error)
        self.assertEqual(
            result.markdown,
            "# 中文文档\n\n"
            "第一段：北京是中国的首都。\n\n"
            "## 列表\n\n"
            "- 第一层\n  - 第二层\n    1. 第三层\n- 同级项目\n\n"
            "### 表格与链接\n\n"
            "| 城市 | 河流 |\n| :--- | ---: |\n| 武汉 | 长江 |\n"
            "| 兰州 | 黄河 |\n\n"
            "[项目说明][project] 与 [中文链接](https://example.org/guide?q=1#章节)。\n\n"
            "[project]: https://example.org/project \"项目标题\"\n\n"
            "保留  内部空格和行末两个空格。  \n下一行。\n",
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "normalized.md"
            self.assertEqual(content.export_markdown(result, output), output)
            self.assertEqual(output.read_bytes(), result.markdown.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
