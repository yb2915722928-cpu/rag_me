"""Fresh-process behavior at the native-result -> handoff boundary."""
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "app.modules.1_documentIngestionAndParsing."
OLD = PREFIX + "9_unifiedOutputAndChunkingHandoff"
NEW = PREFIX + "unifiedDocumentHandoff"


class LazyHandoffTests(unittest.TestCase):
    def run_fresh(self, script, *arguments):
        process = subprocess.run(
            [sys.executable, "-c", script, *arguments], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_real_text_conversion_adaptation_and_export_do_not_initialize_other_parsers(self):
        script = r'''
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

first, prefix, old_name, new_name = sys.argv[1:]
import_module(first)
text = import_module(prefix + "2_textAndWebContent")
body = "Original body.  \nNo inferred offsets.\n"
native = text.convert_bytes(body.encode("utf-8"), format="txt", source="memory:text")
assert native.success, native.error
before = deepcopy(native)
expected = {
    "status": "success", "diagnostics": [], "metadata": {},
    "documents": [{
        "id": "document-1", "body": body, "body_format": "markdown", "status": "success",
        "business_id": " business ", "version": "v2", "requires_review": False,
        "sources": [{"id": "source-2", "kind": "document", "locator": {
            "location": "memory:text", "format": "txt", "encoding": None,
            "content_id": None, "content_location": None, "mime_index": None,
        }}],
        "units": [{"id": "unit-3", "kind": "document", "text": body,
                   "source_ids": ["source-2"], "body_span": None, "alignment": "document",
                   "parent_id": None, "status": "success", "metadata": {}}],
        "diagnostics": [], "structure": {}, "metadata": {"encoding": "utf-8"},
    }],
}
for module_name in (new_name, old_name):
    handoff = import_module(module_name)
    report = handoff.adapt_result(native, business_id=" business ", version="v2")
    assert report.to_dict() == expected, report.to_dict()
    with TemporaryDirectory() as directory:
        path = handoff.export_json(report, Path(directory) / "report.json")
        assert json.loads(path.read_bytes()) == expected
    assert native == before
root = import_module(prefix.rstrip("."))
assert root.convert_bytes(body.encode("utf-8"), format="txt", source="memory:text",
                          business_id=" business ", version="v2").to_dict() == expected
for name in ("openpyxl", "pptx", "PIL", "pypdf", "docx",
             prefix + "pdfAndDocxExtraction", prefix + "3_pdfAndWordExtraction",
             prefix + "4_tabularFileProcessing", prefix + "5_presentationsAndStructuredDocuments",
             prefix + "6_imageProcessing", prefix + "audioTranscriptionAndVideoUnderstanding",
             prefix + "7_audioTranscriptionAndVideoUnderstanding", prefix + "8_zipContainers"):
    assert not any(key == name or key.startswith(name + ".") for key in sys.modules), name
for package in (old_name, new_name):
    for adapter in ("documents", "tables", "derived", "structured", "zip_container", "hosted_documents"):
        assert package + "." + adapter not in sys.modules, (package, adapter)
'''
        for suffix in ("", ".__init__", ".models", ".dispatch"):
            for package in (OLD, NEW):
                with self.subTest(first=package + suffix):
                    self.run_fresh(script, package + suffix, PREFIX, OLD, NEW)


    def test_real_derived_and_hosted_adaptation_leaves_sibling_parsers_uninitialized(self):
        script = r'''
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

package, prefix, family = sys.argv[1:]
leaf = import_module(package + (".documents" if family == "hosted" else ".derived"))
samples = Path("tests/testFile")
if family == "image":
    from tests.test_image_ocr import images, RULES, step_server
    with step_server() as config:
        native = images.convert_file(samples / "image_ocr_rules.png", task="ocr", config=config)
    body, adapter_name = RULES, "adapt_image"
    forbidden = ["audioTranscriptionAndVideoUnderstanding", "7_audioTranscriptionAndVideoUnderstanding",
                 "pdfAndDocxExtraction", "3_pdfAndWordExtraction", "8_zipContainers"]
elif family == "media":
    from tests.test_audio_video import media, TRANSCRIPT, media_server
    with media_server() as (config, requests):
        native = media.convert_file(samples / "media_rules.wav", task="transcribe", config=config)
    assert len(requests) == 1, requests
    body, adapter_name = native.text, "adapt_media"
    assert TRANSCRIPT in body
    forbidden = ["6_imageProcessing", "pdfAndDocxExtraction", "3_pdfAndWordExtraction", "8_zipContainers"]
else:
    from http.server import BaseHTTPRequestHandler
    import time
    from tests.image_test_support import image_server
    hosted = import_module(prefix + "hosted_documents")
    budget = import_module(prefix + "archive_budget")
    archive = (samples / "zip_document_result.zip").read_bytes()
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def reply(self, value):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.reply({"code": 0, "data": {"batch_id": "batch", "file_urls": [base + "/upload"]}})
        def do_PUT(self):
            requests.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.reply(b"")
        def do_GET(self):
            requests.append(self.path)
            self.reply(archive if self.path.endswith("/result") else {
                "code": 0, "data": {"extract_result": [{"state": "done", "full_zip_url": base + "/result"}]},
            })
    with image_server(Handler) as base:
        native = hosted.convert_bytes(
            (samples / "pdf_digital_teaching.pdf").read_bytes(), format="pdf", source="hosted.pdf",
            limits=budget.ArchiveLimits(), deadline=time.monotonic() + 10,
            mineru={"token": "test-token", "api_base": base, "poll_interval": 0},
        )
    assert len(requests) == 4, requests
    body, adapter_name = "# Service original\n\nKeep **formatting**, order and trailing spaces.  \n", "adapt_hosted_document"
    forbidden = ["pdfAndDocxExtraction", "3_pdfAndWordExtraction", "6_imageProcessing",
                 "audioTranscriptionAndVideoUnderstanding", "7_audioTranscriptionAndVideoUnderstanding", "8_zipContainers"]
assert native.success, native.error
before = deepcopy(native)
handoff = import_module(package)
report = handoff.adapt_result(native, business_id="business", version="v2")
assert report.documents[0].body == body, report.to_dict()
assert report.documents[0].business_id == "business"
assert report.documents[0].version == "v2"
assert getattr(leaf, adapter_name)(native, handoff.IdAllocator(), business_id="business", version="v2").to_dict() == report.to_dict()
with TemporaryDirectory() as directory:
    assert json.loads(handoff.export_json(report, Path(directory) / "report.json").read_bytes()) == report.to_dict()
assert native == before
for name in ("openpyxl", "pptx", "pypdf", "docx", *[prefix + suffix for suffix in forbidden]):
    assert not any(key == name or key.startswith(name + ".") for key in sys.modules), name
if family != "image":
    assert not any(key == "PIL" or key.startswith("PIL.") for key in sys.modules)
'''
        for family in ("image", "media", "hosted"):
            for package in (OLD, NEW):
                with self.subTest(family=family, package=package):
                    self.run_fresh(script, package, PREFIX, family)

    def test_external_deep_subclasses_nominal_rejection_and_fixed_multiple_inheritance_precedence(self):
        script = r'''
from importlib import import_module
import sys
from types import SimpleNamespace

package, prefix = sys.argv[1:]
handoff = import_module(package)
text = import_module(prefix + "2_textAndWebContent")
native = text.convert_bytes(b"Original body\n", format="txt", source="memory:subclass")
class ExternalBase(text.ConversionResult):
    __module__ = "third_party.extensions"
class ExternalDeepResult(ExternalBase):
    __module__ = "third_party.extensions"
assert handoff.adapt_result(ExternalDeepResult(**vars(native))).to_dict() == handoff.adapt_result(native).to_dict()
spoofed_type = type("ConversionResult", (), {"__module__": text.ConversionResult.__module__})
spoofed = spoofed_type()
vars(spoofed).update(vars(native), success=True)
for impostor in (spoofed, SimpleNamespace(**vars(native), success=True)):
    try:
        handoff.adapt_result(impostor)
    except TypeError as error:
        assert str(error) == "Unsupported result type: " + type(impostor).__name__
    else:
        raise AssertionError("accepted a nominal lookalike")
    try:
        handoff.adapt_result(impostor, business_id=" ")
    except ValueError as error:
        assert str(error) == "business_id must be a nonempty string or None"
    else:
        raise AssertionError("identity did not take precedence")
images = import_module(prefix + "6_imageProcessing")
media = import_module(prefix + "audioTranscriptionAndVideoUnderstanding")
image = images.convert_bytes(b"invalid image", format="png", source="broken.png", task="ocr")
class MediaFirst(media.ConversionResult, images.ConversionResult):
    __module__ = "third_party.extensions"
class DeepMixedResult(MediaFirst):
    pass
mixed = DeepMixedResult.__new__(DeepMixedResult)
vars(mixed).update(vars(image))
assert type(mixed).__mro__.index(media.ConversionResult) < type(mixed).__mro__.index(images.ConversionResult)
assert handoff.adapt_result(mixed).to_dict() == handoff.adapt_result(image).to_dict()
assert handoff.adapt_result(mixed).documents[0].sources[0].kind == "image"
'''
        for package in (OLD, NEW):
            with self.subTest(package=package):
                self.run_fresh(script, package, PREFIX)


if __name__ == "__main__":
    unittest.main()
