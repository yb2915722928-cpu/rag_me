from importlib import import_module
import unittest


ROOT = "app.modules.1_documentIngestionAndParsing"


class SharedTextCompatibilityTests(unittest.TestCase):
    def test_existing_decoding_module_reexports_shared_function(self):
        existing = import_module(ROOT + ".2_textAndWebContent.decoding")
        shared = import_module(ROOT + ".text_support")

        self.assertIs(existing.decode_bytes, shared.decode_bytes)

    def test_existing_json_module_reexports_shared_functions(self):
        existing = import_module(ROOT + ".2_textAndWebContent.json_content")
        shared = import_module(ROOT + ".text_support")

        for name in ("convert_json", "load_json", "render_json"):
            with self.subTest(function=name):
                self.assertIs(getattr(existing, name), getattr(shared, name))

    def test_existing_markdown_module_reexports_shared_function(self):
        existing = import_module(ROOT + ".2_textAndWebContent.markdown")
        shared = import_module(ROOT + ".text_support")

        self.assertIs(existing.normalize_markdown, shared.normalize_markdown)


if __name__ == "__main__":
    unittest.main()
