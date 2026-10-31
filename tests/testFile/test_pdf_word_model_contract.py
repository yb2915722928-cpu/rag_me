from dataclasses import asdict
from importlib import import_module
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest


BASE = "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
HANDOFF = "app.modules.1_documentIngestionAndParsing.unifiedDocumentHandoff"
content = import_module(BASE)
handoff = import_module(HANDOFF)
SAMPLES = Path(__file__).parent


class PdfWordModelContractTests(unittest.TestCase):
    def test_new_package_preserves_native_pdf_docx_and_complete_reports(self):
        renamed = import_module("app.modules.1_documentIngestionAndParsing.pdfAndDocxExtraction")
        ingestion = import_module("app.modules.1_documentIngestionAndParsing")
        for filename in ("pdf_digital_page_order.pdf", "docx_sections.docx"):
            with self.subTest(filename=filename):
                path = SAMPLES / filename
                options = {"source": "原生资料"}
                expected = content.convert_file(path, **options)
                self.assertTrue(expected.success, expected.error)
                native = renamed.convert_bytes(path.read_bytes(), format=path.suffix, **options)
                self.assertEqual(asdict(native), asdict(expected))
                self.assertIs(type(native), content.ConversionResult)
                report = handoff.adapt_result(native, business_id="文档", version="v2")
                self.assertEqual(report.to_dict(), handoff.adapt_result(
                    expected, business_id="文档", version="v2",
                ).to_dict())
                self.assertEqual(report.to_dict(), ingestion.convert_file(
                    path, business_id="文档", version="v2", **options,
                ).to_dict())

    def test_public_constructors_keep_field_order_defaults_and_success_semantics(self):
        source = content.Source("来源.pdf", "pdf")
        block = content.ContentSource(0, 3, 1, "text_layer")
        result = content.ConversionResult("正文\n", source, [block], ["需核验"])
        self.assertTrue(result.success)
        self.assertEqual(asdict(result), {
            "markdown": "正文\n", "source": {"location": "来源.pdf", "format": "pdf"},
            "sources": [{
                "markdown_start": 0, "markdown_end": 3, "pdf_page_number": 1,
                "extraction_method": "text_layer", "section_path": (),
                "body_block_number": None, "section_block_number": None,
                "block_type": None, "heading_level": None,
            }],
            "warnings": ["需核验"], "error": None,
        })
        for markdown, error, expected in (("", None, True), (None, None, False), ("正文", "", False)):
            with self.subTest(markdown=markdown, error=error):
                self.assertEqual(content.ConversionResult(markdown, source, error=error).success, expected)
        first = content.ConversionResult("正文", source)
        second = content.ConversionResult("正文", source)
        first.sources.append(block)
        first.warnings.append("仅当前结果")
        self.assertEqual(second.sources, [])
        self.assertEqual(second.warnings, [])
        self.assertIsNone(content.Source("来源").format)

    def test_pdf_and_docx_native_results_and_subclasses_keep_complete_public_handoff(self):
        class CustomResult(content.ConversionResult):
            pass

        for filename in ("pdf_digital_page_order.pdf", "docx_sections.docx"):
            with self.subTest(filename=filename):
                native = content.convert_file(SAMPLES / filename)
                self.assertTrue(native.success, native.error)
                self.assertIs(type(native), content.ConversionResult)
                self.assertIs(type(native.source), content.Source)
                self.assertTrue(all(type(source) is content.ContentSource for source in native.sources))
                custom = CustomResult(**vars(native))
                self.assertEqual(handoff.adapt_result(custom).to_dict(), handoff.adapt_result(native).to_dict())
                with self.assertRaisesRegex(TypeError, "Unsupported result type: SimpleNamespace"):
                    handoff.adapt_result(SimpleNamespace(**vars(native), success=True))

    def test_fresh_process_old_and_new_import_orders_share_modules_types_and_handoff(self):
        script = '''
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
import json
import sys
from types import SimpleNamespace

legacy, canonical, handoff_name, order = json.loads(sys.argv[1])
for name in order:
    import_module(name)
old = import_module(legacy)
new = import_module(canonical)
assert old is new
assert import_module(legacy + ".__init__") is new
models = import_module(canonical + ".models")
for suffix in ("", ".pdf", ".docx", ".mineru", ".models"):
    module = import_module(canonical + suffix)
    assert import_module(legacy + suffix) is module, suffix
    for name in ("Source", "ContentSource", "ConversionResult"):
        assert getattr(module, name) is getattr(models, name), (suffix, name)
        assert getattr(module, name).__module__ == canonical + ".models"
mineru = import_module(canonical + ".mineru")
shared = import_module(canonical.rsplit(".", 1)[0] + ".mineru_client")
assert old.MinerUConfig is new.MinerUConfig is mineru.MinerUConfig is shared.MinerUConfig
assert import_module(legacy + ".mineru").MinerUError is mineru.MinerUError is shared.MinerUError
assert import_module(legacy + ".mineru").MinerUClient is mineru.MinerUClient
handoff = import_module(handoff_name)
for filename in ("pdf_digital_page_order.pdf", "docx_sections.docx"):
    path = Path("tests/testFile") / filename
    native = new.convert_file(path, mineru=old.MinerUConfig(token=""))
    assert native.success, native.error
    assert type(native) is models.ConversionResult
    assert asdict(old.convert_file(path)) == asdict(native)
    report = handoff.adapt_result(native)
    assert report.status == "success"
    assert report.documents[0].body == native.markdown
    class CustomResult(old.ConversionResult):
        pass
    assert handoff.adapt_result(CustomResult(**vars(native))).to_dict() == report.to_dict()
    try:
        handoff.adapt_result(SimpleNamespace(**vars(native), success=True))
    except TypeError as exc:
        assert str(exc) == "Unsupported result type: SimpleNamespace"
    else:
        raise AssertionError("shape-only result was accepted")
print("OK")
'''
        canonical = "app.modules.1_documentIngestionAndParsing.pdfAndDocxExtraction"
        orders = []
        for suffix in ("", ".models", ".pdf", ".docx", ".mineru"):
            orders.extend(((BASE + suffix, canonical + suffix), (canonical + suffix, BASE + suffix)))
        orders.extend(((BASE + ".__init__", canonical), (HANDOFF, canonical, BASE + ".__init__")))
        for order in orders:
            with self.subTest(order=order):
                process = subprocess.run(
                    [sys.executable, "-c", script, json.dumps((BASE, canonical, HANDOFF, order))],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(process.stdout.strip(), "OK")


if __name__ == "__main__":
    unittest.main()
