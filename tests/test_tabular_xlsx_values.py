from datetime import datetime, time
import importlib
from pathlib import Path
import unittest


tabular = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing"
)
SAMPLE = Path(__file__).parent / "testFile" / "xlsx_values.xlsx"
CONTEXT = tabular.TableContext("值显示验收", "固定示例", "测试")


class XlsxValuesTests(unittest.TestCase):
    def test_common_decimal_rounding_does_not_expose_binary_float_ties(self):
        result = tabular.convert_file(SAMPLE, context=CONTEXT)
        self.assertTrue(result.success, result.error)
        cells = {row.cells[1].source.coordinate: row.cells[1] for row in result.tables[0].rows}
        self.assertEqual(cells["B30"].raw_value, 2.675)
        self.assertEqual(cells["B30"].text, "2.68")
        self.assertEqual(cells["B31"].text, "3")
        self.assertEqual(cells["B32"].text, "-3")

    def test_unsupported_formats_keep_values_and_located_warnings_outside_body(self):
        for mode in ("table", "rows"):
            result = tabular.convert_file(SAMPLE, source="values.xlsx", context=CONTEXT, mode=mode)
            self.assertTrue(result.success, result.error)
            cells = {row.cells[1].source.coordinate: row.cells[1] for row in result.tables[0].rows}
            self.assertEqual((cells["B21"].raw_value, cells["B21"].text), (12.5, "12.5"))
            self.assertEqual(cells["B24"].cached_value, 12.5)
            self.assertEqual(cells["B24"].raw_value, "=25/2")
            self.assertIn("文件缓存：12.5；非实时", cells["B24"].text)
            self.assertEqual(cells["B28"].raw_value, datetime(2026, 10, 27))
            self.assertEqual(cells["B28"].data_type, "d")
            self.assertEqual(cells["B28"].text, "2026-10-27 00:00:00")
            self.assertEqual((cells["B29"].raw_value, cells["B29"].text), (12000, "12000"))
            for coordinate, number_format in (
                ("B21", '0.0" widgets"'), ("B24", '0.0" widgets"'),
                ("B28", 'yyyy"年"m"月"d"日"'), ("B29", "#,##0,"),
            ):
                with self.subTest(mode=mode, coordinate=coordinate):
                    self.assertEqual(cells[coordinate].number_format, number_format)
                    self.assertTrue(any(f"值!{coordinate}:" in warning
                                        and "unsupported number format" in warning
                                        and number_format in warning for warning in result.warnings))
            self.assertEqual(len(result.warnings), 5)
            for warning in result.warnings:
                self.assertNotIn(warning, result.markdown)
                for row in result.tables[0].rows:
                    self.assertNotIn(warning, row.text)
            self.assertEqual(result, tabular.convert_bytes(
                SAMPLE.read_bytes(), source="values.xlsx", format="xlsx", context=CONTEXT, mode=mode))

    def test_dates_and_times_use_iso_text_including_saved_formula_dates(self):
        for mode in ("table", "rows"):
            result = tabular.convert_bytes(SAMPLE.read_bytes(), format="xlsx", source="values.xlsx",
                                           context=CONTEXT, mode=mode)
            self.assertTrue(result.success, result.error)
            cells = {row.cells[1].source.coordinate: row.cells[1] for row in result.tables[0].rows}
            for coordinate, raw, number_format, text in (
                ("B16", datetime(2026, 10, 27), "yyyy-mm-dd", "2026-10-27"),
                ("B17", datetime(2026, 10, 27, 13, 4, 5),
                 "yyyy-mm-dd h:mm:ss", "2026-10-27T13:04:05"),
                ("B18", time(13, 4, 5), "h:mm:ss", "13:04:05"),
            ):
                with self.subTest(mode=mode, coordinate=coordinate):
                    cell = cells[coordinate]
                    self.assertEqual((cell.raw_value, cell.data_type, cell.number_format),
                                     (raw, "d", number_format))
                    self.assertEqual(cell.text, text)
                    self.assertIn(text, result.markdown)
            cached = cells["B20"]
            self.assertEqual(cached.raw_value, "=DATE(2026,10,27)")
            self.assertEqual(cached.number_format, "yyyy-mm-dd")
            self.assertEqual(cached.cached_value, datetime(2026, 10, 27))
            self.assertEqual(cached.cache_status, "cached")
            self.assertIn("文件缓存：2026-10-27；非实时", cached.text)
            self.assertIn(cached.text, result.markdown)

    def test_common_numbers_percentages_and_money_keep_raw_metadata_and_display(self):
        expected = (
            (9, 1234, "#,##0", "1,234"),
            (10, -1234.5, "#,##0.00", "-1,234.50"),
            (11, 12.5, "0.00", "12.50"),
            (12, 0.2, "0%", "20%"),
            (13, 0.125, "0.00%", "12.50%"),
            (14, 1234.5, '"¥"#,##0.00', "¥1,234.50"),
            (15, -12.5, "$0.00", "-$12.50"),
        )
        for mode in ("table", "rows"):
            result = tabular.convert_file(SAMPLE, context=CONTEXT, mode=mode)
            self.assertTrue(result.success, result.error)
            by_coordinate = {row.cells[1].source.coordinate: row.cells[1]
                             for row in result.tables[0].rows}
            for row, raw, number_format, text in expected:
                with self.subTest(mode=mode, row=row):
                    cell = by_coordinate[f"B{row}"]
                    self.assertEqual(cell.raw_value, raw)
                    self.assertEqual(cell.number_format, number_format)
                    self.assertEqual(cell.data_type, "n")
                    self.assertIsNone(cell.cache_status)
                    self.assertEqual(cell.text, text)
                    self.assertIn(text, result.markdown)
            for coordinate, raw, text in (("B19", 0.2, "20%"), ("B25", 1250, "¥1,250.00")):
                cell = by_coordinate[coordinate]
                self.assertEqual(cell.cached_value, raw)
                self.assertIn(f"文件缓存：{text}", cell.text)
                self.assertIn(cell.text, result.markdown)
            for coordinate, raw, kind, text in (
                ("B6", None, "n", ""), ("B7", 0, "n", "0"),
                ("B8", "#VALUE!", "e", "错误：#VALUE!"),
                ("B22", False, "b", "False"), ("B23", "00123", "s", "00123"),
            ):
                cell = by_coordinate[coordinate]
                self.assertEqual((cell.raw_value, cell.data_type, cell.text), (raw, kind, text))
                self.assertIs(type(cell.raw_value), type(raw))
            self.assertEqual(by_coordinate["B26"].cached_value, "00123")
            self.assertIn("文件缓存：00123", by_coordinate["B26"].text)
            self.assertIs(by_coordinate["B27"].cached_value, False)
            self.assertIn("文件缓存：False", by_coordinate["B27"].text)

    def test_formula_caches_preserve_zero_unknown_number_and_error_in_both_modes(self):
        for mode in ("table", "rows"):
            with self.subTest(mode=mode):
                result = tabular.convert_bytes(SAMPLE.read_bytes(), format="xlsx",
                                               source="values.xlsx", mode=mode, context=CONTEXT)
                self.assertTrue(result.success, result.error)
                cells = [row.cells[1] for row in result.tables[0].rows[:4]]
                for cell, formula, cached in zip(cells, ("=1-1", "=1+1", "=40+2", "=1/0"),
                                                 (0, None, 42, "#DIV/0!")):
                    self.assertEqual(cell.raw_value, formula)
                    self.assertEqual(cell.formula, formula)
                    self.assertEqual(cell.cached_value, cached)
                    self.assertEqual(cell.data_type, "f")
                    self.assertIn(formula, cell.text)
                self.assertEqual([cell.cache_status for cell in cells],
                                 ["cached", "unknown", "cached", "cached"])
                self.assertIn("文件缓存：0", cells[0].text)
                self.assertIn("非实时", cells[0].text)
                self.assertIn("结果未知", cells[1].text)
                self.assertIn("文件缓存：42", cells[2].text)
                self.assertIn("错误：#DIV/0!", cells[3].text)
                self.assertEqual(cells[0].source.coordinate, "B2")
                self.assertEqual(cells[0].source.sheet, "值")
                self.assertEqual(cells[0].source.source.location, "values.xlsx")
                self.assertTrue(any("B3" in warning and "formula" in warning
                                    for warning in result.warnings))
                self.assertFalse(any("B2:" in warning for warning in result.warnings))
                for cell in cells:
                    self.assertIn(cell.text, result.markdown)
                for warning in result.warnings:
                    self.assertNotIn(warning, result.markdown)
