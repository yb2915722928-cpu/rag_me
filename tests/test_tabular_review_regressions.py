from datetime import date
import importlib
from pathlib import Path
import unittest


tabular = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing"
)
SAMPLES = Path(__file__).parent / "testFile"
CONTEXT = tabular.TableContext("评审验收", "固定示例", "测试")


class TabularReviewRegressions(unittest.TestCase):
    def test_iso_date_preserves_date_type_without_unsupported_format_warning(self):
        for mode in ("table", "rows"):
            for result in self.conversions("xlsx_review_iso_date.xlsx", mode):
                with self.subTest(mode=mode):
                    self.assertTrue(result.success, result.error)
                    cell = result.tables[0].rows[0].cells[1]
                    self.assertIs(type(cell.raw_value), date)
                    self.assertEqual(cell.raw_value, date(2026, 10, 27))
                    self.assertEqual((cell.data_type, cell.number_format, cell.text),
                                     ("d", "yyyy-mm-dd", "2026-10-27"))
                    self.assertIn("2026-10-27", result.markdown)
                    self.assertEqual(result.warnings, [])

    def test_corrupt_shared_string_fails_atomically_at_public_entries(self):
        for mode in ("table", "rows"):
            for entry in ("file", "bytes"):
                with self.subTest(mode=mode, entry=entry):
                    path = SAMPLES / "xlsx_review_corrupt_shared_string.xlsx"
                    if entry == "file":
                        result = tabular.convert_file(path, mode=mode, context=CONTEXT)
                    else:
                        result = tabular.convert_bytes(path.read_bytes(), format="xlsx", source=str(path),
                                                       mode=mode, context=CONTEXT)
                    self.assertFalse(result.success)
                    self.assertIsNone(result.markdown)
                    self.assertEqual(result.tables, [])
                    self.assertIn("XLSX reading failed:", result.error)
                    self.assertIn("list index out of range", result.error)

    def test_whitespace_merged_anchor_does_not_create_data_rows(self):
        for mode in ("table", "rows"):
            for result in self.conversions("xlsx_review_blank_merge.xlsx", mode):
                with self.subTest(mode=mode, sample="with data"):
                    self.assertTrue(result.success, result.error)
                    rows = result.tables[0].rows
                    self.assertEqual([row.source.coordinate for row in rows], ["A4:B4"])
                    self.assertEqual([cell.raw_value for cell in rows[0].cells], ["有效", 0])
                    self.assertEqual([cell.text for cell in rows[0].cells], ["有效", "0"])
                    self.assertEqual(rows[0].cells[1].source.coordinate, "B4")
                    self.assertNotIn("合并值", result.markdown)
                    self.assertNotIn("合并覆盖", result.markdown)
            options = tabular.XlsxOptions((tabular.XlsxSheetOptions("Sheet", "A1:B3"),))
            for result in self.conversions("xlsx_review_blank_merge_no_data.xlsx", mode, xlsx=options):
                with self.subTest(mode=mode, sample="no data"):
                    self.assertFalse(result.success)
                    self.assertIsNone(result.markdown)
                    self.assertEqual(result.tables, [])
                    self.assertIn("no data records", result.error)

    def test_array_formula_preserves_stable_expression_without_calculation(self):
        for mode in ("table", "rows"):
            results = list(self.conversions("xlsx_review_array_formula.xlsx", mode))
            for result in results:
                with self.subTest(mode=mode):
                    self.assertTrue(result.success, result.error)
                    cell = result.tables[0].rows[0].cells[1]
                    self.assertEqual(cell.raw_value, '=SUM(IF(A2="A",1,0))')
                    self.assertEqual(cell.formula, '=SUM(IF(A2="A",1,0))')
                    self.assertEqual(cell.text, '=SUM(IF(A2="A",1,0))（结果未知）')
                    self.assertEqual((cell.cached_value, cell.cache_status), (None, "unknown"))
                    self.assertIn(cell.text, result.markdown)
                    self.assertNotIn("object at", result.markdown)
                    self.assertEqual(cell.source.coordinate, "B2")
                    self.assertEqual(result.warnings,
                                     ["XLSX Sheet!B2: formula result unknown; not calculated."])
            self.assertEqual(results[0], results[1])

    def conversions(self, name, mode, **options):
        path = SAMPLES / name
        yield tabular.convert_file(path, mode=mode, context=CONTEXT, **options)
        yield tabular.convert_bytes(path.read_bytes(), format="xlsx", source=str(path),
                                    mode=mode, context=CONTEXT, **options)

    def test_empty_text_formula_cache_is_distinct_from_missing_cache(self):
        for mode in ("table", "rows"):
            for result in self.conversions("xlsx_review_string_cache.xlsx", mode):
                with self.subTest(mode=mode, source=result.source):
                    self.assertTrue(result.success, result.error)
                    empty, text, missing = [row.cells[1] for row in result.tables[0].rows]
                    self.assertEqual((empty.cached_value, empty.cache_status), ("", "cached"))
                    self.assertEqual(empty.formula, '=IF(1=1,"","x")')
                    self.assertEqual(empty.text,
                                     '=IF(1=1,"","x")（文件缓存：空文本；非实时计算结果）')
                    self.assertIn("文件缓存：空文本", result.markdown)
                    self.assertEqual((text.cached_value, text.cache_status), ("x", "cached"))
                    self.assertEqual((missing.cached_value, missing.cache_status), (None, "unknown"))
                    self.assertIn("结果未知", missing.text)
                    self.assertEqual(result.warnings,
                                     ["XLSX Sheet!B4: formula result unknown; not calculated."])
