from io import BytesIO
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tests.zip_document_support import SAMPLES, SERVICE_MARKDOWN, document_server, mineru, zip_containers


class ZipDocumentTests(unittest.TestCase):
    def test_input_and_each_service_archive_have_independent_totals_including_discarded_artifacts(self):
        html = b"<html><body>Original input</body></html>"
        inputs = [("first.html", html), ("second.html", html), ("after.txt", b"Sibling survives")]
        artifacts = [("full.md", SERVICE_MARKDOWN.encode()),
                     ("main.html", b"<p>Independent service HTML</p>"),
                     ("images/discarded.png", b"x" * 600)]
        result_total = sum(len(data) for _, data in artifacts)
        input_total = sum(len(data) for _, data in inputs)
        self.assertLess(input_total, result_total)

        with document_server(result_bytes=_archive_bytes(artifacts)) as service:
            result = zip_containers.convert_bytes(
                _archive_bytes(inputs), source="independent.zip",
                limits=zip_containers.ZipLimits(max_total_bytes=result_total),
                parser_options={"document": {"mineru": service.config}},
            )

        self.assertTrue(result.success, result.to_dict())
        self.assertIsNone(result.stop_reason)
        self.assertEqual(result.total_bytes_read, input_total)
        self.assertEqual(service.uploads, [html, html])
        for member in result.members[:2]:
            self.assertEqual(member.result.markdown, SERVICE_MARKDOWN)
            self.assertEqual(member.result.html, "<p>Independent service HTML</p>")
            self.assertEqual(member.result.artifacts, [name for name, _ in artifacts])
        self.assertEqual(result.members[2].result.markdown, "Sibling survives")

    def test_crc_failure_in_discarded_service_artifact_discards_body_and_preserves_siblings(self):
        original = b"BINARY_CRC_FIXTURE_PAYLOAD"
        archive = _archive_bytes([
            ("full.md", SERVICE_MARKDOWN.encode()),
            ("generated_content_list.json", b'[{"type":"text","page_idx":0}]'),
            ("images/discarded.png", original),
        ])
        self.assertEqual(archive.count(original), 1)
        corrupt = archive.replace(original, b"binary_CRC_FIXTURE_PAYLOAD", 1)
        self.assertEqual(len(corrupt), len(archive))

        with document_server(result_bytes=corrupt) as service:
            result = zip_containers.convert_file(
                SAMPLES / "zip_document_pdf.zip",
                parser_options={"document": {"mineru": service.config}},
            )

        self.assertEqual(result.status, "partial_success")
        self.assertIsNone(result.stop_reason)
        failed = result.members[0]
        self.assertEqual(failed.reason, "parse_error")
        self.assertIn("CRC", failed.error)
        self.assertIsNone(failed.result.markdown)
        self.assertEqual(failed.result.artifacts, [])
        self.assertEqual(failed.result.structured_json, {})
        self.assertEqual(failed.result.sources, [])
        self.assertEqual(result.members[1].result.markdown, "Sibling survives")

    def test_deadline_while_expanding_a_downloaded_result_discards_incomplete_document(self):
        now = [0.0]

        def monotonic():
            value = now[0]
            if value:
                now[0] += 10.0
            return value

        with document_server(on_result=lambda: now.__setitem__(0, 250.0)) as service:
            with patch("time.monotonic", side_effect=monotonic):
                result = zip_containers.convert_file(
                    SAMPLES / "zip_document_live_pdf_digital.zip",
                    parser_options={"document": {"mineru": service.config}},
                )

        self.assertEqual(result.counts, dict(total=1, success=0, failed=0, ignored=0, unprocessed=1))
        self.assertEqual(result.stop_reason, "deadline_exceeded")
        self.assertIsNone(result.members[0].result)

    def test_archive_deadline_during_result_download_takes_precedence_over_unread_result_errors(self):
        path = SAMPLES / "zip_document_live_pdf_digital.zip"
        for result_name in ("zip_corrupt.zip", "zip_document_result_download.zip"):
            now = [0.0]
            with self.subTest(result_name=result_name), document_server(
                result_name=result_name, no_length=True,
                on_result=lambda: now.__setitem__(0, 301.0),
            ) as service:
                with patch("time.monotonic", side_effect=lambda: now[0]):
                    result = zip_containers.convert_bytes(
                        path.read_bytes(), source="deadline.zip",
                        limits=zip_containers.ZipLimits(max_archive_bytes=path.stat().st_size + 500),
                        parser_options={"document": {"mineru": service.config}},
                    )

                self.assertEqual(result.stop_reason, "deadline_exceeded")
                self.assertEqual(result.counts, dict(total=1, success=0, failed=0, ignored=0, unprocessed=1))
                self.assertIsNone(result.members[0].result)

    def test_archive_deadline_keeps_completed_results_and_stops_documents_but_ignores_metadata(self):
        path = SAMPLES / "zip_document_deadline.zip"
        for entry in ("file", "bytes"):
            now = [0.0]
            result_times = iter((250.0, 301.0))
            with self.subTest(entry=entry), document_server(
                on_result=lambda: now.__setitem__(0, next(result_times)),
            ) as service:
                with patch("time.monotonic", side_effect=lambda: now[0]):
                    options = {"document": {"mineru": service.config}}
                    result = (zip_containers.convert_file(path, parser_options=options) if entry == "file"
                              else zip_containers.convert_bytes(path.read_bytes(), source=path.name,
                                                                parser_options=options))

                self.assertEqual(result.counts, dict(total=9, success=2, failed=0, ignored=4, unprocessed=3))
                self.assertEqual(result.stop_reason, "deadline_exceeded")
                self.assertEqual(result.status, "partial_success")
                self.assertEqual(result.members[0].result.markdown, "Completed text")
                self.assertEqual(result.members[1].result.markdown, SERVICE_MARKDOWN)
                self.assertEqual([member.status for member in result.members],
                                 ["success", "success"] + ["unprocessed"] * 3 + ["ignored"] * 4)
                for member in result.members[2:5]:
                    self.assertEqual(member.reason, "deadline_exceeded")
                    self.assertIsNone(member.result)

    def test_deadline_in_single_pdf_result_is_unprocessed_without_a_later_member(self):
        now = [0.0]
        with document_server(on_result=lambda: now.__setitem__(0, 301.0)) as service:
            with patch("time.monotonic", side_effect=lambda: now[0]):
                result = zip_containers.convert_file(
                    SAMPLES / "zip_document_live_pdf_digital.zip",
                    parser_options={"document": {"mineru": service.config}},
                )

        self.assertEqual(result.counts, dict(total=1, success=0, failed=0, ignored=0, unprocessed=1))
        self.assertEqual(result.stop_reason, "deadline_exceeded")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.members[0].reason, "deadline_exceeded")
        self.assertIsNone(result.members[0].result)

    def test_digital_scan_and_mixed_pdf_upload_whole_fixed_members(self):
        manifest = json.loads((SAMPLES / "zip_document_live_manifest.json").read_text(encoding="utf-8"))
        for case in ("pdf_digital", "pdf_scan", "pdf_mixed"):
            specification = manifest[case]
            with self.subTest(case=case), document_server() as service:
                result = zip_containers.convert_file(
                    SAMPLES / specification["archive"],
                    parser_options={"document": {"mineru": service.config}},
                )
                self.assertTrue(result.success, result.to_dict())
                self.assertEqual(service.uploads, [(SAMPLES / specification["member"]).read_bytes()])
                self.assertEqual(result.members[0].result.markdown, SERVICE_MARKDOWN)

    def test_one_archive_can_preserve_each_document_kind_and_lightweight_sibling(self):
        with document_server() as service:
            result = zip_containers.convert_file(
                SAMPLES / "zip_documents.zip", source="all.zip",
                parser_options={"document": {"mineru": service.config}},
            )
        self.assertEqual(result.counts, {"total": 9, "success": 9, "failed": 0, "ignored": 0, "unprocessed": 0})
        self.assertEqual([member.result_kind for member in result.members],
                         ["document", "text"] + ["document"] * 7)
        self.assertEqual(len(service.uploads), 8)
        self.assertEqual(result.members[-1].result.source, "all.zip!/web/fallback.mht#9")

    def test_api_failures_and_missing_configuration_are_explicit_and_preserve_siblings(self):
        for failure in ("auth", "quota", "format", "apply-http", "invalid-json", "upload", "poll",
                        "failed", "timeout", "download", "missing-token"):
            with self.subTest(failure=failure), document_server(failure=failure) as service:
                if failure == "timeout":
                    service.config.max_wait = 0.01
                if failure == "missing-token":
                    service.config.token = ""
                result = zip_containers.convert_file(
                    SAMPLES / "zip_document_pdf.zip",
                    parser_options={"document": {"mineru": service.config}},
                )
                self.assertEqual(result.status, "partial_success")
                self.assertIsNone(result.stop_reason)
                self.assertEqual(result.members[0].status, "failed")
                self.assertEqual(result.members[0].reason, "parse_error")
                self.assertEqual(result.members[0].result_kind, "document")
                self.assertIsNone(result.members[0].result.markdown)
                self.assertTrue(result.members[0].error)
                self.assertEqual(result.members[1].result.markdown, "Sibling survives")
                encoded = json.dumps(result.to_dict())
                self.assertNotIn("test-token", encoded)
                self.assertNotIn("private.invalid", encoded)
                if failure == "missing-token":
                    self.assertIn("MINERU_API_TOKEN", result.members[0].error)
                    self.assertEqual(service.requests, [])

    def test_invalid_document_configuration_is_rejected_without_echoing_values(self):
        for config in ("DO_NOT_ECHO", {"token": 42}, {"unknown": "DO_NOT_ECHO"},
                       {"api_base": "DO_NOT_ECHO"}, {"max_wait": -1},
                       mineru.MinerUConfig(request_timeout=float("nan"))):
            with self.subTest(config_type=type(config).__name__):
                result = zip_containers.convert_file(
                    SAMPLES / "zip_document_pdf.zip", parser_options={"document": {"mineru": config}},
                )
                self.assertEqual(result.status, "partial_success")
                self.assertIn("Invalid document options", result.members[0].error)
                self.assertNotIn("DO_NOT_ECHO", json.dumps(result.to_dict()))

    def test_remote_result_download_members_and_expansion_obey_caller_limits(self):
        path = SAMPLES / "zip_document_pdf.zip"
        for fixture, limits, diagnostic in (
            ("zip_document_result_download.zip", zip_containers.ZipLimits(max_archive_bytes=path.stat().st_size + 500),
             "max_archive_bytes"),
            ("zip_document_result_many.zip", zip_containers.ZipLimits(max_members=2), "max_members"),
            ("zip_document_result_expanded.zip", zip_containers.ZipLimits(max_member_bytes=5000), "max_member_bytes"),
            ("zip_document_result_expanded.zip", zip_containers.ZipLimits(max_total_bytes=5000), "max_total_bytes"),
        ):
            with self.subTest(budget=diagnostic), document_server(result_name=fixture, no_length=True) as service:
                result = zip_containers.convert_bytes(
                    path.read_bytes(), source="limited.zip", limits=limits,
                    parser_options={"document": {"mineru": service.config}},
                )
                self.assertEqual(result.status, "partial_success")
                self.assertIn(diagnostic, result.members[0].error)
                self.assertIsNone(result.members[0].result.markdown)
                self.assertEqual(result.members[1].result.markdown, "Sibling survives")

    def test_invalid_service_artifacts_fail_the_document_without_partial_body_or_losing_siblings(self):
        for result_name, diagnostic in (
            ("zip_document_result_blank.zip", "full.md"),
            ("zip_document_result_missing_page.zip", "page_idx"),
            ("zip_document_result_bad_list.zip", "content_list"),
            ("zip_document_result_no_md.zip", "full.md"),
            ("zip_document_result_bad_json.zip", "JSON"),
            ("zip_document_result_v2_only.zip", "content_list"),
            ("zip_corrupt.zip", "ZIP"),
        ):
            with self.subTest(result_name=result_name), document_server(result_name=result_name) as service:
                result = zip_containers.convert_file(
                    SAMPLES / "zip_document_pdf.zip",
                    parser_options={"document": {"mineru": service.config}},
                )
            self.assertEqual(result.status, "partial_success")
            member = result.members[0]
            self.assertEqual(member.status, "failed")
            self.assertIn(diagnostic, member.error)
            self.assertIsNone(member.result.markdown)
            self.assertEqual(member.result.structured_json, {})
            self.assertEqual(member.result.sources, [])
            self.assertEqual(result.members[1].result.markdown, "Sibling survives")

    def test_html_aliases_and_selected_mhtml_use_html_model_and_accept_html_only_artifacts(self):
        with document_server() as service:
            result = zip_containers.convert_file(
                SAMPLES / "zip_document_web.zip", source="pages.zip",
                parser_options={"document": {"mineru": service.config}},
            )
        self.assertTrue(result.success, result.to_dict())
        for request in service.requests:
            self.assertEqual(request, {"files": [{"name": "document.html"}], "model_version": "MinerU-HTML"})
        self.assertEqual(len(service.uploads), 4)
        self.assertIn(b"Start chooses this shorter page.", service.uploads[2])
        self.assertNotIn(b"Unselected large frame", service.uploads[2])
        mhtml = result.members[2].result
        self.assertEqual(mhtml.main_html["content_id"], "<main-page>")
        self.assertEqual(mhtml.main_html["mime_index"], 2)
        self.assertEqual(mhtml.main_html["content_location"], "https://example.test/main")
        self.assertIn("largest", " ".join(result.members[3].result.warnings))
        for member in result.members:
            self.assertEqual(member.result.markdown, "# Remote article\n")
            self.assertEqual(member.result.html, "<h1>Remote article</h1>")
            self.assertEqual(member.result.structured_json, {})
            self.assertEqual(member.result.sources, [])
            self.assertEqual(member.result.requested_model, "MinerU-HTML")
            self.assertTrue(member.result.requires_review)

    def test_office_uploads_real_suffixes_and_does_not_invent_native_locations(self):
        with document_server() as service:
            result = zip_containers.convert_file(
                SAMPLES / "zip_document_office.zip",
                parser_options={"document": {"mineru": service.config}},
            )
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual([request["files"][0]["name"] for request in service.requests],
                         ["document.docx", "document.pptx", "document.xlsx"])
        self.assertEqual(service.uploads, [(SAMPLES / name).read_bytes() for name in
                                          ("docx_sections.docx", "pptx_refund.pptx", "xlsx_travel.xlsx")])
        for member in result.members:
            with self.subTest(format=member.format):
                native = member.result
                self.assertEqual(native.markdown, SERVICE_MARKDOWN)
                self.assertEqual(native.sources[0].service_page_index, 0)
                self.assertIsNone(native.sources[0].pdf_page_number)
                self.assertEqual(native.sources[0].page_origin, "service_page_unverified")
                self.assertIn("native", " ".join(native.review_items).lower())
                self.assertTrue(native.requires_review)

    def test_digital_pdf_defaults_to_api_and_keeps_original_markdown_and_structured_sources(self):
        path = SAMPLES / "zip_document_pdf.zip"
        with document_server() as service:
            options = {"document": {"mineru": service.config}}
            file_result = zip_containers.convert_file(path, source="upload.zip", parser_options=options)
            byte_result = zip_containers.convert_bytes(path.read_bytes(), source="upload.zip", parser_options=options)

        self.assertTrue(file_result.success, file_result.to_dict())
        self.assertEqual(file_result, byte_result)
        member = file_result.members[0]
        self.assertEqual(member.result_kind, "document")
        self.assertEqual(member.result.markdown, SERVICE_MARKDOWN)
        self.assertEqual(member.result.source, "upload.zip!/docs/manual.pdf#1")
        self.assertEqual(member.result.provider, "mineru")
        self.assertEqual(member.result.requested_model, "vlm")
        self.assertEqual(member.result.structured_json["output/generated_content_list.json"][0]["text"],
                         "Different structured text")
        self.assertIn("output/generated_content_list_v2.json", member.result.structured_json)
        self.assertEqual(member.result.sources[0].pdf_page_number, 1)
        self.assertEqual(member.result.sources[0].service_page_index, 0)
        self.assertIsNone(member.result.sources[0].markdown_start)
        self.assertIsNone(member.result.sources[0].markdown_end)
        self.assertTrue(member.result.requires_review)
        self.assertEqual(service.requests[0]["files"][0]["name"], "document.pdf")
        self.assertEqual(service.uploads, [(SAMPLES / "pdf_digital_teaching.pdf").read_bytes()] * 2)
        self.assertEqual(file_result.members[1].result.markdown, "Sibling survives")


def _archive_bytes(entries):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return stream.getvalue()


if __name__ == "__main__":
    unittest.main()
