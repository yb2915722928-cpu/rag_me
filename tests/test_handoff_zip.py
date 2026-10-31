import copy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_audio_video import QUESTION as MEDIA_QUESTION, TRANSCRIPT, media_server, video_reply
from tests.test_image_ocr import step_server
from tests.test_image_provenance import images, provenance_server
from tests.test_image_understanding import QUESTION, envelope, step_server as understanding_server
from tests.zip_document_support import SERVICE_MARKDOWN, document_server


zip_containers = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.8_zipContainers"
)
handoff = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.unifiedDocumentHandoff"
)
SAMPLES = Path(__file__).parent / "testFile"


class ZipHandoffTests(unittest.TestCase):
    def round_trip(self, native, **identity):
        before = copy.deepcopy(native)
        report = handoff.adapt_result(native, **identity)
        with tempfile.TemporaryDirectory() as directory:
            saved = json.loads(handoff.export_json(report, Path(directory) / "交接.json").read_bytes())
        self.assertEqual(native, before)
        identifiers = []
        for document in saved["documents"]:
            sources = {source["id"] for source in document["sources"]}
            units = {unit["id"] for unit in document["units"]}
            identifiers.append(document["id"])
            identifiers.extend(source["id"] for source in document["sources"])
            identifiers.extend(unit["id"] for unit in document["units"])
            for unit in document["units"]:
                self.assertTrue(set(unit["source_ids"]) <= sources)
                self.assertTrue(unit["parent_id"] is None or unit["parent_id"] in units)
            for diagnostic in document["diagnostics"]:
                self.assertEqual(diagnostic["document_id"], document["id"])
                self.assertTrue(diagnostic["source_id"] is None or diagnostic["source_id"] in sources)
                self.assertTrue(diagnostic["unit_id"] is None or diagnostic["unit_id"] in units)
        self.assertEqual(len(identifiers), len(set(identifiers)))
        return saved

    def test_text_members_keep_independent_bodies_and_unique_references(self):
        native = zip_containers.convert_file(SAMPLES / "zip_text.zip", source="资料包.zip")
        self.assertEqual(native.status, "success")

        saved = self.round_trip(native, business_id="资料包", version="修订二")

        self.assertEqual(saved["status"], "success")
        self.assertEqual([document["body"] for document in saved["documents"]],
                         ["ZIP 容器示例\n两行原文\n", "# 使用方法\n\n保留 **强调**。\n"])
        for index, document in enumerate(saved["documents"]):
            self.assertIsNone(document["business_id"])
            self.assertIsNone(document["version"])
            self.assertEqual(document["sources"][0]["locator"]["location"],
                             native.members[index].result.source.location)
            self.assertEqual(document["units"][0]["text"], document["body"])
            self.assertEqual(document["units"][0]["alignment"], "document")
            self.assertIsNone(document["units"][0]["body_span"])

    def test_member_inventory_keeps_duplicates_failures_ignored_and_unprocessed(self):
        for filename, limits in (("zip_members.zip", None),
                                 ("zip_budgets.zip", zip_containers.ZipLimits(max_total_bytes=8))):
            with self.subTest(filename=filename):
                native = zip_containers.convert_file(SAMPLES / filename, source="混合包.zip", limits=limits)
                self.assertEqual(native.status, "partial_success")

                saved = self.round_trip(native, business_id="集合", version="v2")

                self.assertEqual(saved["status"], "partial_success")
                container = saved["metadata"]["container"]
                self.assertEqual(container, {
                    "source": "混合包.zip", "business_id": "集合", "version": "v2",
                    "error": native.error, "stop_reason": native.stop_reason,
                    "counts": native.counts, "total_bytes_read": native.total_bytes_read,
                    "requires_review": native.requires_review,
                })
                members = saved["metadata"]["members"]
                self.assertEqual(len(members), native.counts["total"])
                documents = {document["id"]: document for document in saved["documents"]}
                for member, original in zip(members, native.members, strict=True):
                    self.assertEqual(member["source"], {
                        "container": "混合包.zip", "member_path": original.source.member_path,
                        "entry_index": original.source.entry_index,
                    })
                    for name in ("format", "status", "result_kind", "error", "reason", "bytes_read"):
                        self.assertEqual(member[name], getattr(original, name))
                    self.assertTrue(set(member["document_ids"]) <= documents.keys())
                    if original.status == "success":
                        self.assertEqual(len(member["document_ids"]), 1)
                        document = documents[member["document_ids"][0]]
                        self.assertEqual(document["body"], original.result.markdown)
                        self.assertIsNone(document["business_id"])
                        self.assertIsNone(document["version"])
                    if original.result is None:
                        self.assertEqual(member["document_ids"], [])
                if filename == "zip_members.zip":
                    self.assertEqual(members[3]["source"]["member_path"], "same.txt")
                    self.assertEqual(members[4]["source"]["member_path"], "same.txt")
                    self.assertEqual([members[i]["source"]["entry_index"] for i in (3, 4)], [4, 5])
                    self.assertNotEqual(members[3]["document_ids"], members[4]["document_ids"])
                    self.assertEqual(members[10]["reason"], "unsupported_format")
                    self.assertIn("Invalid JSON", members[11]["error"])
                else:
                    self.assertEqual([member["status"] for member in members],
                                     ["success", "unprocessed", "unprocessed", "ignored"])
                    self.assertEqual(container["stop_reason"], "max_total_bytes")

    def test_failed_native_results_keep_diagnostics_without_chunkable_body(self):
        structured = zip_containers.convert_file(SAMPLES / "zip_members.zip")
        with document_server(result_name="zip_document_result_bad_list.zip") as service:
            document = zip_containers.convert_file(
                SAMPLES / "zip_document_pdf.zip",
                parser_options={"document": {"mineru": service.config}},
            )
        with step_server() as config:
            image = zip_containers.convert_file(
                SAMPLES / "zip_image_corrupt.zip",
                parser_options={"image": {"task": "ocr", "config": config}},
            )
        with media_server(fail_at=2) as (config, _):
            media = zip_containers.convert_file(
                SAMPLES / "zip_media_delayed.zip",
                parser_options={"media": {"task": "transcribe", "config": config,
                                          "options": {"audio_segment_seconds": 2.5}}},
            )
        for native, code in ((structured, "upstream_error"), (document, "upstream_error"),
                             (image, "image_decode_error"), (media, "service_error")):
            with self.subTest(code=code):
                self.assertEqual(native.status, "partial_success")
                failed_index = next(index for index, member in enumerate(native.members)
                                    if member.status == "failed" and member.result is not None)

                saved = self.round_trip(native)

                member = saved["metadata"]["members"][failed_index]
                self.assertEqual(member["status"], "failed")
                self.assertEqual(member["reason"], "parse_error")
                self.assertEqual(len(member["document_ids"]), 1)
                document = next(document for document in saved["documents"]
                                if document["id"] == member["document_ids"][0])
                self.assertEqual(document["status"], "failed")
                self.assertIsNone(document["body"])
                self.assertEqual(document["units"], [])
                error = next(item for item in document["diagnostics"] if item["code"] == code)
                self.assertEqual(error["level"], "error")
                self.assertEqual(error["message"], native.members[failed_index].error)

    def test_empty_corrupt_and_all_failed_archives_export_failure_evidence(self):
        for filename, total in (("zip_empty.zip", 0), ("zip_corrupt.zip", 0),
                                ("zip_metadata.zip", 3), ("zip_all_failed.zip", 2)):
            with self.subTest(filename=filename):
                native = zip_containers.convert_file(SAMPLES / filename)
                self.assertEqual(native.status, "failed")

                saved = self.round_trip(native)

                self.assertEqual(saved["status"], "failed")
                self.assertEqual(saved["metadata"]["container"]["counts"]["total"], total)
                self.assertEqual(len(saved["metadata"]["members"]), total)
                self.assertIsNone(saved["metadata"]["container"]["business_id"])
                self.assertIsNone(saved["metadata"]["container"]["version"])
                for document in saved["documents"]:
                    self.assertIsNone(document["body"])
                    self.assertEqual(document["units"], [])
                if native.error:
                    self.assertEqual(saved["diagnostics"], [{
                        "level": "error", "code": "zip_error", "message": native.error,
                        "document_id": None, "unit_id": None, "source_id": None,
                        "details": {"container": native.source, "stop_reason": native.stop_reason},
                    }])

    def test_mixed_lightweight_members_keep_node_parentage_rows_and_cells(self):
        native = zip_containers.convert_file(
            SAMPLES / "zip_lightweight.zip", source="structure.zip",
            parser_options={"text": {"encoding": "gb18030"},
                            "csv": {"encoding": "gb18030", "delimiter": ";", "mode": "rows"}},
        )
        self.assertEqual(native.status, "success")

        saved = self.round_trip(native)

        self.assertEqual([document["body"] for document in saved["documents"]],
                         [member.result.markdown for member in native.members])
        self.assertEqual([member["result_kind"] for member in saved["metadata"]["members"]],
                         ["structured", "structured", "csv", "text"])
        structured, xml, table, text = saved["documents"]
        sources = {source["id"]: source["locator"] for source in structured["sources"]}
        nodes = {sources[unit["source_ids"][0]]["node_path"]: unit for unit in structured["units"]}
        self.assertEqual(nodes["/rules/0/city"]["parent_id"], nodes["/rules/0"]["id"])
        for document in (structured, xml):
            for unit in document["units"]:
                self.assertEqual(unit["alignment"], "unmapped")
                self.assertIsNone(unit["body_span"])
        self.assertIn("<!--保留-->", xml["body"])
        row = table["units"][0]
        self.assertIn("城市：北京", row["text"])
        self.assertIn("额度：00500", row["text"])
        self.assertEqual(row["alignment"], "unmapped")
        row_source = next(source["locator"] for source in table["sources"]
                          if source["id"] == row["source_ids"][0])
        self.assertEqual(row_source["row_start"], 2)
        self.assertEqual(row_source["source"]["location"], "structure.zip!/rates.csv#3")
        self.assertEqual(table["structure"]["tables"][0]["columns"][1]["name"], "额度")
        cell = table["structure"]["tables"][0]["rows"][0]["cells"][1]
        self.assertEqual(cell["raw_value"], "00500")
        self.assertEqual(cell["source"]["column_start"], 2)
        self.assertEqual(text["body"], "正文编码独立于文件名。")

    def test_hosted_members_keep_service_artifacts_pages_and_selected_html(self):
        with document_server() as service:
            native = zip_containers.convert_file(
                SAMPLES / "zip_documents.zip", source="documents.zip",
                parser_options={"document": {"mineru": service.config}},
            )
        self.assertEqual(native.status, "success")

        saved = self.round_trip(native)

        self.assertTrue(saved["metadata"]["container"]["requires_review"])
        self.assertEqual(len(saved["documents"]), 9)
        for document, member in zip(saved["documents"], native.members, strict=True):
            self.assertEqual(document["body"], member.result.markdown)
            if member.result_kind != "document":
                continue
            original = asdict(member.result)
            self.assertEqual(document["requires_review"], member.result.requires_review)
            for key in ("structured_json", "sources", "artifacts", "html", "html_file",
                        "markdown_file", "content_list_file"):
                self.assertEqual(document["structure"][key], original[key])
            self.assertEqual(document["metadata"]["main_html"], original["main_html"])
            self.assertEqual(document["metadata"]["review_items"], original["review_items"])
            for unit in document["units"]:
                self.assertIsNone(unit["body_span"])
                if unit["kind"] == "service_block":
                    self.assertEqual(unit["alignment"], "unmapped")
            if member.format in ("pdf", "docx", "pptx", "xlsx"):
                self.assertEqual(document["body"], SERVICE_MARKDOWN)
                source = document["structure"]["sources"][0]
                self.assertEqual(source["service_page_index"], 0)
                self.assertEqual(source["pdf_page_number"], 1 if member.format == "pdf" else None)
            if member.format == "mhtml":
                self.assertEqual(document["metadata"]["main_html"]["content_id"], "<main-page>")
                self.assertEqual(document["metadata"]["main_html"]["mime_index"], 2)

    def test_image_no_text_and_uncertain_keep_quality_state_after_service_stops(self):
        for filename, status, text, options in (
            ("zip_image_blank.zip", "no_text", "", {"task": "ocr"}),
            ("zip_image_uncertain.zip", "uncertain", "审批终点被截断，无法确认关系。",
             {"task": "understand", "question": QUESTION}),
        ):
            with self.subTest(status=status):
                with understanding_server(envelope(status=status, text=text, notes=["需对照原图"])) as (config, _):
                    native = zip_containers.convert_file(
                        SAMPLES / filename, parser_options={"image": options | {"config": config}},
                    )
                self.assertEqual(native.status, "success")

                saved = self.round_trip(native)

                self.assertEqual(saved["metadata"]["members"][0]["status"], "success")
                self.assertTrue(saved["metadata"]["container"]["requires_review"])
                document = saved["documents"][0]
                self.assertEqual((document["status"], document["body"]), (status, text))
                self.assertEqual(document["body_format"], "text")
                self.assertTrue(document["requires_review"])
                self.assertEqual(document["units"][0]["status"], status)
                self.assertEqual(document["sources"][0]["locator"], asdict(native.members[0].result.source))
                self.assertIn("需对照原图", [item["message"] for item in document["diagnostics"]])

    def test_image_crop_mapping_stays_with_its_member(self):
        with provenance_server() as config:
            native = zip_containers.convert_file(
                SAMPLES / "zip_image_crop.zip", source="policy.zip", parser_options={"image": {
                    "task": "ocr", "config": config, "is_cropped": True,
                    "document": images.DocumentSource("付款制度", "已批准版", images.DocumentPosition("pdf_page", 3)),
                    "crop": images.CropMapping("原图一", 1200, 600, (120, 180, 1120, 440)),
                }},
            )
        self.assertEqual(native.status, "success")

        saved = self.round_trip(native, business_id="容器", version="包版本")

        document = saved["documents"][0]
        self.assertEqual(saved["metadata"]["members"][0]["document_ids"], [document["id"]])
        source = document["sources"][0]["locator"]
        self.assertEqual(source["location"], "policy.zip!/crop.png#1")
        self.assertEqual(source["document"]["business_version"], "已批准版")
        self.assertEqual(source["document"]["position"], {"kind": "pdf_page", "index": 3})
        self.assertEqual(source["crop"]["bbox"], [120, 180, 1120, 440])
        self.assertEqual(source["crop"]["original_image_id"], "原图一")
        self.assertIsNone(document["business_id"])
        self.assertIsNone(document["version"])

    def test_media_members_keep_actual_times_modalities_and_unverified_empty_text(self):
        with media_server(video=video_reply("终点不清晰。", "uncertain", ["需回看"])) as (config, _):
            combined = zip_containers.convert_file(
                SAMPLES / "zip_media_delayed.zip", parser_options={"media": {
                    "task": "both", "question": MEDIA_QUESTION, "config": config,
                    "options": {"audio_segment_seconds": 2.5, "video_segment_seconds": 2},
                }},
            )
        with media_server(asr={"text": ""}) as (config, _):
            silent = zip_containers.convert_file(
                SAMPLES / "zip_media_silence.zip",
                parser_options={"media": {"task": "transcribe", "config": config}},
            )
        for native, status in ((combined, "uncertain"), (silent, "no_text")):
            with self.subTest(status=status):
                self.assertEqual(native.status, "success")

                saved = self.round_trip(native)

                document = saved["documents"][0]
                self.assertEqual(document["status"], status)
                self.assertEqual(document["body"], native.members[0].result.text)
                self.assertTrue(document["requires_review"])
                self.assertTrue(saved["metadata"]["container"]["requires_review"])
                self.assertEqual(document["sources"][0]["locator"], asdict(native.members[0].result.source))
                for unit in document["units"]:
                    self.assertEqual(unit["alignment"], "unmapped")
                    self.assertIsNone(unit["body_span"])
                if status == "uncertain":
                    self.assertIn(TRANSCRIPT, document["body"])
                    self.assertIn("终点不清晰。", document["body"])
                    sources = {source["id"]: source["locator"] for source in document["sources"]}
                    video = [sources[unit["source_ids"][0]] for unit in document["units"] if unit["kind"] == "video"]
                    self.assertEqual([(item["start_seconds"], item["end_seconds"]) for item in video],
                                     [(1.25, 3.25), (3.25, 5.25)])
                    self.assertTrue(all(item["speaker"] is None and item["time_precision"] == "segment" for item in video))
                    self.assertIn("需回看", [item["message"] for item in document["diagnostics"]])
                else:
                    self.assertEqual(document["body"], "")
                    self.assertTrue(all(unit["status"] == "no_text" for unit in document["units"]))


if __name__ == "__main__":
    unittest.main()
