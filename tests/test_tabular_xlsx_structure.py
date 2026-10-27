import importlib
from pathlib import Path
import unittest


tabular = importlib.import_module("app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing")
SAMPLES = Path(__file__).parent / "testFile"


class XlsxStructureTests(unittest.TestCase):
    def test_consecutive_header_layers_keep_units_and_each_original_source(self):
        path = SAMPLES / "xlsx_structure_layers.xlsx"
        options = tabular.XlsxOptions((tabular.XlsxSheetOptions("层级", "A2:D5", (2, 3)),))
        result = tabular.convert_bytes(path.read_bytes(), format="xlsx", source="layers.xlsx", xlsx=options)
        self.assertTrue(result.success, result.error)
        table = result.tables[0]
        self.assertEqual([c.name for c in table.columns],
                         ["对象 / 城市", "标准 / 住宿（元／晚）", "餐补（元／天）", "备注"])
        self.assertEqual([[s.coordinate for s in c.header_sources] for c in table.columns],
                         [["A2", "A3"], ["B2", "B3"], ["C2", "C3"], ["D2", "D3"]])
        self.assertEqual(table.columns[1].source.coordinate, "B2")
        self.assertEqual(table.source.coordinate, "A2:D5")
        self.assertEqual([r.source.row_start for r in table.rows], [4, 5])
        self.assertIn("标准 / 住宿（元／晚）：500", table.rows[0].text)
        self.assertNotIn("标准 / 餐补", table.rows[0].text)
        self.assertEqual(result, tabular.convert_file(path, source="layers.xlsx", xlsx=options))

    def test_real_header_merges_expand_only_their_own_labels(self):
        options = tabular.XlsxOptions((tabular.XlsxSheetOptions("合并", header_rows=(1, 2, 3)),))
        result = tabular.convert_file(SAMPLES / "xlsx_structure_merges.xlsx", xlsx=options)
        self.assertTrue(result.success, result.error)
        table = result.tables[0]
        self.assertEqual([c.name for c in table.columns],
                         ["地区", "差旅标准 / 住宿 / 元／晚", "差旅标准 / 餐补 / 元／天", "备注"])
        self.assertEqual([s.coordinate for s in table.columns[0].header_sources], ["A1", "A2", "A3"])
        self.assertEqual([(s.merged_anchor, s.merged_range) for s in table.columns[0].header_sources],
                         [("A1", "A1:A3")] * 3)
        self.assertEqual(table.columns[2].header_sources[0].coordinate, "C1")
        self.assertEqual(table.columns[2].header_sources[0].merged_anchor, "B1")
        self.assertEqual(table.columns[2].header_sources[0].merged_range, "B1:C1")
        self.assertIsNone(table.columns[2].header_sources[1].merged_anchor)
        self.assertIn("差旅标准 / 餐补 / 元／天：100", table.rows[0].text)

    def test_data_text_labels_follow_real_merges_without_changing_raw_blanks(self):
        options = tabular.XlsxOptions((tabular.XlsxSheetOptions("合并", header_rows=(1, 2, 3)),))
        for mode in ("rows", "table"):
            with self.subTest(mode=mode):
                result = tabular.convert_file(SAMPLES / "xlsx_structure_merges.xlsx", xlsx=options, mode=mode)
                self.assertTrue(result.success, result.error)
                first, second, outside, horizontal = result.tables[0].rows
                self.assertEqual(first.cells[0].raw_value, "华北")
                self.assertEqual(first.cells[0].source.merged_range, "A4:A5")
                self.assertIsNone(second.cells[0].raw_value)
                self.assertEqual(second.cells[0].text, "华北（合并共同标签，锚点 A4，范围 A4:A5）")
                self.assertIn("地区：华北（合并共同标签，锚点 A4，范围 A4:A5）", second.text)
                self.assertEqual(second.cells[0].source.coordinate, "A5")
                self.assertEqual(second.cells[0].source.merged_anchor, "A4")
                self.assertIn("共同说明", second.cells[3].text)
                self.assertEqual(second.cells[3].source.merged_range, "D4:D5")
                self.assertIsNone(outside.cells[0].raw_value)
                self.assertEqual(outside.cells[0].text, "")
                self.assertIsNone(outside.cells[0].source.merged_anchor)
                self.assertIsNone(outside.cells[3].source.merged_range)
                self.assertEqual(horizontal.cells[1].raw_value, "横向共同标签")
                for cell in horizontal.cells[2:]:
                    self.assertIsNone(cell.raw_value)
                    self.assertIn("横向共同标签（合并共同标签", cell.text)
                    self.assertEqual(cell.source.merged_anchor, "B7")
                    self.assertEqual(cell.source.merged_range, "B7:D7")
                self.assertIn("华北（合并共同标签，锚点 A4，范围 A4:A5）", result.markdown)

    def test_merged_numbers_formulas_and_booleans_are_never_independent_covered_values(self):
        path = SAMPLES / "xlsx_structure_measurements.xlsx"
        for mode in ("rows", "table"):
            with self.subTest(mode=mode):
                result = tabular.convert_bytes(path.read_bytes(), format="xlsx", source="measurements.xlsx", mode=mode)
                self.assertTrue(result.success, result.error)
                anchor, covered, outside = result.tables[0].rows
                self.assertEqual([c.raw_value for c in anchor.cells], ["甲", 900, "=B2+1", True])
                self.assertIn("900（合并值，仅锚点记录，范围 B2:B3）", anchor.text)
                self.assertEqual(anchor.cells[2].formula, "=B2+1")
                self.assertEqual([c.raw_value for c in covered.cells], ["乙", None, None, None])
                for cell, coordinate, area in zip(covered.cells[1:], ("B2", "C2", "D2"),
                                                   ("B2:B3", "C2:C3", "D2:D3")):
                    self.assertIn(f"值见锚点 {coordinate}，范围 {area}", cell.text)
                    self.assertIn("非本行独立值", cell.text)
                    self.assertEqual(cell.source.merged_anchor, coordinate)
                    self.assertEqual(cell.source.merged_range, area)
                    self.assertIsNone(cell.formula)
                    self.assertIsNone(cell.cached_value)
                    self.assertIsNone(cell.cache_status)
                self.assertNotIn("900", covered.text)
                self.assertNotIn("=B2+1", covered.text)
                self.assertNotIn("True", covered.text)
                self.assertEqual([c.text for c in outside.cells[1:]], ["", "", ""])
                self.assertIn("非本行独立值", result.markdown)

    def test_default_extent_includes_real_merged_coverage_and_preserves_covered_rows(self):
        path = SAMPLES / "xlsx_structure_vertical_data.xlsx"
        result = tabular.convert_file(path)
        self.assertTrue(result.success, result.error)
        table = result.tables[0]
        self.assertEqual(table.source.coordinate, "A1:A4")
        self.assertEqual([r.source.row_start for r in table.rows], [2, 3, 4])
        self.assertEqual([r.cells[0].raw_value for r in table.rows], ["共同", None, None])
        self.assertIn("共同（合并共同标签，锚点 A2，范围 A2:A4）", table.rows[2].text)
        self.assertEqual(table.rows[2].cells[0].source.coordinate, "A4")

    def test_ambiguous_or_cut_structure_fails_atomically_with_locations(self):
        cases = (
            ("merges", "合并", "C1:D7", (1, 2, 3), "B1:C1", "cuts"),
            ("merges", "合并", "A1:B7", (1, 2, 3), "B1:C1", "cuts"),
            ("merges", "合并", "A1:D4", (1, 2, 3), "A4:A5", "cuts"),
            ("merges", "合并", "A5:D7", (5,), "A4:A5", "cuts"),
            ("merges", "合并", "A1:D7", (2, 3), "A1:A3", "cuts"),
            ("cross_boundary", "结构", None, (1,), "A1:A2", "boundary"),
            ("duplicate", "结构", None, (1, 2), "header rows", "duplicate"),
            ("blank", "结构", None, (1, 2), "B1", "empty column"),
            ("empty_level", "结构", None, (1, 2), "2", "header row"),
        )
        for suffix, sheet, area, headers, position, reason in cases:
            with self.subTest(sample=suffix, area=area, headers=headers):
                path = SAMPLES / f"xlsx_structure_{suffix}.xlsx"
                options = tabular.XlsxOptions((tabular.XlsxSheetOptions(sheet, area, headers),))
                for result in (tabular.convert_file(path, xlsx=options),
                               tabular.convert_bytes(path.read_bytes(), format="xlsx", source="structure.xlsx", xlsx=options)):
                    self.assertFalse(result.success)
                    self.assertIsNone(result.markdown)
                    self.assertEqual(result.tables, [])
                    self.assertIn(sheet, result.error)
                    self.assertIn(position, result.error)
                    self.assertIn(reason, result.error)


    def test_cut_range_cannot_hide_its_anchor_behind_an_apparently_empty_selection(self):
        result = tabular.convert_file(SAMPLES / "xlsx_structure_vertical_data.xlsx", xlsx=tabular.XlsxOptions((
            tabular.XlsxSheetOptions("结构", "A3:A4"),)))
        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertEqual(result.tables, [])
        self.assertIn("A2:A4", result.error)
        self.assertIn("cuts", result.error)

    def test_later_sheet_structure_failure_does_not_expose_the_valid_first_table(self):
        path = SAMPLES / "xlsx_structure_atomic.xlsx"
        for mode in ("rows", "table"):
            result = tabular.convert_file(path, mode=mode)
            self.assertFalse(result.success)
            self.assertIsNone(result.markdown)
            self.assertEqual(result.tables, [])
            self.assertIn("跨界", result.error)
            self.assertIn("A1:A2", result.error)
            self.assertIn("boundary", result.error)
