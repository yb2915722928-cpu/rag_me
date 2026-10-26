import importlib
from pathlib import Path
import tempfile
import unittest


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)
SAMPLES = Path(__file__).parent / "testFile"


class HtmlConversionTests(unittest.TestCase):
    def test_bytes_and_utf8_export_keep_source_and_diagnostics_out_of_body(self):
        data = (SAMPLES / "html_invalid_declaration.html").read_bytes()
        source = content.Source("uploaded-page.htm")

        result = content.convert_bytes(data, format=".HTM", source=source, mode="full")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source, content.Source("uploaded-page.htm", "htm"))
        self.assertIsNone(source.format)
        self.assertTrue(result.warnings)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.md"
            exported_path = content.export_markdown(result, path)
            exported = exported_path.read_bytes()
        self.assertEqual(exported_path, path)
        self.assertEqual(exported, result.markdown.encode("utf-8"))
        self.assertIn("长江流经武汉，黄河流经兰州。", exported.decode("utf-8"))
        self.assertFalse(exported.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", exported)
        self.assertNotIn(source.location, result.markdown)
        for warning in result.warnings:
            self.assertNotIn(warning, exported.decode("utf-8"))

    def test_explicit_html_encoding_wins_over_declaration_and_bom(self):
        for filename, encoding in (
            ("html_explicit_override.html", "gb18030"),
            ("html_utf8_bom_conflict.html", "utf-8"),
        ):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename, encoding=encoding)

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.encoding, encoding)
                self.assertIn("长江流经武汉，黄河流经兰州。", result.markdown)
                self.assertEqual(result.warnings, [])

    def test_bom_wins_over_conflicting_html_declaration(self):
        for filename, encoding in (
            ("html_utf8_bom_conflict.html", "utf-8-sig"),
            ("html_utf16_bom_conflict.html", "utf-16"),
        ):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename)

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.encoding, encoding)
                self.assertIn("长江流经武汉，黄河流经兰州。", result.markdown)
                self.assertNotIn("\ufeff", result.markdown)
                self.assertEqual(result.warnings, [])

    def test_declaration_wins_over_valid_utf8_and_can_be_overridden(self):
        path = SAMPLES / "html_declaration_before_utf8.html"

        declared = content.convert_file(path)
        explicit = content.convert_file(path, encoding="utf-8")

        self.assertTrue(declared.success, declared.error)
        self.assertTrue(explicit.success, explicit.error)
        self.assertEqual(declared.encoding, "iso8859-1")
        self.assertEqual(declared.markdown, "cafÃ©\n")
        self.assertEqual(explicit.markdown, "café\n")

    def test_invalid_or_unusable_declarations_warn_then_fall_back_to_utf8(self):
        result = content.convert_file(SAMPLES / "html_invalid_declaration.html")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.encoding, "utf-8")
        self.assertIn("长江流经武汉，黄河流经兰州。", result.markdown)
        self.assertEqual(len(result.warnings), 2)
        self.assertIn("no-such-text-codec", result.warnings[0])
        self.assertIn("ascii", result.warnings[1])
        for warning in result.warnings:
            self.assertNotIn(warning, result.markdown)

    def test_legacy_encoding_without_declaration_is_detected_and_reported(self):
        result = content.convert_file(SAMPLES / "html_detected_gb18030.html")

        self.assertTrue(result.success, result.error)
        self.assertIn("长江流经武汉，黄河流经兰州。", result.markdown)
        self.assertIn("北京是中国的首都，故宫位于北京市中心。", result.markdown)
        self.assertNotIn("\ufffd", result.markdown)
        self.assertIsNotNone(result.encoding)
        self.assertTrue(result.warnings)
        self.assertIn(result.encoding, " ".join(result.warnings))

    def test_html_decode_errors_return_failure_without_fallback_body(self):
        for filename, encoding in (
            ("html_declared_gb18030.html", "utf-8"),
            ("html_utf16_bom_conflict.html", "utf-8"),
            ("html_declared_gb18030.html", "no-such-text-codec"),
            ("html_undecodable.html", None),
            ("html_truncated_utf16.html", None),
        ):
            with self.subTest(filename=filename, encoding=encoding):
                result = content.convert_file(SAMPLES / filename, encoding=encoding)

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertIn("decoding", result.error.lower())
                self.assertEqual(result.warnings, [])

    def test_html_charset_and_http_equiv_declarations_decode_chinese_without_guessing(self):
        for filename in ("html_declared_gb18030.html", "html_http_equiv_gb18030.html"):
            with self.subTest(filename=filename):
                result = content.convert_file(SAMPLES / filename)

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.encoding, "gb18030")
                self.assertIn("长江流经武汉，黄河流经兰州。", result.markdown)
                self.assertEqual(result.warnings, [])

    def test_article_candidates_select_body_and_htm_file_is_supported(self):
        for filename in (
            "html_candidate_main.html", "html_candidate_article.htm", "html_candidate_role.html",
        ):
            with self.subTest(filename=filename):
                path = SAMPLES / filename
                article = content.convert_file(path)
                full = content.convert_file(path, mode="full")

                self.assertTrue(article.success, article.error)
                self.assertTrue(full.success, full.error)
                self.assertEqual(article.source.format, path.suffix.lstrip("."))
                for result in (article, full):
                    self.assertIn("正文事实：黄河流经兰州。", result.markdown)
                for outside in ("候选之外的页面介绍", "候选之外的页面结语"):
                    self.assertNotIn(outside, article.markdown)
                    self.assertIn(outside, full.markdown)

    def test_fragment_without_usable_candidate_falls_back_to_cleaned_content(self):
        result = content.convert_file(SAMPLES / "html_fallback_fragment.html")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.encoding, "utf-8")
        self.assertIn("# 普通页面的正文", result.markdown)
        self.assertIn("缺少文章候选时仍保留这段文字。", result.markdown)
        self.assertNotIn("回退页面导航", result.markdown)
        self.assertNotIn("回退页面页脚", result.markdown)

    def test_image_extension_does_not_interrupt_surrounding_text(self):
        for mode in ("article", "full"):
            with self.subTest(mode=mode):
                result = content.convert_file(SAMPLES / "html_images.html", mode=mode)

                self.assertTrue(result.success, result.error)
                self.assertIn("# 文字转换继续进行", result.markdown)
                self.assertIn("图片前的文字", result.markdown)
                self.assertIn("图片后的文字", result.markdown)
                self.assertIn("第二段文字照常保留。", result.markdown)
                self.assertEqual(result.warnings, [])

    def test_script_shell_and_article_without_body_fail_and_cannot_be_exported(self):
        for filename, mode in (
            ("html_script_only.html", "article"),
            ("html_script_only.html", "full"),
            ("html_title_only.html", "article"),
            ("html_title_only.html", "full"),
            ("html_noise_only.html", "article"),
        ):
            with self.subTest(filename=filename, mode=mode):
                result = content.convert_file(SAMPLES / filename, mode=mode)

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertIn("body", result.error.lower())
                self.assertEqual(result.encoding, "utf-8")
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "failed.md"
                    with self.assertRaises(ValueError):
                        content.export_markdown(result, path)
                    self.assertFalse(path.exists())

    def test_code_preserves_blank_lines_tabs_trailing_spaces_and_literal_fences(self):
        for mode in ("article", "full"):
            with self.subTest(mode=mode):
                result = content.convert_file(SAMPLES / "html_code_whitespace.html", mode=mode)

                self.assertTrue(result.success, result.error)
                expected_code = (
                    '\n\n  def greet(name):  \n\treturn "hello  " + name  \n   \n\n'
                    '```\n  print(greet("北京"))  \n\n'
                )
                fenced = result.markdown.split("````\n")
                self.assertEqual(len(fenced), 3)
                self.assertEqual(fenced[1], expected_code)
                self.assertIn("代码前的说明。", fenced[0])
                self.assertIn("代码后的说明。", fenced[2])

    def test_headings_nested_lists_table_rows_and_text_link_keep_structure(self):
        result = content.convert_file(SAMPLES / "html_structure.html")

        self.assertTrue(result.success, result.error)
        self.assertIn("# 旅行资料\n", result.markdown)
        self.assertIn("## 出发准备\n", result.markdown)
        self.assertIn("### 城市与河流\n", result.markdown)
        self.assertIn("1. 核对证件\n   * 身份证\n   * 车票\n2. 整理行李", result.markdown)
        self.assertIn(
            "| 城市 | 河流 |\n| --- | --- |\n| 武汉 | 长江 |\n| 兰州 | 黄河 |",
            result.markdown,
        )
        self.assertIn("[旅行指南](https://example.org/guide?q=1&lang=zh)", result.markdown)

    def test_article_filters_noise_and_full_keeps_wider_page_content(self):
        path = SAMPLES / "html_structure.html"

        article = content.convert_file(path)
        full = content.convert_file(path, mode="full")

        for result in (article, full):
            self.assertTrue(result.success, result.error)
            self.assertIn("# 旅行资料", result.markdown)
            self.assertIn("北京是中国的首都，长江流经武汉。", result.markdown)
            for noise in (
                "站点标题，不是正文标题", "secret-style-marker", "script_marker",
                "脚本替代唯一标记", "模板唯一标记",
            ):
                self.assertNotIn(noise, result.markdown)
        for noise in (
            "站点导航唯一标记", "类名导航唯一标记", "站外广告唯一标记",
            "文章侧栏唯一标记", "文内广告唯一标记", "文章页脚唯一标记",
            "站点页脚唯一标记", "容器页脚唯一标记",
        ):
            self.assertNotIn(noise, article.markdown)
            self.assertIn(noise, full.markdown)

    def test_python_tutorial_preserves_known_headings_paragraph_and_code(self):
        path = SAMPLES / "python_datastructures.html"

        result = content.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source, content.Source(str(path), "html"))
        self.assertEqual(result.encoding, "utf-8")
        self.assertEqual(result.warnings, [])
        self.assertIn("# 5. Data Structures", result.markdown)
        self.assertIn("## 5.1. More on Lists", result.markdown)
        self.assertIn("### 5.1.1. Using Lists as Stacks", result.markdown)
        self.assertIn(
            "This chapter describes some things you’ve learned about already in more detail",
            result.markdown,
        )
        self.assertIn(
            ">>> fruits = ['orange', 'apple', 'pear', 'banana', 'kiwi', 'apple', 'banana']\n"
            ">>> fruits.count('apple')\n2\n",
            result.markdown,
        )
        self.assertNotIn("<html", result.markdown)


if __name__ == "__main__":
    unittest.main()
