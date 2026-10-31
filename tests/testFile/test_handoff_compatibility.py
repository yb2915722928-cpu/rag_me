"""Public import and report contracts for canonical and legacy handoff paths."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
PREFIX = "app.modules.1_documentIngestionAndParsing."
OLD = PREFIX + "9_unifiedOutputAndChunkingHandoff"
NEW = PREFIX + "unifiedDocumentHandoff"


class HandoffCompatibilityTests(unittest.TestCase):
    def test_fresh_import_orders_preserve_all_existing_modules_and_public_objects(self):
        script = r'''
from importlib import import_module
import json
import sys
import warnings

old_name, new_name, first = sys.argv[1:]
exports = ["adapt_result", "export_json", "BodySpan", "ContentUnit", "Diagnostic",
           "Document", "HandoffReport", "IdAllocator", "Source"]
modules = {
    "__init__": exports,
    "models": exports[2:],
    "diagnostics": ["Diagnostic"],
    "dispatch": ["adapt_result", "adapt_validated_result", "TextWebResult", "PdfWordResult",
                 "HostedDocumentResult", "TableResult", "StructuredResult", "ImageResult",
                 "MediaResult", "ZipResult"],
    "text_web": ["TextWebResult", "adapt_text_web"],
    "documents": ["PdfWordResult", "HostedDocumentResult", "adapt_pdf_word", "adapt_hosted_document"],
    "tables": ["TableResult", "adapt_tables"],
    "derived": ["ImageResult", "MediaResult", "adapt_image", "adapt_media"],
    "structured": ["StructuredResult", "adapt_structured"],
    "zip_container": ["ZipResult", "adapt_zip"],
    "hosted_documents": ["DocumentResult", "adapt_hosted_document"],
}
with warnings.catch_warnings(record=True) as observed:
    warnings.simplefilter("always")
    import_module(first)
    old, new = import_module(old_name), import_module(new_name)
    assert old.__all__ == new.__all__ == exports
    for name in exports:
        assert getattr(old, name) is getattr(new, name), name
    for suffix, names in modules.items():
        legacy = import_module(old_name + "." + suffix)
        canonical = import_module(new_name + "." + suffix)
        for name in names:
            assert getattr(legacy, name) is getattr(canonical, name), (suffix, name)
    for name in exports[2:]:
        assert getattr(new, name).__module__ == new_name + ".models", name
    assert not observed, [str(item.message) for item in observed]
text = import_module(new_name.rsplit(".", 1)[0] + ".2_textAndWebContent")
native = text.convert_bytes(b"original body\n", format="txt", source="memory:compat")
expected = new.adapt_result(native, business_id="business", version="v2").to_dict()
assert old.adapt_result(native, business_id="business", version="v2").to_dict() == expected
assert expected["documents"][0]["body"] == "original body\n"
print(json.dumps({"modules": len(modules), "warnings": len(observed)}))
'''
        for suffix in ("", ".__init__", ".models", ".dispatch", ".derived", ".hosted_documents"):
            for first in (OLD + suffix, NEW + suffix):
                with self.subTest(first=first):
                    process = subprocess.run(
                        [sys.executable, "-c", script, OLD, NEW, first], cwd=ROOT,
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertEqual(json.loads(process.stdout), {"modules": 11, "warnings": 0})


if __name__ == "__main__":
    unittest.main()
