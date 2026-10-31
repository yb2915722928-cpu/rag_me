from importlib import import_module
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests.test_audio_video import QUESTION as MEDIA_QUESTION, TRANSCRIPT, media, media_server, video_reply
from tests.test_image_ocr import RULES, step_server
from tests.test_image_understanding import (
    CLEAR_ANSWER, QUESTION as IMAGE_QUESTION, envelope as image_envelope,
    step_server as image_task_server,
)
from tests.zip_document_support import SERVICE_MARKDOWN, document_server


ingestion = import_module("app.modules.1_documentIngestionAndParsing")
handoff = import_module(ingestion.__name__ + ".unifiedDocumentHandoff")
SAMPLES = Path(__file__).parent / "testFile"


class DocumentIngestionTests(unittest.TestCase):
    def assert_complete_reports_equal(self, reports):
        expected = reports[0].to_dict()
        with TemporaryDirectory() as directory:
            for index, report in enumerate(reports):
                with self.subTest(entry=index):
                    self.assertEqual(report.to_dict(), expected)
                    for export in (ingestion.export_json, handoff.export_json):
                        output = export(report, Path(directory) / "完整报告.json")
                        self.assertEqual(json.loads(output.read_bytes()), expected)
        return reports[0]

    def test_local_formats_keep_their_content_and_structure_through_both_entries(self):
        cases = (
            ("2_textAndWebContent", "txt_gb18030.txt", "document", "长江流经武汉"),
            ("2_textAndWebContent", "md_list_fence.md", "document", "first  value"),
            ("2_textAndWebContent", "html_table_pipe.html", "document", "普通文字中的管道"),
            ("2_textAndWebContent", "mhtml_start_shorter.mhtml", "document", "Start chooses this shorter page."),
            ("pdfAndDocxExtraction", "pdf_digital_page_order.pdf", "pdf_page", "Printed page 41"),
            ("pdfAndDocxExtraction", "docx_sections.docx", "paragraph", None),
            ("4_tabularFileProcessing", "csv_travel.csv", "table_row", None),
            ("4_tabularFileProcessing", "xlsx_travel.xlsx", "table_row", None),
            ("5_presentationsAndStructuredDocuments", "pptx_refund.pptx", "slide", None),
            ("5_presentationsAndStructuredDocuments", "structured_json_pointers.json", "json_node", None),
            ("5_presentationsAndStructuredDocuments", "xml_refund_rules.xml", "xml_element", None),
        )
        for module, filename, kind, evidence in cases:
            path = SAMPLES / filename
            parser = import_module(ingestion.__name__ + "." + module)
            identity = {"business_id": "规则", "version": "v2"}
            reports = (
                ingestion.convert_file(path, source="资料", **identity),
                ingestion.convert_bytes(
                    path.read_bytes(), format=path.suffix, source="资料", **identity,
                ),
                handoff.adapt_result(parser.convert_file(path, source="资料"), **identity),
                handoff.adapt_result(parser.convert_bytes(
                    path.read_bytes(), format=path.suffix, source="资料",
                ), **identity),
            )
            with self.subTest(filename=filename):
                report = self.assert_complete_reports_equal(reports)
                self.assertEqual(report.status, "success", report.to_dict())
                document = report.documents[0]
                self.assertEqual((document.business_id, document.version), ("规则", "v2"))
                self.assertEqual(document.sources[0].locator["location"], "资料")
                self.assertIn(kind, {unit.kind for unit in document.units})
                self.assertTrue(document.body)
                if evidence is not None:
                    self.assertIn(evidence, document.body)

    def test_explicit_format_and_parser_options_override_the_filename(self):
        report = ingestion.convert_file(
            SAMPLES / "structured_json_override.txt", format=" .JSON ", encoding="utf-8",
        )
        self.assertEqual(report.status, "success")
        self.assertTrue(all(unit.kind == "json_node" for unit in report.documents[0].units))

        report = ingestion.convert_bytes(
            "姓名;城市\n小明;武汉".encode("gb18030"), format=" .CSV ", source="表格",
            delimiter=";", encoding="gb18030", mode="rows",
        )
        self.assertEqual(report.status, "success")
        self.assertIn("武汉", report.documents[0].units[0].text)
        self.assertEqual(report.documents[0].metadata["encoding"], "gb18030")

    def test_format_aliases_reach_the_expected_parser(self):
        for format, filename in (
            ("markdown", "md_list_fence.md"), ("htm", "html_table_pipe.html"),
            ("mht", "mhtml_start_shorter.mhtml"),
        ):
            with self.subTest(format=format):
                report = ingestion.convert_bytes(
                    (SAMPLES / filename).read_bytes(), format=format, source="上传",
                )
                self.assertEqual(report.status, "success")
                self.assertTrue(report.documents[0].body)

    def test_native_failures_remain_exportable_reports_without_content_units(self):
        reports = (
            ingestion.convert_file(SAMPLES / "missing-file.txt"),
            ingestion.convert_bytes(b"{", format="json", source="broken.json"),
            ingestion.convert_bytes("not bytes", format="txt", source="wrong.txt"),
            ingestion.convert_bytes(b"text", format="txt", source=""),
            ingestion.convert_bytes(b"bad image", format="png", source="bad.png", task="ocr"),
        )
        with TemporaryDirectory() as directory:
            output = Path(directory) / "失败.json"
            for report in reports:
                with self.subTest(report=report.to_dict()):
                    self.assertEqual(report.status, "failed")
                    document = report.documents[0]
                    self.assertIsNone(document.body)
                    self.assertEqual(document.units, [])
                    self.assertTrue(any(item.level == "error" for item in document.diagnostics))
                    ingestion.export_json(report, output)
                    self.assertEqual(json.loads(output.read_bytes()), report.to_dict())

    def test_unsupported_format_and_unknown_options_raise_before_file_io(self):
        for format in (None, "", "   ", "exe", 123):
            with self.subTest(format=format), self.assertRaises(ValueError):
                ingestion.convert_bytes(b"", format=format, source="upload")
        with self.assertRaisesRegex(ValueError, "Unsupported format"):
            ingestion.convert_file(SAMPLES / "missing.exe")
        with self.assertRaises(TypeError):
            ingestion.convert_file(SAMPLES / "missing.txt", unrecognized_option=True)

    def test_invalid_identity_is_rejected_before_any_model_request(self):
        with step_server() as config:
            for identity in ({"business_id": " "}, {"version": 123}):
                with self.subTest(identity=identity), self.assertRaises((TypeError, ValueError)):
                    ingestion.convert_file(
                        SAMPLES / "image_ocr_rules.png", task="ocr", config=config, **identity,
                    )
        with document_server() as service:
            with self.assertRaises(ValueError):
                ingestion.convert_file(
                    SAMPLES / "zip_document_pdf.zip", version="",
                    parser_options={"document": {"mineru": service.config}},
                )
        self.assertEqual(service.requests, [])
        self.assertEqual(service.uploads, [])

    def test_images_keep_all_three_tasks_in_complete_reports(self):
        images = import_module(ingestion.__name__ + ".6_imageProcessing")
        identity = {"business_id": "审批图", "version": "业务三"}
        cases = (
            ("ocr", "image_ocr_rules.png", RULES, None),
            ("describe", "image_understanding_clear.png", CLEAR_ANSWER, None),
            ("understand", "image_understanding_clear.png", CLEAR_ANSWER, IMAGE_QUESTION),
        )
        for task, filename, text, question in cases:
            path = SAMPLES / filename
            kwargs = {"source": "规则图", "task": task, "question": question}
            with self.subTest(task=task), image_task_server(image_envelope(text=text)) as (config, requests):
                reports = (
                    ingestion.convert_file(path, config=config, **kwargs, **identity),
                    ingestion.convert_bytes(
                        path.read_bytes(), format="png", config=config, **kwargs, **identity,
                    ),
                    handoff.adapt_result(images.convert_file(path, config=config, **kwargs), **identity),
                    handoff.adapt_result(images.convert_bytes(
                        path.read_bytes(), format="png", config=config, **kwargs,
                    ), **identity),
                )
                self.assertEqual(len(requests), 4)
            report = self.assert_complete_reports_equal(reports)
            self.assertEqual(report.status, "content", report.to_dict())
            document = report.documents[0]
            self.assertEqual(document.body, text)
            self.assertEqual(document.units[0].kind, task)
            self.assertEqual((document.business_id, document.version), ("审批图", "业务三"))
            self.assertEqual(document.metadata["question"], question)
            self.assertEqual((document.metadata["requested_model"], document.metadata["response_model"]),
                             ("step-5-preview", "step-5-preview-actual"))
            self.assertEqual(document.sources[0].locator["location"], "规则图")
            self.assertTrue(document.requires_review)

    def test_media_keeps_segment_sources_through_file_and_byte_entries(self):
        path = SAMPLES / "media_rules.wav"
        with media_server() as (config, requests):
            reports = (
                ingestion.convert_file(path, source="录音", task="transcribe", config=config),
                ingestion.convert_bytes(
                    path.read_bytes(), format="wav", source="录音", task="transcribe", config=config,
                ),
                handoff.adapt_result(import_module(
                    ingestion.__name__ + ".audioTranscriptionAndVideoUnderstanding",
                ).convert_file(path, source="录音", task="transcribe", config=config)),
            )
        self.assertEqual(len(requests), 3)
        self.assert_complete_reports_equal(reports)
        self.assertEqual(reports[0].status, "content")
        document = reports[0].documents[0]
        self.assertIn(TRANSCRIPT, document.body)
        self.assertTrue(document.requires_review)
        self.assertEqual(document.units[0].alignment, "unmapped")
        source = next(item for item in document.sources if item.kind == "media_segment")
        self.assertEqual(source.locator["time_precision"], "segment")
        self.assertEqual(source.locator["start_seconds"], 0)
        self.assertGreater(source.locator["end_seconds"], 0)

    def test_video_uncertainty_keeps_complete_reports_and_segment_review(self):
        path = SAMPLES / "media_uncertain.mp4"
        text, note = "终点被截断，无法确认审批人。", "缺少终点"
        kwargs = {
            "source": "培训画面", "task": "video", "question": MEDIA_QUESTION,
            "media_id": "审批培训", "media_version": "录制二",
        }
        identity = {"business_id": "审批课程", "version": "业务三"}
        with media_server(video=video_reply(text, "uncertain", [note])) as (config, requests):
            reports = (
                ingestion.convert_file(path, config=config, **kwargs, **identity),
                ingestion.convert_bytes(path.read_bytes(), format="mp4", config=config, **kwargs, **identity),
            )
            native = media.convert_file(path, config=config, **kwargs)
            native_bytes = media.convert_bytes(path.read_bytes(), format="mp4", config=config, **kwargs)
            self.assertEqual(native, native_bytes)
            self.assertEqual(native.status, "uncertain", native.error)
            reports += (handoff.adapt_result(native, **identity), handoff.adapt_result(native_bytes, **identity))
            self.assertEqual(len(requests), 4)
        report = self.assert_complete_reports_equal(reports)
        self.assertEqual(report.status, "uncertain")
        document = report.documents[0]
        self.assertEqual(document.body, native.text)
        self.assertEqual((document.business_id, document.version), ("审批课程", "业务三"))
        self.assertEqual(document.metadata, {"task": "video", "question": MEDIA_QUESTION})
        self.assertTrue(document.requires_review)
        unit, = document.units
        self.assertEqual((unit.kind, unit.text, unit.status), ("video", text, "uncertain"))
        self.assertEqual(unit.alignment, "unmapped")
        self.assertIsNone(unit.body_span)
        self.assertEqual((unit.metadata["requested_model"], unit.metadata["response_model"],
                          unit.metadata["prompt_version"], unit.metadata["review_notes"]),
                         ("step-5-preview", "step-5-preview-actual", "video-v1", [note]))
        source, = [item for item in document.sources if item.id in unit.source_ids]
        segment, = native.segments
        self.assertEqual((source.locator["start_seconds"], source.locator["end_seconds"]),
                         (segment.start_seconds, segment.end_seconds))
        self.assertEqual((source.locator["media_id"], source.locator["media_version"],
                          source.locator["sha256"], source.locator["time_precision"]),
                         ("审批培训", "录制二", native.source.sha256, "segment"))
        review, = [item for item in document.diagnostics if item.unit_id == unit.id]
        self.assertEqual((review.code, review.message, review.source_id, review.document_id),
                         ("model_uncertainty", note, source.id, document.id))

    def test_combined_media_keeps_empty_audio_and_uncertain_video_in_complete_reports(self):
        path = SAMPLES / "video_extra_delayed.mp4"
        text, note = "终点被截断，无法确认审批人。", "缺少终点"
        kwargs = {
            "source": "培训录制", "task": "both", "media_id": "审批培训", "media_version": "录制二",
            "options": media.ProcessingOptions(audio_segment_seconds=2.5, video_segment_seconds=2),
        }
        identity = {"business_id": "审批课程", "version": "业务三"}
        with media_server(asr={"text": ""}, video=video_reply(text, "uncertain", [note])) as (config, requests):
            reports = (
                ingestion.convert_file(path, config=config, **kwargs, **identity),
                ingestion.convert_bytes(path.read_bytes(), format="mp4", config=config, **kwargs, **identity),
            )
            native = media.convert_file(path, config=config, **kwargs)
            native_bytes = media.convert_bytes(path.read_bytes(), format="mp4", config=config, **kwargs)
            self.assertEqual(native, native_bytes)
            self.assertEqual(native.status, "uncertain", native.error)
            self.assertEqual([item.status for item in native.segments],
                             ["no_text", "uncertain", "no_text", "uncertain", "no_text"])
            self.assertEqual(native.review_issues, [
                "媒体派生文字尚待对照同一版本原音视频核验。",
                "时间仅定位实际处理片段，不是逐句或逐词时间。",
            ])
            self.assertEqual(native.warnings, [
                "同步 ASR 不提供说话人区分；speaker 保持未知。",
                "部分或全部片段未取得可用转写，不证明原媒体没有语音。",
                "视频模型可能遗漏短暂画面或动作；画面解释不能替代原视频证据。",
            ])
            before, request_count = copy.deepcopy(native), len(requests)
            with patch("pathlib.Path.open", side_effect=AssertionError("handoff read input")), \
                    patch("http.client.HTTPConnection.request", side_effect=AssertionError("handoff requested HTTP")):
                reports += (handoff.adapt_result(native, **identity),)
            self.assertEqual(native, before)
            self.assertEqual(len(requests), request_count)
        report = self.assert_complete_reports_equal(reports)
        self.assertEqual(report.status, "uncertain")
        document = report.documents[0]
        self.assertEqual(document.body, f"[1.250–3.250 秒 · 画面信息]\n{text}\n\n[3.250–5.250 秒 · 画面信息]\n{text}")
        self.assertEqual((document.business_id, document.version), ("审批课程", "业务三"))
        self.assertEqual(document.metadata, {"task": "both", "question": None})
        self.assertTrue(document.requires_review)
        root = document.sources[0]
        self.assertEqual((root.locator["media_id"], root.locator["media_version"],
                          root.locator["audio_stream_index"], root.locator["sha256"]),
                         ("审批培训", "录制二", 1,
                          "1690dcf6a6910eb3e7f6501a6ac06f97adf2340a309ceaa86084949071821d7c"))
        sources = {source.id: source for source in document.sources}
        for unit in document.units:
            self.assertEqual(unit.alignment, "unmapped")
            self.assertIsNone(unit.body_span)
            source, = [sources[source_id] for source_id in unit.source_ids]
            self.assertEqual(source.locator["sha256"], root.locator["sha256"])
            if unit.kind == "audio":
                self.assertEqual((unit.text, unit.status), ("", "no_text"))
            else:
                self.assertEqual((unit.status, unit.metadata["requested_model"],
                                  unit.metadata["response_model"], unit.metadata["prompt_version"]),
                                 ("uncertain", "step-5-preview", "step-5-preview-actual", "video-v1"))
                review, = [item for item in document.diagnostics if item.unit_id == unit.id]
                self.assertEqual((review.code, review.message, review.source_id),
                                 ("model_uncertainty", note, source.id))

    def test_zip_preserves_partial_success_inventory_and_container_identity(self):
        path = SAMPLES / "zip_members.zip"
        reports = (
            ingestion.convert_file(path, source="资料包", business_id="集合", version="v2"),
            ingestion.convert_bytes(
                path.read_bytes(), format=" .ZIP ", source="资料包",
                business_id="集合", version="v2",
            ),
            handoff.adapt_result(import_module(
                ingestion.__name__ + ".8_zipContainers",
            ).convert_file(path, source="资料包"), business_id="集合", version="v2"),
        )
        report = self.assert_complete_reports_equal(reports)
        self.assertEqual(report.status, "partial_success")
        self.assertEqual(report.metadata["container"]["business_id"], "集合")
        self.assertTrue(report.metadata["members"])
        for document in report.documents:
            self.assertIsNone(document.business_id)
            self.assertIsNone(document.version)

    def test_zip_still_uses_hosted_documents(self):
        path = SAMPLES / "zip_document_pdf.zip"
        parser = import_module(ingestion.__name__ + ".8_zipContainers")
        with document_server() as service:
            options = {"parser_options": {"document": {"mineru": service.config}}}
            reports = (
                ingestion.convert_file(path, source="托管资料包", **options),
                ingestion.convert_bytes(
                    path.read_bytes(), format="zip", source="托管资料包", **options,
                ),
            )
            native = parser.convert_file(path, source="托管资料包", **options)
            network_before = copy.deepcopy((service.requests, service.uploads, service.polls))
            before = copy.deepcopy(native)
            with patch("pathlib.Path.open", side_effect=AssertionError("handoff read input")), \
                    patch("http.client.HTTPConnection.request", side_effect=AssertionError("handoff requested HTTP")):
                reports += (handoff.adapt_result(native),)
            self.assertEqual(native, before)
            self.assertEqual((service.requests, service.uploads, service.polls), network_before)
        report = self.assert_complete_reports_equal(reports)
        self.assertEqual(report.status, "success", report.to_dict())
        self.assertEqual(len(service.requests), 3)
        self.assertEqual(report.documents[0].body, SERVICE_MARKDOWN)
        self.assertTrue(report.documents[0].requires_review)

    def test_handoff_uses_only_the_native_zip_after_its_input_disappears(self):
        parser = import_module(ingestion.__name__ + ".8_zipContainers")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "资料.zip"
            path.write_bytes((SAMPLES / "zip_members.zip").read_bytes())
            native = parser.convert_file(path, source="持久来源")
        self.assertFalse(path.exists())
        before = copy.deepcopy(native)
        with patch("pathlib.Path.open", side_effect=AssertionError("handoff read input")), \
                patch("http.client.HTTPConnection.request", side_effect=AssertionError("handoff requested HTTP")):
            report = handoff.adapt_result(native, business_id="容器", version="v2")
        self.assertEqual(native, before)
        self.assertEqual(report.status, "partial_success")
        self.assertEqual(report.metadata["container"]["business_id"], "容器")
        self.assertTrue(all(document.business_id is None for document in report.documents))


if __name__ == "__main__":
    unittest.main()
