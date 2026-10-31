import copy
from dataclasses import asdict
from importlib import import_module
import json
from pathlib import Path
import tempfile
import unittest


presentations = import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
handoff = import_module(
    "app.modules.1_documentIngestionAndParsing.unifiedDocumentHandoff"
)
SAMPLES = Path(__file__).parent / "testFile"


class StructuredHandoffTests(unittest.TestCase):
    def test_json_nodes_keep_escaped_paths_types_and_real_parent_references(self):
        sample = SAMPLES / "structured_json_pointers.json"
        for entry in ("file", "bytes"):
            with self.subTest(entry=entry):
                if entry == "file":
                    native = presentations.convert_file(sample, source="节点.json")
                else:
                    native = presentations.convert_bytes(
                        sample.read_bytes(), format="json", source="节点.json",
                    )
                self.assertTrue(native.success, native.error)
                saved = self._roundtrip(native, business_id="规则", version="修订二")

                document = saved["documents"][0]
                self.assertEqual(document["business_id"], "规则")
                self.assertEqual(document["version"], "修订二")
                self.assertEqual(document["metadata"]["encoding"], native.encoding)
                self.assertFalse(document["requires_review"])
                self.assertEqual(document["sources"][0]["locator"], {
                    "location": "节点.json", "format": "json",
                })
                self.assertEqual(
                    document["structure"]["sources"],
                    json.loads(json.dumps([asdict(s) for s in native.sources])),
                )
                sources = {s["id"]: s for s in document["sources"]}
                nodes = {
                    sources[u["source_ids"][0]]["locator"]["node_path"]: u
                    for u in document["units"]
                }
                self.assertEqual(len(nodes), 15)
                for path, parent_path, node_type in (
                    ("", None, "object"), ("/", "", "object"),
                    ("//a~1b", "/", "object"), ("//a~1b/m~0n", "//a~1b", "array"),
                    ("//a~1b/m~0n/2", "//a~1b/m~0n", "boolean"),
                    ("//a~1b/m~0n/3", "//a~1b/m~0n", "null"),
                    ("//a~1b/m~0n/7/企业~1退款~0", "//a~1b/m~0n/7", "string"),
                    ("/~01", "", "string"), ("/0", "", "string"),
                ):
                    unit = nodes[path]
                    locator = sources[unit["source_ids"][0]]["locator"]
                    self.assertEqual(unit["kind"], "json_node")
                    self.assertEqual(locator["parent_path"], parent_path)
                    self.assertEqual(locator["node_type"], node_type)
                    self.assertEqual(unit["parent_id"], None if parent_path is None else nodes[parent_path]["id"])
                for unit in document["units"]:
                    self.assertIsNone(unit["text"])
                    self.assertIsNone(unit["body_span"])
                    self.assertEqual(unit["alignment"], "unmapped")

    def test_pptx_units_keep_exact_spans_cells_notes_and_uncovered_body(self):
        for filename in ("pptx_refund.pptx", "pptx_visual.pptx", "pptx_tables.pptx"):
            with self.subTest(filename=filename):
                sample = SAMPLES / filename
                native = presentations.convert_bytes(
                    sample.read_bytes(), format="pptx", source=filename,
                )
                self.assertTrue(native.success, native.error)
                saved = self._roundtrip(native)
                document = saved["documents"][0]
                self.assertIsNone(document["business_id"])
                self.assertIsNone(document["version"])
                sources = {s["id"]: s for s in document["sources"]}
                self.assertEqual(len(document["units"]), len(native.sources))
                for original, unit in zip(native.sources, document["units"]):
                    locator = sources[unit["source_ids"][0]]["locator"]
                    self.assertEqual(locator, json.loads(json.dumps(asdict(original))))
                    if original.markdown_start is None:
                        self.assertIsNone(unit["body_span"])
                        self.assertIsNone(unit["text"])
                        self.assertEqual(unit["alignment"], "unmapped")
                    else:
                        self.assertEqual(unit["body_span"], {
                            "start": original.markdown_start, "end": original.markdown_end,
                        })
                        self.assertEqual(unit["alignment"], "exact")
                        self.assertEqual(unit["text"], document["body"][original.markdown_start:original.markdown_end])
                    self.assertIsNone(unit["parent_id"])
                if filename == "pptx_refund.pptx":
                    finance = next(u for u in document["units"] if u["text"] and "财务审核" in u["text"])
                    locator = sources[finance["source_ids"][0]]["locator"]
                    self.assertEqual((locator["slide_number"], locator["slide_title"], locator["paragraph_number"], locator["level"]),
                                     (8, "退款审批流程", 3, 1))
                    notes = next(u for u in document["units"] if u["kind"] == "notes_paragraph")
                    self.assertIn("仅适用于企业订单", notes["text"])
                    self.assertEqual(sources[notes["source_ids"][0]]["locator"]["slide_number"], 8)
                if filename == "pptx_visual.pptx":
                    cell = next(u for u in document["units"] if u["kind"] == "table_cell" and "财务审核" in u["text"])
                    locator = sources[cell["source_ids"][0]]["locator"]
                    self.assertEqual((locator["row_number"], locator["column_number"]), (2, 2))
                    self.assertIn("<table>\n<tr>", document["body"])
                    self.assertFalse(any("<table>" in (u["text"] or "") for u in document["units"]))

    def test_visual_objects_keep_review_references_and_parent_container_coordinates(self):
        for filename in ("pptx_visual.pptx", "pptx_refund.pptx", "pptx_image_only.pptx"):
            with self.subTest(filename=filename):
                native = presentations.convert_file(SAMPLES / filename)
                self.assertTrue(native.success, native.error)
                saved = self._roundtrip(native)
                document = saved["documents"][0]
                self.assertEqual(saved["status"], "success")
                self.assertEqual(document["status"], "success")
                self.assertTrue(document["requires_review"])
                self.assertEqual(
                    document["structure"]["review_issues"],
                    json.loads(json.dumps([asdict(issue) for issue in native.review_issues])),
                )
                sources = {s["id"]: s for s in document["sources"]}
                units = {u["id"]: u for u in document["units"]}
                self.assertEqual(len(document["diagnostics"]), len(native.review_issues))
                for original, diagnostic in zip(native.review_issues, document["diagnostics"]):
                    self.assertEqual(diagnostic["level"], "review")
                    self.assertEqual(diagnostic["code"], original.code)
                    self.assertEqual(diagnostic["message"], original.message)
                    self.assertEqual(diagnostic["document_id"], document["id"])
                    self.assertEqual(sources[diagnostic["source_id"]]["locator"],
                                     json.loads(json.dumps(asdict(original.source))))
                    self.assertEqual(units[diagnostic["unit_id"]]["source_ids"], [diagnostic["source_id"]])
                    self.assertNotIn(diagnostic["message"], document["body"])
                    if original.source.kind in ("group", "picture", "chart", "connector", "unsupported_object"):
                        unit = units[diagnostic["unit_id"]]
                        self.assertIsNone(unit["text"])
                        self.assertIsNone(unit["body_span"])
                        self.assertEqual(unit["alignment"], "unmapped")
                if filename == "pptx_visual.pptx":
                    group = next(s for s in document["sources"] if s["kind"] == "group")
                    child = next(s for s in document["sources"] if s["locator"].get("shape_path") == [2, 3])
                    self.assertEqual(group["locator"]["bounds_emu"], [1371600, 685800, 4114800, 1371600])
                    self.assertEqual(child["locator"]["bounds_emu"], [457200, 457200, 2743200, 1371600])
                    self.assertTrue(all(u["parent_id"] is None for u in document["units"]))
                if filename == "pptx_image_only.pptx":
                    self.assertEqual(document["body"], "# 第 1 页\n\n")
                    self.assertIn("picture_unverified", [d["code"] for d in document["diagnostics"]])

    def test_failed_native_results_export_errors_and_encoding_warnings_without_content(self):
        for filename in ("xml_invalid_gb18030.xml", "json_refund_invalid_gb18030.json", "pptx_atomic_failure.pptx"):
            with self.subTest(filename=filename):
                native = presentations.convert_file(SAMPLES / filename)
                self.assertFalse(native.success)
                saved = self._roundtrip(native)
                document = saved["documents"][0]
                self.assertEqual(saved["status"], "failed")
                self.assertEqual(document["status"], "failed")
                self.assertIsNone(document["body"])
                self.assertEqual(document["units"], [])
                self.assertEqual(document["structure"], {"sources": [], "review_issues": []})
                self.assertFalse(document["requires_review"])
                self.assertEqual(document["metadata"]["encoding"], native.encoding)
                self.assertEqual([d["message"] for d in document["diagnostics"]], [*native.warnings, native.error])
                for warning in document["diagnostics"][:-1]:
                    self.assertEqual((warning["level"], warning["code"]), ("warning", "upstream_warning"))
                self.assertEqual((document["diagnostics"][-1]["level"], document["diagnostics"][-1]["code"]),
                                 ("error", "upstream_error"))
                self.assertEqual(len(document["sources"]), 1)
                for diagnostic in document["diagnostics"]:
                    self.assertEqual(diagnostic["document_id"], document["id"])
                    self.assertEqual(diagnostic["source_id"], document["sources"][0]["id"])
                    self.assertIsNone(diagnostic["unit_id"])

    def test_xml_keeps_raw_body_repeated_elements_namespaces_and_unmapped_parents(self):
        for filename in ("xml_refund_rules.xml", "xml_relationships.xml", "xml_unknown_declaration.xml"):
            with self.subTest(filename=filename):
                native = presentations.convert_file(SAMPLES / filename)
                self.assertTrue(native.success, native.error)
                saved = self._roundtrip(native)
                document = saved["documents"][0]
                sources = {s["id"]: s for s in document["sources"]}
                nodes = {
                    sources[u["source_ids"][0]]["locator"]["node_path"]: u
                    for u in document["units"]
                }
                self.assertEqual(len(nodes), len(native.sources))
                for original in native.sources:
                    unit = nodes[original.node_path]
                    self.assertEqual(unit["kind"], "xml_element")
                    self.assertEqual(sources[unit["source_ids"][0]]["locator"]["node_type"], "element")
                    self.assertEqual(unit["parent_id"], None if original.parent_path is None else nodes[original.parent_path]["id"])
                    self.assertEqual(unit["alignment"], "unmapped")
                    self.assertIsNone(unit["text"])
                    self.assertIsNone(unit["body_span"])
                self.assertFalse(document["requires_review"])
                self.assertEqual([d["message"] for d in document["diagnostics"]], native.warnings)
                if filename == "xml_refund_rules.xml":
                    first = nodes["/refund[1]/rule[1]/owner[1]"]
                    second = nodes["/refund[1]/rule[2]/owner[1]"]
                    self.assertNotEqual(first["parent_id"], second["parent_id"])
                    self.assertIn('<rule order_type="企业订单" amount_gt="10000"><owner>企业专属负责人</owner>', document["body"])
                if filename == "xml_relationships.xml":
                    root = "/%7Burn%3Arefund%3Arules%7Drules[1]"
                    branch = root + "/%7Bhttps%3A%2F%2Fexample.invalid%2Frefund%2Fcorporate%7Dbranch[1]"
                    owner = branch + "/%7Bhttps%3A%2F%2Fexample.invalid%2Frefund%2Fcorporate%7Downer"
                    self.assertEqual(nodes[owner + "[1]"]["parent_id"], nodes[branch]["id"])
                    self.assertEqual(nodes[owner + "[2]"]["parent_id"], nodes[branch]["id"])
                    self.assertIn('<?workflow preserve="yes"?>\r\n', document["body"])
                    self.assertIn('普通订单<owner>客服</owner>核验后退款<!--归属注释-->', document["body"])

    def test_handoff_and_export_need_only_native_result_and_keep_independent_projections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "已删除.pptx"
            path.write_bytes((SAMPLES / "pptx_visual.pptx").read_bytes())
            native = presentations.convert_file(path)
        self.assertTrue(native.success, native.error)
        self.assertFalse(path.exists())
        saved = self._roundtrip(native)
        self.assertEqual(saved["documents"][0]["sources"][0]["locator"]["location"], str(path))

        before = copy.deepcopy(native)
        report = handoff.adapt_result(native)
        document = report.documents[0]
        document.sources[1].locator["slide_number"] = 999
        document.structure["sources"][0]["slide_number"] = 888
        document.structure["review_issues"][0]["source"]["slide_number"] = 777
        document.diagnostics[0].message = "changed"
        self.assertEqual(native, before)

    def _roundtrip(self, native, **identity):
        before = copy.deepcopy(native)
        report = handoff.adapt_result(native, **identity)
        with tempfile.TemporaryDirectory() as directory:
            output = handoff.export_json(report, Path(directory) / "交接.json")
            saved = json.loads(output.read_bytes())
        self.assertEqual(native, before)
        self.assertEqual(len(saved["documents"]), 1)
        document = saved["documents"][0]
        self.assertEqual(document["body"], native.markdown)
        self.assertEqual(document["body_format"], "markdown")
        ids = [document["id"], *(s["id"] for s in document["sources"]),
               *(u["id"] for u in document["units"])]
        self.assertEqual(len(ids), len(set(ids)))
        source_ids = {s["id"] for s in document["sources"]}
        unit_ids = {u["id"] for u in document["units"]}
        for unit in document["units"]:
            self.assertTrue(set(unit["source_ids"]) <= source_ids)
            if unit["parent_id"] is not None:
                self.assertIn(unit["parent_id"], unit_ids)
        return saved


if __name__ == "__main__":
    unittest.main()
