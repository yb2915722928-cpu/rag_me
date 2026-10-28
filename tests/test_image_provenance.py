import base64
from contextlib import contextmanager
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import threading
import unittest


images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
SAMPLES = Path(__file__).parent / "testFile"
MANIFEST = json.loads((SAMPLES / "image_provenance_samples.json").read_text(encoding="utf-8"))
HASHES = {sample["filename"]: sample["sha256"] for sample in MANIFEST["samples"]}
CROP = SAMPLES / "image_provenance_crop.png"
ORIGINAL = SAMPLES / "image_provenance_original.png"
TEXT = "付款条件\n金额超过 1 万元时，须负责人审批。\n未经批准不得付款。"


@contextmanager
def provenance_server(*, text=TEXT, status="content", http_status=200, image=CROP, extra=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            picture = request["messages"][0]["content"][1]["image_url"]["url"]
            raw = base64.b64decode(picture.split(";base64,")[1], validate=True)
            valid = self.path == "/v1/chat/completions" and raw == image.read_bytes()
            output = {"status": status, "text": text, "review_notes": []}
            reply = {"model": "step-5-preview-test", "choices": [{"finish_reason": "stop",
                     "message": {"content": json.dumps(output)}}]} | (extra or {})
            body = json.dumps(reply).encode()
            self.send_response(http_status if valid else 400)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield images.StepFunConfig(api_key="test-key", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                                   model="step-5-preview", timeout=1)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class ImageProvenanceTests(unittest.TestCase):
    def test_unknown_document_facts_stay_empty_and_whole_image_has_no_invented_subregion(self):
        with provenance_server(image=ORIGINAL) as config:
            result = images.convert_file(ORIGINAL, source="report-v9-page-99.png", task="ocr", config=config)
            unknown = images.convert_bytes(ORIGINAL.read_bytes(), format="png", source="unknown-parent",
                                           task="ocr", document=images.DocumentSource(), config=config)
        self.assertTrue(result.success, result.error)
        self.assertIsNone(result.source.document)
        self.assertIsNone(result.source.crop)
        self.assertEqual((result.source.width, result.source.height), (1200, 600))
        self.assertEqual(asdict(unknown.source.document), {
            "document_id": None, "business_version": None, "position": None,
        })

    def test_same_bytes_keep_distinct_document_positions_and_same_name_keeps_distinct_byte_versions(self):
        pdf = images.DocumentSource("policy-pdf", "business-release-A", images.DocumentPosition("pdf_page", 3))
        slide = images.DocumentSource("policy-deck", "business-release-B", images.DocumentPosition("slide", 3))
        with provenance_server() as config:
            first = images.convert_bytes(CROP.read_bytes(), format="png", source="same-name.png",
                                         task="ocr", document=pdf, config=config)
            second = images.convert_bytes(CROP.read_bytes(), format="png", source="same-name.png",
                                          task="ocr", document=slide, config=config)
        alternate = SAMPLES / "image_provenance_crop_v2.png"
        with provenance_server(image=alternate, text=TEXT.replace("1 万元", "2 万元")) as config:
            version = images.convert_bytes(alternate.read_bytes(), format="png", source="same-name.png",
                                           task="ocr", document=pdf, config=config)
        for result in (first, second, version):
            self.assertTrue(result.success, result.error)
        self.assertEqual(first.source.sha256, second.source.sha256)
        self.assertEqual(first.source.document, pdf)
        self.assertEqual(second.source.document, slide)
        self.assertNotEqual(first.source.document.position, second.source.document.position)
        self.assertEqual(version.source.sha256, HASHES[alternate.name])
        self.assertNotEqual(first.source.sha256, version.source.sha256)
        self.assertEqual(first.source.document.business_version, version.source.document.business_version)

    def test_normal_empty_and_service_or_protocol_failures_keep_document_and_crop(self):
        document = images.DocumentSource("payment-policy", "v1", images.DocumentPosition("pdf_page", 3))
        crop = images.CropMapping("source-image", 1200, 600, (120, 180, 1120, 440))
        for response, expected_status, error in (
            ({"text": "", "status": "no_text"}, "no_text", None),
            ({"http_status": 503}, "failed", "service_error"),
            ({"text": ""}, "failed", "protocol_error"),
        ):
            with self.subTest(response=response), provenance_server(**response) as config:
                file = images.convert_file(CROP, task="ocr", document=document, crop=crop, config=config)
                data = images.convert_bytes(CROP.read_bytes(), format="png", source=str(CROP), task="ocr",
                                            document=document, crop=crop, config=config)
            self.assertEqual(file, data)
            self.assertEqual(file.status, expected_status)
            self.assertEqual(file.error.code if file.error else None, error)
            self.assertEqual(file.text, "" if error is None else None)
            self.assertEqual(file.source.document, document)
            self.assertEqual(file.source.crop, crop)
            self.assertEqual(file.source.sha256, HASHES[CROP.name])
            self.assertEqual((file.source.width, file.source.height), (1000, 260))

    def test_read_decode_and_option_failures_keep_only_known_source_facts(self):
        document = images.DocumentSource("payment-policy", position=images.DocumentPosition("slide", 1))
        crop = images.CropMapping("source-image", 1200, 600, (120, 180, 1120, 440))
        missing = images.convert_file(SAMPLES / "image_provenance_absent.png", task="ocr", document=document, crop=crop)
        corrupt = images.convert_bytes(b"", format="png", source="broken-crop", task="ocr", document=document, crop=crop)
        invalid = images.convert_file(CROP, task="ocr", format="gif", document=document, crop=crop)
        for result, code in ((missing, "file_read_error"), (corrupt, "image_decode_error"), (invalid, "unsupported_format")):
            with self.subTest(code=code):
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, code)
                self.assertEqual(result.source.document, document)
                self.assertEqual(result.source.crop, crop)
                self.assertIsNone(result.source.width)
                self.assertIsNone(result.source.height)
                self.assertIsNone(result.text)
        self.assertIsNone(missing.source.sha256)
        self.assertIsNone(invalid.source.sha256)
        self.assertEqual(corrupt.source.sha256, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_declared_crop_requires_complete_in_bounds_pixel_mapping_at_entry(self):
        valid = {"original_image_id": "source-image", "original_width": 1200, "original_height": 600,
                 "bbox": (120, 180, 1120, 440)}
        cases = [{"is_cropped": True}, {"crop": {}}, {"crop": images.CropMapping()}]
        for field in valid:
            cases.append({"crop": images.CropMapping(**(valid | {field: None}))})
        for field, value in (
            ("original_image_id", " "), ("original_width", 0), ("original_height", True),
            ("bbox", (-1, 180, 1120, 440)), ("bbox", (120, 180, 1201, 440)),
            ("bbox", (120, 180, 1120, 601)), ("bbox", (120, 180, 120, 440)),
            ("bbox", (120, 440, 1120, 180)), ("bbox", (120, 180, 1120, 440.5)),
            ("bbox", (False, 180, 1120, 440)), ("bbox", (120, 180, 1120)),
        ):
            cases.append({"crop": images.CropMapping(**(valid | {field: value}))})
        cases.append({"is_cropped": "yes", "crop": images.CropMapping(**valid)})
        document = images.DocumentSource("payment-policy")
        for options in cases:
            with self.subTest(options=options):
                file = images.convert_file(CROP, source="known-crop", task="ocr", document=document, **options)
                data = images.convert_bytes(CROP.read_bytes(), format="png", source="known-crop",
                                            task="ocr", document=document, **options)
                for result in (file, data):
                    self.assertFalse(result.success)
                    self.assertEqual(result.error.code, "invalid_options")
                    self.assertEqual(result.source.location, "known-crop")
                    self.assertEqual(result.source.document, document)
                    self.assertIsNone(result.source.crop)
                    self.assertIsNone(result.source.width)
                    self.assertIsNone(result.text)

    def test_crop_maps_both_entries_to_original_region_without_replacing_input_hash_or_dimensions(self):
        crop = images.CropMapping("archive/payment-rules/source-image-01", 1200, 600, (120, 180, 1120, 440))
        document = images.DocumentSource("payment-policy", "approved-2026-10", images.DocumentPosition("pdf_page", 3))
        with provenance_server(extra={"source": {"document_id": "model-invented", "bbox": [0, 0, 1, 1]}}) as config:
            file = images.convert_file(CROP, task="ocr", document=document, crop=crop,
                                       is_cropped=True, config=config)
            data = images.convert_bytes(CROP.read_bytes(), format="png", source=str(CROP), task="ocr",
                                        document=document, crop=crop, config=config)
        self.assertTrue(file.success, file.error)
        self.assertEqual(file, data)
        self.assertEqual(file.text, TEXT)
        self.assertEqual(file.source.document, document)
        self.assertEqual(asdict(file.source.crop), {
            "original_image_id": "archive/payment-rules/source-image-01", "original_width": 1200,
            "original_height": 600, "bbox": (120, 180, 1120, 440),
        })
        self.assertEqual((file.source.width, file.source.height), (1000, 260))
        self.assertEqual(file.source.sha256, HASHES[CROP.name])
        self.assertNotEqual(file.source.sha256, HASHES[ORIGINAL.name])

    def test_invalid_document_metadata_fails_at_public_boundary_with_known_input_location(self):
        for document in (
            {"document_id": "payment-policy"},
            images.DocumentSource(document_id=" "),
            images.DocumentSource(business_version=4),
            images.DocumentSource(position={"kind": "pdf_page", "index": 3}),
            images.DocumentSource(position=images.DocumentPosition("page", 3)),
            images.DocumentSource(position=images.DocumentPosition("pdf_page", 0)),
            images.DocumentSource(position=images.DocumentPosition("slide", True)),
        ):
            with self.subTest(document=document):
                result = images.convert_file(ORIGINAL, source="known-upload", task="ocr", document=document)
                other = images.convert_bytes(ORIGINAL.read_bytes(), format="png", source="known-upload",
                                             task="ocr", document=document)
                for failed in (result, other):
                    self.assertFalse(failed.success)
                    self.assertEqual(failed.error.code, "invalid_options")
                    self.assertEqual(failed.source.location, "known-upload")
                    self.assertIsNone(failed.text)
                    self.assertIsNone(failed.source.width)

    def test_document_identity_business_version_and_typed_position_survive_both_entries(self):
        document = images.DocumentSource("payment-policy", "approved-2026-10",
                                         images.DocumentPosition("pdf_page", 3))
        with provenance_server(image=ORIGINAL) as config:
            file = images.convert_file(ORIGINAL, task="ocr", document=document, config=config)
            data = images.convert_bytes(ORIGINAL.read_bytes(), format="png", source=str(ORIGINAL),
                                        task="ocr", document=document, config=config)
        self.assertTrue(file.success, file.error)
        self.assertEqual(file, data)
        self.assertEqual(asdict(file.source.document), {
            "document_id": "payment-policy", "business_version": "approved-2026-10",
            "position": {"kind": "pdf_page", "index": 3},
        })
        self.assertEqual(file.source.sha256, HASHES[ORIGINAL.name])


if __name__ == "__main__":
    unittest.main()
