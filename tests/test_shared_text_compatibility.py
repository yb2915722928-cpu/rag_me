from importlib import import_module
import unittest


ROOT = "app.modules.1_documentIngestionAndParsing"


class SharedTextCompatibilityTests(unittest.TestCase):
    def test_existing_decoding_module_reexports_shared_function(self):
        existing = import_module(ROOT + ".2_textAndWebContent.decoding")
        shared = import_module(ROOT + ".text_support")

        self.assertIs(existing.decode_bytes, shared.decode_bytes)


if __name__ == "__main__":
    unittest.main()
