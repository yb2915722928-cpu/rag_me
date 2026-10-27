import importlib
import json
from pathlib import Path
import unittest


presentations = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
text_content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)
SAMPLES = Path(__file__).parent / "testFile"


class StructuredJsonTests(unittest.TestCase):
    def test_explicit_json_format_overrides_a_text_extension(self):
        path = SAMPLES / "structured_json_override.txt"
        inferred = presentations.convert_file(path)
        overridden = presentations.convert_file(path, format=".JSON", source="renamed-upload")

        self.assertFalse(inferred.success)
        self.assertIn("Unsupported format: txt", inferred.error)
        self.assertTrue(overridden.success, overridden.error)
        self.assertEqual(overridden.source, presentations.Source("renamed-upload", "json"))
        self.assertEqual(
            overridden.markdown,
            presentations.convert_file(SAMPLES / "json_refund_rules.json").markdown,
        )

    def test_refund_conditions_owners_and_steps_stay_in_their_original_branches(self):
        result = presentations.convert_file(SAMPLES / "json_refund_rules.json")

        self.assertTrue(result.success, result.error)
        body = result.markdown.removeprefix("```json\n").removesuffix("\n```\n")
        rules = json.loads(body)["rules"]
        self.assertEqual(rules, [
            {
                "condition": {"order_type": "普通订单"}, "owner": "客服",
                "steps": ["提交退款申请", "客服核验订单", "原路退款"],
            },
            {
                "condition": {"order_type": "企业订单", "amount_max_inclusive": 10000},
                "owner": "企业财务",
                "steps": ["提交企业退款申请", "企业财务核验", "企业财务退款"],
            },
            {
                "condition": {"order_type": "企业订单", "amount_gt": 10000},
                "owner": "企业专属负责人",
                "steps": ["提交企业退款申请", "企业财务核验", "企业专属负责人审批", "企业财务执行退款"],
            },
        ])
        nodes = {source.node_path: source for source in result.sources}
        self.assertEqual(nodes["/rules/2/condition/amount_gt"].parent_path, "/rules/2/condition")
        self.assertEqual(nodes["/rules/2/owner"].parent_path, "/rules/2")
        self.assertEqual(nodes["/rules/1/owner"].parent_path, "/rules/1")
        self.assertEqual(
            [source.node_path for source in result.sources if source.parent_path == "/rules/2/steps"],
            ["/rules/2/steps/0", "/rules/2/steps/1", "/rules/2/steps/2", "/rules/2/steps/3"],
        )
        self.assertFalse(result.requires_review)

    def test_object_field_reordering_keeps_relationships_without_creating_business_steps(self):
        original = presentations.convert_file(SAMPLES / "json_refund_rules.json")
        reordered = presentations.convert_file(SAMPLES / "json_refund_reordered.json")

        self.assertTrue(original.success, original.error)
        self.assertTrue(reordered.success, reordered.error)
        original_body = original.markdown.removeprefix("```json\n").removesuffix("\n```\n")
        reordered_body = reordered.markdown.removeprefix("```json\n").removesuffix("\n```\n")
        self.assertEqual(json.loads(original_body), json.loads(reordered_body))
        self.assertEqual(
            {source.node_path: source for source in original.sources},
            {source.node_path: source for source in reordered.sources},
        )
        self.assertTrue(all(source.level is None for source in reordered.sources))

    def test_json_pointer_escaping_empty_keys_and_all_nodes_are_complete(self):
        result = presentations.convert_bytes(
            (SAMPLES / "structured_json_pointers.json").read_bytes(),
            format="json", source="pointer-upload.json",
        )

        self.assertTrue(result.success, result.error)
        nodes = {source.node_path: (source.parent_path, source.node_type) for source in result.sources}
        self.assertEqual(nodes, {
            "": (None, "object"),
            "/": ("", "object"),
            "//a~1b": ("/", "object"),
            "//a~1b/m~0n": ("//a~1b", "array"),
            "//a~1b/m~0n/0": ("//a~1b/m~0n", "number"),
            "//a~1b/m~0n/1": ("//a~1b/m~0n", "number"),
            "//a~1b/m~0n/2": ("//a~1b/m~0n", "boolean"),
            "//a~1b/m~0n/3": ("//a~1b/m~0n", "null"),
            "//a~1b/m~0n/4": ("//a~1b/m~0n", "object"),
            "//a~1b/m~0n/5": ("//a~1b/m~0n", "array"),
            "//a~1b/m~0n/6": ("//a~1b/m~0n", "string"),
            "//a~1b/m~0n/7": ("//a~1b/m~0n", "object"),
            "//a~1b/m~0n/7/企业~1退款~0": ("//a~1b/m~0n/7", "string"),
            "/~01": ("", "string"),
            "/0": ("", "string"),
        })
        self.assertEqual(len(result.sources), len(nodes))
        self.assertTrue(all(source.kind == "json_node" for source in result.sources))
        self.assertTrue(all(source.markdown_start is None and source.markdown_end is None for source in result.sources))
        body = result.markdown.removeprefix("```json\n").removesuffix("\n```\n")
        values = json.loads(body)[""]["a/b"]["m~n"]
        self.assertIs(type(values[0]), int)
        self.assertIs(type(values[1]), float)
        self.assertIs(values[2], False)
        self.assertIsNone(values[3])
        self.assertEqual(values[4:7], [{}, [], ""])

    def test_legal_scalar_and_empty_container_roots_have_a_source(self):
        for suffix, expected, node_type in (
            ("string", "", "string"), ("integer", 9007199254740993, "number"),
            ("float", -1.25, "number"), ("true", True, "boolean"),
            ("false", False, "boolean"), ("null", None, "null"),
            ("empty_object", {}, "object"), ("empty_array", [], "array"),
        ):
            with self.subTest(root=suffix):
                result = presentations.convert_file(SAMPLES / f"json_root_{suffix}.json")

                self.assertTrue(result.success, result.error)
                body = result.markdown.removeprefix("```json\n").removesuffix("\n```\n")
                value = json.loads(body)
                self.assertEqual(value, expected)
                self.assertIs(type(value), type(expected))
                self.assertEqual(result.sources, [presentations.ContentSource(
                    kind="json_node", node_path="", parent_path=None, node_type=node_type,
                )])

    def test_json_public_entries_match_existing_converter_for_fixed_valid_and_bad_inputs(self):
        for filename, encoding in (
            ("json_refund_rules.json", None), ("structured_json_pointers.json", None),
            ("json_types.json", None), ("json_schema_2020_12.json", None),
            ("json_utf8_bom.json", None), ("json_utf8_bom.json", "utf-8"),
            ("json_gb18030.json", None), ("json_gb18030.json", "gb18030"),
            ("json_gb18030.json", "utf-8"),
            ("json_empty.json", None), ("json_whitespace.json", None),
            ("json_trailing_comma.json", None), ("json_multiple_documents.json", None),
            ("json_invalid_escape.json", None), ("json_nan.json", None),
            ("json_infinity.json", None), ("json_negative_infinity.json", None),
            ("structured_json_overflow.json", None),
            ("json_refund_invalid_gb18030.json", None),
        ):
            for entry in ("file", "bytes"):
                with self.subTest(filename=filename, encoding=encoding, entry=entry):
                    path = SAMPLES / filename
                    options = dict(format="json", source="upload.json", encoding=encoding)
                    if entry == "file":
                        actual = presentations.convert_file(path, **options)
                        legacy = text_content.convert_file(path, **options)
                    else:
                        actual = presentations.convert_bytes(path.read_bytes(), **options)
                        legacy = text_content.convert_bytes(path.read_bytes(), **options)

                    self.assertEqual(actual.success, legacy.success)
                    self.assertEqual(actual.markdown, legacy.markdown)
                    self.assertEqual(actual.error, legacy.error)
                    self.assertEqual(actual.encoding, legacy.encoding)
                    self.assertEqual(actual.warnings, legacy.warnings)
                    self.assertEqual(actual.source, presentations.Source("upload.json", "json"))
                    if not actual.success:
                        self.assertEqual(actual.sources, [])
                        self.assertFalse(actual.requires_review)

    def test_invalid_json_keeps_known_encoding_and_detection_warning(self):
        result = presentations.convert_file(SAMPLES / "json_refund_invalid_gb18030.json")

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertEqual(result.sources, [])
        self.assertIsNotNone(result.encoding)
        self.assertTrue(result.warnings)
        self.assertIn("Invalid JSON", result.error)

    def test_unknown_explicit_encoding_returns_a_decoding_failure_without_fallback(self):
        result = presentations.convert_file(
            SAMPLES / "json_refund_rules.json", encoding="unknown-structured-codec",
        )

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertEqual(result.sources, [])
        self.assertIsNone(result.encoding)
        self.assertEqual(result.warnings, [])
        self.assertIn("Decoding failed", result.error)
        self.assertIn("unknown-structured-codec", result.error)


if __name__ == "__main__":
    unittest.main()
