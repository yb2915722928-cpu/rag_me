from dataclasses import asdict
from importlib import import_module
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest


BASE = "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
HANDOFF = "app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff"
content = import_module(BASE)
handoff = import_module(HANDOFF)
SAMPLES = Path(__file__).parent / "testFile"


class PdfWordModelContractTests(unittest.TestCase):
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

    def test_fresh_process_import_orders_share_one_model_class(self):
        script = '''
from importlib import import_module
from pathlib import Path
import json
import sys

base, handoff_name, order = json.loads(sys.argv[1])
for name in order:
    import_module(name)
package = import_module(base)
models = import_module(base + ".models")
for name in (base, base + ".pdf", base + ".docx", base + ".mineru"):
    module = import_module(name)
    for model in ("Source", "ContentSource", "ConversionResult"):
        assert getattr(module, model) is getattr(models, model), (name, model)
assert package.MinerUConfig is import_module(base + ".mineru").MinerUConfig
handoff = import_module(handoff_name)
for filename in ("pdf_digital_page_order.pdf", "docx_sections.docx"):
    native = package.convert_file(Path("tests/testFile") / filename)
    assert native.success, native.error
    assert type(native) is models.ConversionResult
    report = handoff.adapt_result(native)
    assert report.status == "success"
    assert report.documents[0].body == native.markdown
print("OK")
'''
        orders = (
            (BASE, BASE + ".pdf", BASE + ".docx", BASE + ".mineru", HANDOFF),
            (BASE + ".pdf", BASE + ".docx", BASE + ".mineru", BASE, HANDOFF),
            (BASE + ".mineru", BASE + ".models", BASE + ".pdf", BASE + ".docx", HANDOFF),
            (HANDOFF, BASE + ".models", BASE + ".docx", BASE + ".pdf", BASE + ".mineru", BASE),
        )
        for order in orders:
            with self.subTest(first_import=order[0]):
                process = subprocess.run(
                    [sys.executable, "-c", script, json.dumps((BASE, HANDOFF, order))],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(process.stdout.strip(), "OK")


if __name__ == "__main__":
    unittest.main()
