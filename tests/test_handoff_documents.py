import copy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_pdf_word_mineru import mineru_server
from tests.test_pdf_word_mixed import SCAN_BLOCKS
from tests.zip_document_support import SERVICE_MARKDOWN, document_server, zip_containers


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
)
handoff = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff"
)
SAMPLES = Path(__file__).parent / "testFile"


class DocumentHandoffTests(unittest.TestCase):
    def round_trip(self, native, **identity):
        before = copy.deepcopy(native)
        report = handoff.adapt_result(native, **identity)
        with tempfile.TemporaryDirectory() as directory:
            saved = json.loads(handoff.export_json(report, Path(directory) / "result.json").read_bytes())
        self.assertEqual(native, before)
        document = saved["documents"][0]
        sources = {source["id"] for source in document["sources"]}
        units = {unit["id"] for unit in document["units"]}
        self.assertEqual(len({document["id"]} | sources | units),
                         1 + len(document["sources"]) + len(document["units"]))
        for unit in document["units"]:
            self.assertTrue(set(unit["source_ids"]) <= sources)
            self.assertIsNone(unit["parent_id"])
        return saved

    def test_pdf_keeps_actual_pages_methods_and_exact_ranges_in_complete_body(self):
        digital = content.convert_file(SAMPLES / "pdf_digital_page_order.pdf")
        with mineru_server(SCAN_BLOCKS, "pdf_mixed_maintenance.pdf",
                           inspect_upload=lambda data: True) as api:
            mixed = content.convert_bytes(
                (SAMPLES / "pdf_mixed_maintenance.pdf").read_bytes(),
                format="pdf", source="混合维护.pdf", mineru=api,
            )
        for native, pages, methods in (
            (digital, [1, 2], ["text_layer", "text_layer"]),
            (mixed, [1, 2, 3, 4], ["text_layer", "mineru_api", "text_layer", "mineru_api"]),
        ):
            with self.subTest(pages=pages):
                self.assertTrue(native.success, native.error)
                saved = self.round_trip(native, business_id="维护规程", version="修订二")
                document = saved["documents"][0]
                self.assertEqual(saved["status"], "success")
                self.assertEqual(document["body"], native.markdown)
                self.assertEqual(document["body_format"], "markdown")
                self.assertEqual(document["business_id"], "维护规程")
                self.assertEqual(document["version"], "修订二")
                sources = {source["id"]: source for source in document["sources"]}
                locations = [sources[unit["source_ids"][0]]["locator"] for unit in document["units"]]
                self.assertEqual([location["pdf_page_number"] for location in locations], pages)
                self.assertEqual([location["extraction_method"] for location in locations], methods)
                for unit, original in zip(document["units"], native.sources, strict=True):
                    self.assertEqual(unit["kind"], "pdf_page")
                    self.assertEqual(unit["alignment"], "exact")
                    self.assertEqual(unit["body_span"],
                                     {"start": original.markdown_start, "end": original.markdown_end})
                    self.assertEqual(document["body"][original.markdown_start:original.markdown_end],
                                     unit["text"])
                first_end = document["units"][0]["body_span"]["end"]
                second_start = document["units"][1]["body_span"]["start"]
                self.assertEqual(document["body"][first_end:second_start], "\n")
        self.assertIn("Printed page 41", digital.markdown)
        self.assertIn("Printed page 7", digital.markdown)
        self.assertIn("Temperature must not exceed 60 C.", mixed.markdown)

    def test_docx_preserves_section_block_types_levels_and_order_without_pages(self):
        for filename in ("docx_sections.docx", "docx_deep_headings.docx"):
            with self.subTest(filename=filename):
                native = content.convert_file(SAMPLES / filename)
                self.assertTrue(native.success, native.error)
                document = self.round_trip(native)["documents"][0]
                self.assertEqual(document["body"], native.markdown)
                self.assertIsNone(document["business_id"])
                self.assertIsNone(document["version"])
                blocks = [source for source in document["sources"] if source["kind"] == "docx_block"]
                self.assertEqual(len(blocks), len(native.sources))
                for unit, source, original in zip(document["units"], blocks, native.sources, strict=True):
                    locator = source["locator"]
                    self.assertEqual(unit["source_ids"], [source["id"]])
                    self.assertEqual(unit["kind"], original.block_type)
                    self.assertEqual(unit["alignment"], "exact")
                    self.assertEqual(unit["text"], document["body"][unit["body_span"]["start"]:
                                                                             unit["body_span"]["end"]])
                    self.assertEqual(locator["section_path"], list(original.section_path))
                    self.assertEqual(locator["body_block_number"], original.body_block_number)
                    self.assertEqual(locator["section_block_number"], original.section_block_number)
                    self.assertEqual(locator["heading_level"], original.heading_level)
                    self.assertEqual(locator["extraction_method"], "docx_native")
                    self.assertIsNone(locator["pdf_page_number"])
                if filename == "docx_sections.docx":
                    table = next(unit for unit in document["units"] if unit["kind"] == "table")
                    self.assertEqual(table["text"],
                                     "| 设备 | 周期 |\n| --- | --- |\n| 泵 | 每月 |\n| 阀门 | 每季度 |\n")
                    self.assertEqual(blocks[3]["locator"]["section_path"], ["设备维护"])
                    self.assertEqual([source["locator"]["body_block_number"] for source in blocks],
                                     [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14])
                else:
                    self.assertEqual([source["locator"]["heading_level"] for source in blocks], [6, 7, 9])
                    self.assertEqual(blocks[-1]["locator"]["section_path"],
                                     ["六级标题", "七级标题", "九级标题"])

    def test_native_diagnostics_keep_failure_and_quality_limits_out_of_body(self):
        for filename in ("pdf_digital_teaching.pdf", "pdf_digital_blank.pdf",
                         "pdf_digital_corrupt.pdf", "docx_empty.docx", "docx_corrupt.docx"):
            with self.subTest(filename=filename):
                native = content.convert_file(SAMPLES / filename)
                saved = self.round_trip(native)
                document = saved["documents"][0]
                warnings = [item for item in document["diagnostics"] if item["level"] == "warning"]
                errors = [item for item in document["diagnostics"] if item["level"] == "error"]
                self.assertEqual([item["message"] for item in warnings], native.warnings)
                self.assertEqual([item["message"] for item in errors],
                                 [] if native.error is None else [native.error])
                for item in document["diagnostics"]:
                    self.assertEqual(item["document_id"], document["id"])
                    self.assertEqual(item["source_id"], document["sources"][0]["id"])
                if native.success:
                    self.assertEqual(saved["status"], "success")
                    for warning in native.warnings:
                        self.assertNotIn(warning, document["body"])
                else:
                    self.assertEqual(saved["status"], "failed")
                    self.assertEqual(document["status"], "failed")
                    self.assertIsNone(document["body"])
                    self.assertEqual(document["units"], [])
                    self.assertEqual(document["sources"][0]["locator"]["location"],
                                     str(SAMPLES / filename))

    def test_hosted_pdf_keeps_separate_markdown_artifacts_and_unmapped_service_blocks(self):
        with document_server() as service:
            archive = zip_containers.convert_file(
                SAMPLES / "zip_document_pdf.zip", source="资料.zip",
                parser_options={"document": {"mineru": service.config}},
            )
            native = archive.members[0].result
            self.assertTrue(native.success, native.error)
            network_before = copy.deepcopy((service.requests, service.uploads, service.polls))
            document = self.round_trip(native)["documents"][0]
            self.assertEqual((service.requests, service.uploads, service.polls), network_before)
        self.assertEqual(document["body"], SERVICE_MARKDOWN)
        self.assertEqual(document["body_format"], "markdown")
        self.assertEqual(document["metadata"]["provider"], "mineru")
        self.assertEqual(document["metadata"]["requested_model"], "vlm")
        self.assertEqual(document["structure"]["structured_json"], native.structured_json)
        self.assertEqual(document["structure"]["artifacts"], native.artifacts)
        self.assertEqual(document["structure"]["sources"], [asdict(source) for source in native.sources])
        self.assertEqual(document["structure"]["markdown_file"], "output/full.md")
        self.assertEqual(document["structure"]["content_list_file"], "output/generated_content_list.json")
        block = document["structure"]["structured_json"]["output/generated_content_list.json"][0]
        self.assertEqual(block["text"], "Different structured text")
        self.assertEqual(block["bbox"], [10, 20, 300, 400])
        self.assertNotIn(block["text"], document["body"])
        body_unit, block_unit = document["units"]
        self.assertEqual(body_unit["text"], SERVICE_MARKDOWN)
        self.assertEqual(body_unit["alignment"], "document")
        self.assertIsNone(body_unit["body_span"])
        self.assertEqual(block_unit["kind"], "service_block")
        self.assertEqual(block_unit["alignment"], "unmapped")
        self.assertIsNone(block_unit["body_span"])
        self.assertIsNone(block_unit["text"])
        source = next(source for source in document["sources"] if source["id"] == block_unit["source_ids"][0])
        self.assertEqual(source["kind"], "service_block")
        self.assertEqual(source["locator"]["location"], "资料.zip!/docs/manual.pdf#1")
        self.assertEqual(source["locator"]["artifact"], "output/generated_content_list.json")
        self.assertEqual(source["locator"]["block_index"], 0)
        self.assertEqual(source["locator"]["service_page_index"], 0)
        self.assertEqual(source["locator"]["pdf_page_number"], 1)
        self.assertEqual(source["locator"]["page_origin"], "uploaded_pdf")
        self.assertIsNone(source["locator"]["markdown_start"])
        self.assertIsNone(source["locator"]["markdown_end"])

    def test_hosted_review_preserves_office_location_gaps_without_promoting_service_pages(self):
        with document_server() as service:
            for filename in ("zip_document_pdf.zip", "zip_document_office.zip"):
                archive = zip_containers.convert_file(
                    SAMPLES / filename, parser_options={"document": {"mineru": service.config}},
                )
                for member in archive.members:
                    if member.result_kind != "document":
                        continue
                    native = member.result
                    with self.subTest(format=native.format):
                        document = self.round_trip(native)["documents"][0]
                        self.assertEqual(document["status"], "success")
                        self.assertTrue(document["requires_review"])
                        self.assertEqual(document["metadata"]["review_items"], native.review_items)
                        reviews = [item for item in document["diagnostics"] if item["code"] == "upstream_review"]
                        self.assertEqual([item["message"] for item in reviews], native.review_items)
                        for item in reviews:
                            self.assertEqual(item["document_id"], document["id"])
                            self.assertEqual(item["source_id"], document["sources"][0]["id"])
                            self.assertNotIn(item["message"], document["body"])
                        self.assertIn("character ranges are unavailable", " ".join(native.review_items))
                        if native.format != "pdf":
                            self.assertIn("Office native locations are unavailable", " ".join(native.review_items))
                            source = document["sources"][1]
                            self.assertEqual(source["kind"], "service_block")
                            self.assertEqual(source["locator"]["service_page_index"], 0)
                            self.assertEqual(source["locator"]["page_origin"], "service_page_unverified")
                            self.assertIsNone(source["locator"]["pdf_page_number"])
                            for field in ("body_block_number", "section_path", "slide_number", "cell_address"):
                                self.assertNotIn(field, source["locator"])

    def test_failed_hosted_document_exports_error_and_source_without_usable_body(self):
        for options in ({"failure": "failed"}, {"result_name": "zip_document_result_bad_json.zip"}):
            with self.subTest(options=options), document_server(**options) as service:
                archive = zip_containers.convert_file(
                    SAMPLES / "zip_document_pdf.zip", source="失败资料.zip",
                    parser_options={"document": {"mineru": service.config}},
                )
                native = archive.members[0].result
                self.assertFalse(native.success)
                saved = self.round_trip(native)
                self.assertEqual(saved["status"], "failed")
                document = saved["documents"][0]
                self.assertEqual(document["status"], "failed")
                self.assertIsNone(document["body"])
                self.assertEqual(document["units"], [])
                self.assertEqual(document["sources"][0]["locator"],
                                 {"location": "失败资料.zip!/docs/manual.pdf#1", "format": "pdf"})
                errors = [item for item in document["diagnostics"] if item["level"] == "error"]
                self.assertEqual([item["message"] for item in errors], [native.error])
                self.assertEqual(errors[0]["document_id"], document["id"])
                self.assertEqual(errors[0]["source_id"], document["sources"][0]["id"])
                self.assertEqual(document["structure"]["structured_json"], {})

    def test_hosted_web_keeps_html_selected_mhtml_and_document_only_alignment(self):
        with document_server() as service:
            archive = zip_containers.convert_file(
                SAMPLES / "zip_document_web.zip",
                parser_options={"document": {"mineru": service.config}},
            )
            network_before = copy.deepcopy((service.requests, service.uploads, service.polls))
            for member in archive.members:
                native = member.result
                with self.subTest(format=native.format):
                    document = self.round_trip(native)["documents"][0]
                    self.assertEqual(document["body"], "# Remote article\n")
                    self.assertEqual(document["structure"]["html"], "<h1>Remote article</h1>")
                    self.assertEqual(document["structure"]["html_file"], "main.html")
                    self.assertEqual(document["structure"]["artifacts"], ["full.md", "main.html"])
                    self.assertEqual(document["structure"]["sources"], [])
                    self.assertEqual(document["structure"]["structured_json"], {})
                    self.assertEqual(document["metadata"]["main_html"], native.main_html)
                    self.assertEqual(document["metadata"]["requested_model"], "MinerU-HTML")
                    self.assertTrue(document["requires_review"])
                    self.assertEqual(len(document["units"]), 1)
                    self.assertEqual(document["units"][0]["alignment"], "document")
                    self.assertIsNone(document["units"][0]["body_span"])
                    self.assertEqual([item["message"] for item in document["diagnostics"]
                                      if item["code"] == "upstream_warning"], native.warnings)
                    if native.format == "mhtml":
                        self.assertEqual(document["metadata"]["main_html"]["content_id"], "<main-page>")
                        self.assertEqual(document["metadata"]["main_html"]["mime_index"], 2)
            self.assertEqual((service.requests, service.uploads, service.polls), network_before)


if __name__ == "__main__":
    unittest.main()
