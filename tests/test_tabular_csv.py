import importlib
from pathlib import Path
import unittest


tabular = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing"
)
SAMPLES = Path(__file__).parent / "testFile"


class CsvConversionTests(unittest.TestCase):
    def test_detected_encoding_is_reported_and_warning_stays_outside_body(self):
        result = tabular.convert_file(
            SAMPLES / "csv_explicit_gb18030.csv", delimiter=";", header_record=3,
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.encoding, "gb18030")
        self.assertEqual(result.tables[0].rows[1].cells[0].raw_value, "上海")
        detected = [warning for warning in result.warnings if "Encoding automatically" in warning]
        self.assertEqual(len(detected), 1)
        self.assertNotIn(detected[0], result.markdown)

    def test_strict_decoding_rejects_truncated_unknown_and_explicit_wrong_encoding(self):
        for filename, encoding in (
            ("csv_truncated_utf16.csv", None), ("csv_undecodable.csv", None),
            ("csv_explicit_gb18030.csv", "utf-8"),
            ("csv_travel_utf16_le_bom.csv", "utf-8"),
        ):
            with self.subTest(filename=filename, encoding=encoding):
                result = tabular.convert_file(SAMPLES / filename, encoding=encoding)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.tables, [])
                self.assertIn("Decoding failed", result.error)
                self.assertEqual(result.warnings, [])
        for encoding in (None, "utf-8"):
            result = tabular.convert_file(SAMPLES / "csv_bom_only.csv", encoding=encoding)
            self.assertFalse(result.success)
            self.assertIn("header", result.error)

    def test_file_read_and_option_errors_are_explicit_results(self):
        path = SAMPLES / "csv_travel.csv"
        for arguments, diagnostic in (
            ({"path": SAMPLES / "csv_missing.csv"}, "Could not read"),
            ({"path": SAMPLES}, "format"),
            ({"path": SAMPLES, "format": "csv"}, "Could not read"),
            ({"path": None}, "path"), ({"path": 12}, "path"),
            ({"path": path, "format": "xlsx"}, "XLSX reading failed"),
            ({"path": path, "source": 12}, "source"),
            ({"path": path, "mode": "full"}, "mode"),
            ({"path": path, "header_record": 0}, "header_record"),
        ):
            with self.subTest(arguments=arguments):
                result = tabular.convert_file(**arguments)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.tables, [])
                self.assertIn(diagnostic, result.error)

    def test_teaching_travel_evidence_scopes_keep_city_pairs_and_context(self):
        path = SAMPLES / "csv_travel.csv"
        context = tabular.TableContext(
            name="员工国内差旅标准", version="2026示例版", applicability="普通员工，国内出差",
        )
        result = tabular.convert_file(path, context=context)
        self.assertTrue(result.success, result.error)
        beijing, shanghai, hangzhou = result.tables[0].rows
        self.assertEqual([cell.raw_value for cell in beijing.cells], ["北京", "500", "100"])
        self.assertEqual([cell.raw_value for cell in shanghai.cells], ["上海", "450", "100"])
        self.assertEqual([cell.raw_value for cell in hangzhou.cells], ["杭州", "400", "80"])
        beijing_evidence = beijing.text
        self.assertIn("住宿上限（元／晚）：500", beijing_evidence)
        self.assertNotIn("上海", beijing_evidence)
        self.assertNotIn("450", beijing_evidence)
        two_rows_evidence = beijing.text + "\n\n" + shanghai.text
        self.assertIn("城市：上海\n住宿上限（元／晚）：450", two_rows_evidence)
        self.assertNotIn("杭州", two_rows_evidence)
        self.assertIn("| 北京 | 500 | 100 |\n| 上海 | 450 | 100 |", result.markdown)
        for evidence in (beijing_evidence, result.markdown, two_rows_evidence):
            for expected in ("员工国内差旅标准", "2026示例版", "普通员工，国内出差"):
                self.assertIn(expected, evidence)
        self.assertEqual(int(beijing.cells[1].raw_value) - int(shanghai.cells[1].raw_value), 50)
        self.assertEqual(beijing.source.row_start, 2)
        self.assertEqual(shanghai.source.row_start, 3)

    def test_bom_encoding_and_explicit_utf8_preserve_first_header(self):
        for suffix, used_encoding, explicit in (
            ("utf8_bom", "utf-8-sig", None),
            ("utf16_le_bom", "utf-16", None), ("utf16_be_bom", "utf-16", None),
            ("utf32_le_bom", "utf-32", None), ("utf32_be_bom", "utf-32", None),
            ("utf8_bom", "utf-8", "utf-8"),
        ):
            with self.subTest(suffix=suffix, explicit=explicit):
                result = tabular.convert_file(SAMPLES / f"csv_travel_{suffix}.csv", encoding=explicit)
                self.assertTrue(result.success, result.error)
                self.assertEqual(result.encoding, used_encoding)
                self.assertEqual(result.tables[0].columns[0].name, "城市")
                self.assertEqual(result.tables[0].rows[0].cells[0].raw_value, "北京")
                self.assertFalse(any("Encoding automatically" in warning for warning in result.warnings))

    def test_bad_quotes_fail_without_exposing_preceding_valid_rows(self):
        for filename in ("csv_quote_unclosed.csv", "csv_quote_trailing.csv", "csv_quote_bare.csv"):
            with self.subTest(filename=filename):
                result = tabular.convert_file(SAMPLES / filename)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.tables, [])
                self.assertIn("record 3", result.error)
                self.assertIn("physical lines 3", result.error)
                self.assertIn("quot", result.error)

    def test_absent_header_data_or_selected_header_fails_clearly(self):
        cases = (
            ("csv_empty.csv", None, "header"),
            ("csv_blank.csv", None, "header"),
            ("csv_header_only.csv", None, "data"),
            ("csv_no_data.csv", None, "data"),
            ("csv_quoted.csv", 1, "header record 1"),
            ("csv_travel.csv", 99, "header record 99"),
        )
        for filename, header_record, diagnostic in cases:
            with self.subTest(filename=filename, header_record=header_record):
                result = tabular.convert_file(SAMPLES / filename, header_record=header_record)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.tables, [])
                self.assertIn(diagnostic, result.error)

    def test_empty_or_duplicate_column_names_fail_with_header_position(self):
        for filename, diagnostic in (
            ("csv_header_empty.csv", "empty"), ("csv_header_duplicate.csv", "duplicate"),
        ):
            with self.subTest(filename=filename):
                result = tabular.convert_file(SAMPLES / filename)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.tables, [])
                self.assertIn("header", result.error)
                self.assertIn("record 1", result.error)
                self.assertIn(diagnostic, result.error)

    def test_inconsistent_row_width_fails_entire_conversion_at_original_record(self):
        for filename in ("csv_width_short.csv", "csv_width_long.csv"):
            for mode in ("table", "rows"):
                with self.subTest(filename=filename, mode=mode):
                    result = tabular.convert_bytes(
                        (SAMPLES / filename).read_bytes(), format="csv", source=filename, mode=mode,
                    )
                    self.assertFalse(result.success)
                    self.assertIsNone(result.markdown)
                    self.assertEqual(result.tables, [])
                    self.assertEqual(result.encoding, "utf-8")
                    self.assertIn("record 3", result.error)
                    self.assertIn("width", result.error)

    def test_invalid_public_options_fail_without_body_or_tables(self):
        data = (SAMPLES / "csv_travel.csv").read_bytes()
        defaults = dict(data=data, format="csv", source="travel.csv")
        cases = (
            ("data", "decoded"), ("format", None), ("format", 1),
            ("format", ""), ("format", "xlsx"), ("format", "txt"),
            ("source", None), ("source", 1), ("source", "  "),
            ("mode", "full"), ("mode", None), ("mode", []),
            ("encoding", 1), ("encoding", ""), ("encoding", "invalid-codec"),
            ("delimiter", None), ("delimiter", ""), ("delimiter", "||"),
            ("delimiter", '"'), ("delimiter", "\n"), ("delimiter", "\r"),
            ("header_record", 0), ("header_record", -1), ("header_record", True),
            ("header_record", 1.5), ("header_record", "1"),
            ("context", {}), ("context", tabular.TableContext(name=123)),
            ("context", tabular.TableContext(version="  ")),
            ("context", tabular.TableContext(applicability=[])),
            ("context", tabular.TableContext(notes=False)),
        )
        for name, value in cases:
            with self.subTest(name=name, value=value):
                result = tabular.convert_bytes(**(defaults | {name: value}))
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.tables, [])
                self.assertTrue(result.error)

    def test_markdown_escapes_cells_without_changing_structured_values(self):
        result = tabular.convert_file(SAMPLES / "csv_markdown.csv")

        self.assertTrue(result.success, result.error)
        self.assertIn("| 列\\|名 | 路径 | 说明 |", result.markdown)
        self.assertIn("| 值\\|A | C:\\\\临时\\\\file | 第一行<br>第二行&lt;br&gt;&amp; |", result.markdown)
        row = result.tables[0].rows[0]
        self.assertEqual([cell.raw_value for cell in row.cells], ["值|A", "C:\\临时\\file", "第一行\r\n第二行<br>&"])
        self.assertEqual(row.cells[2].text, "第一行\r\n第二行<br>&")
        self.assertIn("列\\|名：值\\|A", row.text)
        self.assertIn("说明：第一行<br>第二行&lt;br&gt;&amp;", row.text)

    def test_unknown_context_stays_unknown_with_separate_warnings(self):
        data = (SAMPLES / "csv_travel.csv").read_bytes()
        result = tabular.convert_bytes(data, format="csv", source="2026-普通员工.csv", mode="rows")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.tables[0].context, tabular.TableContext())
        self.assertEqual(len(result.warnings), 3)
        for field in ("name", "version", "applicability"):
            self.assertTrue(any(field in warning for warning in result.warnings))
        for row in result.tables[0].rows:
            self.assertIn("表名：未知\n版本：未知\n适用条件：未知", row.text)
            self.assertNotIn("备注：", row.text)
        for warning in result.warnings:
            self.assertNotIn(warning, result.markdown)

        known = tabular.convert_bytes(
            data, format="csv", source="travel.csv",
            context=tabular.TableContext(name="保留原名", version="另一版本", applicability="管理人员"),
        )
        self.assertEqual(known.warnings, [])
        self.assertIn("版本：另一版本", known.tables[0].rows[0].text)
        self.assertIn("适用条件：管理人员", known.tables[0].rows[0].text)

    def test_explicit_encoding_delimiter_and_header_use_original_record_number(self):
        path = SAMPLES / "csv_explicit_gb18030.csv"
        result = tabular.convert_file(path, encoding="gb18030", delimiter=";", header_record=3)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.encoding, "gb18030")
        self.assertEqual([column.name for column in result.tables[0].columns], ["城市", "住宿上限（元／晚）", "餐补（元／天）"])
        self.assertEqual([cell.raw_value for cell in result.tables[0].rows[0].cells], ["北京", "500", "100"])
        self.assertEqual(result.tables[0].source.row_start, 3)
        self.assertEqual(result.tables[0].rows[0].source.row_start, 4)
        self.assertNotIn("导出说明", result.markdown)
        self.assertFalse(any("Encoding automatically" in warning for warning in result.warnings))
        self.assertEqual(result, tabular.convert_bytes(
            path.read_bytes(), format=".CSV", source=str(path), encoding="gb18030",
            delimiter=";", header_record=3,
        ))

    def test_quoted_fields_remain_text_and_keep_original_record_and_physical_lines(self):
        result = tabular.convert_bytes(
            (SAMPLES / "csv_quoted.csv").read_bytes(), format="csv", source="quoted.csv",
            mode="rows",
        )

        self.assertTrue(result.success, result.error)
        table = result.tables[0]
        self.assertEqual([column.name for column in table.columns], ["编号", "说明", "金额", "备注"])
        self.assertEqual(len(table.rows), 2)
        first, last = table.rows
        self.assertEqual(
            [cell.raw_value for cell in first.cells],
            ["00123", '含逗号,与"引号"\r\n第二行', "=1+2", ""],
        )
        self.assertEqual([cell.raw_value for cell in last.cells], ["00002", "普通文本", "0", "尾"])
        self.assertEqual(
            first.source,
            tabular.SourcePosition(result.source, 3, 3, 1, 4, 3, 4),
        )
        self.assertEqual(last.source, tabular.SourcePosition(result.source, 6, 6, 1, 4, 7, 7))
        self.assertEqual(table.source, tabular.SourcePosition(result.source, 2, 6, 1, 4, 2, 7))
        self.assertEqual(table.columns[1].source, tabular.SourcePosition(result.source, 2, 2, 2, 2, 2, 2))
        self.assertEqual(first.cells[1].source, tabular.SourcePosition(result.source, 3, 3, 2, 2, 3, 4))
        self.assertIn("quoted.csv", first.text)
        self.assertIn("记录 3", first.text)
        self.assertIn("物理行 3–4", first.text)

    def test_rows_carry_complete_columns_and_caller_context_independently(self):
        context = tabular.TableContext(
            name="员工国内差旅标准", version="2026示例版",
            applicability="普通员工，国内出差", notes="教学数据，不是实际报销政策",
        )
        path = SAMPLES / "csv_travel.csv"
        rows_result = tabular.convert_bytes(
            path.read_bytes(), format="csv", source="travel.csv", mode="rows", context=context,
        )
        table_result = tabular.convert_file(path, source="travel.csv", context=context)

        self.assertTrue(rows_result.success, rows_result.error)
        self.assertTrue(table_result.success, table_result.error)
        beijing = rows_result.tables[0].rows[0]
        self.assertEqual(beijing.context, context)
        self.assertEqual(
            [column.name for column in beijing.columns],
            ["城市", "住宿上限（元／晚）", "餐补（元／天）"],
        )
        self.assertIn("城市：北京", beijing.text)
        self.assertIn("住宿上限（元／晚）：500", beijing.text)
        self.assertIn("餐补（元／天）：100", beijing.text)
        for value in (context.name, context.version, context.applicability, context.notes):
            self.assertIn(value, beijing.text)
            self.assertIn(value, table_result.markdown)
        self.assertNotIn("上海", beijing.text)
        self.assertNotIn("450", beijing.text)
        self.assertIn("| 上海 | 450 | 100 |", table_result.markdown)
        self.assertEqual(rows_result.tables[0].rows, table_result.tables[0].rows)
        self.assertNotIn("| ---", rows_result.markdown)

    def test_file_suffix_and_explicit_format_match_bytes_entry(self):
        path = SAMPLES / "seaborn_iris.csv"
        expected = tabular.convert_bytes(path.read_bytes(), format="csv", source="upload.csv")

        inferred = tabular.convert_file(path, source="upload.csv")
        overridden = tabular.convert_file(path, format=".CSV", source="upload.csv")

        self.assertEqual(inferred, expected)
        self.assertEqual(overridden, expected)
        self.assertEqual(tabular.convert_file(path).source.location, str(path))

    def test_real_csv_bytes_keep_column_value_correspondence_in_default_table(self):
        result = tabular.convert_bytes(
            (SAMPLES / "seaborn_iris.csv").read_bytes(),
            format="csv", source="iris.csv",
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source, tabular.Source("iris.csv", "csv"))
        self.assertEqual(result.encoding, "utf-8")
        table = result.tables[0]
        self.assertEqual(len(table.rows), 150)
        self.assertEqual(
            [column.name for column in table.columns],
            ["sepal_length", "sepal_width", "petal_length", "petal_width", "species"],
        )
        self.assertEqual(
            [cell.raw_value for cell in table.rows[0].cells],
            ["5.1", "3.5", "1.4", "0.2", "setosa"],
        )
        self.assertIn("| 5.1 | 3.5 | 1.4 | 0.2 | setosa |", result.markdown)


if __name__ == "__main__":
    unittest.main()
