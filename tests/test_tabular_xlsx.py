import importlib
from pathlib import Path
import unittest


tabular = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing"
)
SAMPLES = Path(__file__).parent / "testFile"


class XlsxConversionTests(unittest.TestCase):
    def test_teaching_travel_row_and_table_evidence_keep_units_and_business_context(self):
        context = tabular.TableContext("员工国内差旅标准", "2026示例版", "普通员工，国内出差")
        path = SAMPLES / "xlsx_travel.xlsx"
        table_result = tabular.convert_file(path, context=context)
        rows_result = tabular.convert_file(path, context=context, mode="rows")

        self.assertTrue(table_result.success, table_result.error)
        self.assertEqual(table_result.tables, rows_result.tables)
        beijing, shanghai, hangzhou = rows_result.tables[0].rows
        self.assertIn("住宿上限（元／晚）：500", beijing.text)
        self.assertIn("餐补（元／天）：100", beijing.text)
        self.assertNotIn("上海", beijing.text)
        self.assertNotIn("450", beijing.text)
        combined = beijing.text + "\n\n" + shanghai.text
        self.assertIn("住宿上限（元／晚）：450", combined)
        self.assertNotIn("杭州", combined)
        for evidence in (beijing.text, combined, table_result.markdown):
            for text in ("员工国内差旅标准", "2026示例版", "普通员工，国内出差"):
                self.assertIn(text, evidence)
        self.assertEqual(beijing.cells[1].raw_value - shanghai.cells[1].raw_value, 50)
        self.assertEqual(hangzhou.cells[1].raw_value, 400)
        self.assertEqual(beijing.cells[1].source.coordinate, "B2")
        self.assertEqual(table_result.warnings, [])

    def test_file_errors_and_explicit_format_use_the_same_xlsx_contract(self):
        path = SAMPLES / "xlsx_travel.xlsx"
        result = tabular.convert_file(path, source="upload.xlsx", format=".XLSX")
        self.assertEqual(result, tabular.convert_bytes(path.read_bytes(), format="xlsx", source="upload.xlsx"))
        for result in (
            tabular.convert_file(SAMPLES / "xlsx_missing.xlsx"),
            tabular.convert_file(SAMPLES, format="xlsx"),
            tabular.convert_bytes(b"", format="xlsx", source="empty.xlsx"),
            tabular.convert_bytes("not bytes", format="xlsx", source="bad.xlsx"),
            tabular.convert_bytes(path.read_bytes(), format="xlsx", source=""),
        ):
            self.assertFalse(result.success)
            self.assertIsNone(result.markdown)
            self.assertEqual(result.tables, [])
            self.assertTrue(result.error)

    def test_explicit_range_limits_data_and_default_header_skips_empty_rows_in_range(self):
        result = tabular.convert_file(SAMPLES / "xlsx_sheets.xlsx", xlsx=tabular.XlsxOptions((
            tabular.XlsxSheetOptions("第一表", "$B$1:$C$3"),)))

        self.assertTrue(result.success, result.error)
        table = result.tables[0]
        self.assertEqual(table.source.coordinate, "B2:C3")
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(table.columns[0].source.coordinate, "B2")
        self.assertEqual([cell.raw_value for cell in table.rows[0].cells], ["北京", 500])
        self.assertNotIn("上海", result.markdown)

    def test_merges_and_multilevel_headers_are_explicitly_unsupported_for_now(self):
        for path, options, diagnostic in (
            ("xlsx_merged_unsupported.xlsx", None, "A2:A3"),
            ("xlsx_merged_unsupported.xlsx", tabular.XlsxOptions((
                tabular.XlsxSheetOptions("合并", "A3:B3"),)), "A2:A3"),
            ("xlsx_travel.xlsx", tabular.XlsxOptions((
                tabular.XlsxSheetOptions("差旅", header_rows=(1, 2)),)), "multi-level"),
        ):
            with self.subTest(path=path, options=options):
                result = tabular.convert_file(SAMPLES / path, xlsx=options)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.tables, [])
                self.assertIn(diagnostic, result.error)

    def test_invalid_xlsx_options_are_rejected_at_public_entries(self):
        invalid = (
            {}, tabular.XlsxOptions(()), tabular.XlsxOptions([]), tabular.XlsxOptions(("差旅",)),
            tabular.XlsxOptions((tabular.XlsxSheetOptions(""),)),
            tabular.XlsxOptions((tabular.XlsxSheetOptions("差旅"), tabular.XlsxSheetOptions("差旅"))),
        )
        sheet_options = (
            {"cell_range": "A:C"}, {"cell_range": "1:3"}, {"cell_range": "C3:A1"},
            {"cell_range": "A0:B2"}, {"cell_range": "A1:XFE2"}, {"cell_range": "A1:B1048577"},
            {"cell_range": "差旅!A1:C4"}, {"cell_range": "A1:B2,C3:D4"},
            {"cell_range": 123}, {"cell_range": ""},
            {"header_rows": ()}, {"header_rows": [1]}, {"header_rows": (True,)},
            {"header_rows": (0,)}, {"header_rows": (1.5,)}, {"header_rows": (3, 2)},
            {"header_rows": (1, 3)}, {"header_rows": (1048577,)},
            {"cell_range": "B2:C4", "header_rows": (1,)},
            {"cell_range": "B2:C4", "header_rows": (5,)},
            {"context": {}}, {"context": tabular.TableContext(version=" ")},
        )
        invalid += tuple(tabular.XlsxOptions((tabular.XlsxSheetOptions("差旅", **kwargs),))
                         for kwargs in sheet_options)
        path = SAMPLES / "xlsx_travel.xlsx"
        for options in invalid:
            with self.subTest(options=options):
                for result in (
                    tabular.convert_file(path, xlsx=options),
                    tabular.convert_bytes(path.read_bytes(), format="xlsx", source="input.xlsx", xlsx=options),
                ):
                    self.assertFalse(result.success)
                    self.assertIsNone(result.markdown)
                    self.assertEqual(result.tables, [])
                    self.assertTrue(result.error)

    def test_invalid_selected_tables_and_corrupt_workbooks_fail_atomically(self):
        cases = (
            ("xlsx_empty.xlsx", None, "no nonempty visible"),
            ("xlsx_header_only.xlsx", None, "no data"),
            ("xlsx_duplicate_header.xlsx", None, "duplicate"),
            ("xlsx_blank_header.xlsx", None, "empty column"),
            ("xlsx_atomic_failure.xlsx", None, "无数据"),
            ("xlsx_corrupt.xlsx", None, "XLSX"),
            ("xlsx_sheets.xlsx", tabular.XlsxOptions((tabular.XlsxSheetOptions("不存在"),)), "不存在"),
            ("xlsx_sheets.xlsx", tabular.XlsxOptions((tabular.XlsxSheetOptions("空表"),)), "空表"),
            ("xlsx_sheets.xlsx", tabular.XlsxOptions((tabular.XlsxSheetOptions("第一表", "B2:C2"),)), "no data"),
            ("xlsx_sheets.xlsx", tabular.XlsxOptions((tabular.XlsxSheetOptions("第一表", "B2:C5", (4,)),)), "header"),
        )
        for filename, options, diagnostic in cases:
            with self.subTest(filename=filename, options=options):
                result = tabular.convert_file(SAMPLES / filename, xlsx=options)
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.tables, [])
                self.assertIn(diagnostic, result.error)

    def test_plain_values_keep_types_formats_and_formula_is_unknown_not_calculated(self):
        result = tabular.convert_file(SAMPLES / "xlsx_plain_values.xlsx")

        self.assertTrue(result.success, result.error)
        cells = result.tables[0].rows[0].cells
        self.assertEqual([cell.raw_value for cell in cells[:6]], [None, 0, False, "00123", 12.5, "=B2+1"])
        self.assertIsNone(cells[0].raw_value)
        self.assertIs(type(cells[1].raw_value), int)
        self.assertIs(type(cells[2].raw_value), bool)
        self.assertEqual([cell.data_type for cell in cells[:6]], ["n", "n", "b", "s", "n", "f"])
        self.assertEqual(cells[4].number_format, "0.00")
        self.assertEqual(cells[0].text, "")
        self.assertEqual(cells[1].text, "0")
        self.assertEqual(cells[5].formula, "=B2+1")
        self.assertIsNone(cells[5].cached_value)
        self.assertEqual(cells[5].cache_status, "unknown")
        self.assertIn("结果未知", cells[5].text)
        self.assertIn("=B2+1", cells[5].text)
        self.assertTrue(any("F2" in warning and "formula" in warning for warning in result.warnings))
        self.assertIn("特殊\\|列", result.markdown)
        self.assertIn("A\\|B\\\\路径<br>第二行&lt;br&gt;&amp;", result.markdown)
        self.assertEqual(cells[6].raw_value, "A|B\\路径\n第二行<br>&")
        self.assertIsNone(cells[1].source.merged_anchor)
        self.assertIsNone(cells[1].source.merged_range)

    def test_unknown_context_is_not_inferred_from_sheet_or_filename(self):
        result = tabular.convert_file(SAMPLES / "xlsx_sheets.xlsx", source="2026-普通员工.xlsx")

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(result.warnings), 6)
        for table in result.tables:
            self.assertEqual(table.context, tabular.TableContext())
            self.assertIn("表名：未知\n版本：未知\n适用条件：未知", table.rows[0].text)
            for field in ("name", "version", "applicability"):
                self.assertTrue(any(table.source.sheet in warning and field in warning
                                    for warning in result.warnings))
        for warning in result.warnings:
            self.assertNotIn(warning, result.markdown)

    def test_explicit_sheet_range_header_and_context_work_in_both_representations(self):
        context = tabular.TableContext("员工国内差旅标准", "2026示例版", "普通员工，国内出差")
        hidden_context = tabular.TableContext("隐藏标准", "2025版", "管理人员", "旧版")
        options = tabular.XlsxOptions(sheets=(
            tabular.XlsxSheetOptions("隐藏", context=hidden_context),
            tabular.XlsxSheetOptions("第一表", cell_range="B1:C5", header_rows=(2,), context=context),
        ))
        path = SAMPLES / "xlsx_sheets.xlsx"
        result = tabular.convert_file(path, xlsx=options, source="upload.xlsx")
        rows = tabular.convert_bytes(path.read_bytes(), format=".XLSX", source="upload.xlsx",
                                     xlsx=options, mode="rows")

        self.assertTrue(result.success, result.error)
        self.assertEqual([table.source.sheet for table in result.tables], ["第一表", "隐藏"])
        self.assertEqual(result.tables, rows.tables)
        self.assertEqual(result.warnings, [])
        beijing, shanghai = rows.tables[0].rows
        self.assertEqual(beijing.context, context)
        self.assertEqual(rows.tables[1].rows[0].context, hidden_context)
        self.assertIn("城市：北京\n金额：500", beijing.text)
        self.assertNotIn("上海", beijing.text)
        self.assertNotIn("450", beijing.text)
        self.assertIn("城市：上海\n金额：450", shanghai.text)
        self.assertIn("版本：2026示例版", beijing.text)
        self.assertIn("适用条件：管理人员", rows.tables[1].rows[0].text)
        self.assertIn("| 北京 | 500 |\n| 上海 | 450 |", result.markdown)
        self.assertNotIn("| ---", rows.markdown)
        self.assertEqual(result, tabular.convert_bytes(path.read_bytes(), format="xlsx",
                                                      source="upload.xlsx", xlsx=options))

    def test_defaults_read_nonempty_visible_sheets_in_workbook_order_with_original_positions(self):
        result = tabular.convert_file(SAMPLES / "xlsx_sheets.xlsx")

        self.assertTrue(result.success, result.error)
        self.assertEqual([table.source.sheet for table in result.tables], ["第一表", "第二表"])
        table = result.tables[0]
        self.assertEqual([row.source.row_start for row in table.rows], [3, 5])
        self.assertEqual(table.source.coordinate, "B2:C5")
        self.assertEqual(table.columns[1].source.coordinate, "C2")
        self.assertEqual(table.rows[1].cells[1].source.coordinate, "C5")
        self.assertEqual(table.rows[1].cells[1].source.column_start, 3)
        self.assertEqual(table.rows[1].source.sheet, "第一表")
        self.assertEqual(table.rows[1].cells[1].source.source.location, str(SAMPLES / "xlsx_sheets.xlsx"))
        self.assertIn("工作表：第一表", table.rows[0].text)
        self.assertIn("B3:C3", table.rows[0].text)
        self.assertNotIn("隐藏", result.markdown)
        self.assertNotIn("物理行", result.markdown)

    def test_real_rectangular_workbook_keeps_city_column_pairs(self):
        result = tabular.convert_bytes(
            (SAMPLES / "xlsx_travel.xlsx").read_bytes(), format="xlsx", source="travel.xlsx",
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source, tabular.Source("travel.xlsx", "xlsx"))
        self.assertIsNone(result.encoding)
        table = result.tables[0]
        self.assertEqual([column.name for column in table.columns],
                         ["城市", "住宿上限（元／晚）", "餐补（元／天）"])
        self.assertEqual([[cell.raw_value for cell in row.cells] for row in table.rows],
                         [["北京", 500, 100], ["上海", 450, 100], ["杭州", 400, 80]])
        self.assertIn("| 北京 | 500 | 100 |", result.markdown)
        self.assertIn("| 上海 | 450 | 100 |", result.markdown)
