import importlib
import json
from pathlib import Path
import tempfile
import unittest


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)
SAMPLES = Path(__file__).parent / "testFile"


class JsonConversionTests(unittest.TestCase):
    def test_legacy_encoding_keeps_chinese_and_excludes_warnings_from_export(self):
        path = SAMPLES / "json_gb18030.json"

        for encoding in (None, "GB18030"):
            with self.subTest(encoding=encoding):
                result = content.convert_file(
                    path, encoding=encoding, source="legacy-upload.json"
                )

                self.assertTrue(result.success, result.error)
                self.assertIsNone(result.error)
                if encoding is None:
                    self.assertTrue(result.warnings)
                    self.assertIn(result.encoding, " ".join(result.warnings))
                else:
                    self.assertEqual(result.encoding, "gb18030")
                    self.assertEqual(result.warnings, [])
                with tempfile.TemporaryDirectory() as directory:
                    output = content.export_markdown(result, Path(directory) / "legacy.md")
                    exported = output.read_bytes()

                self.assertEqual(exported, result.markdown.encode("utf-8"))
                self.assertFalse(exported.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r", exported)
                decoded = exported.decode("utf-8")
                self.assertNotIn(result.source.location, decoded)
                for warning in result.warnings:
                    self.assertNotIn(warning, decoded)
                value = json.loads(
                    decoded.removeprefix("```json\n").removesuffix("\n```\n")
                )
                self.assertEqual(value["标题"], "地理资料")
                self.assertIn("长江流经武汉，黄河流经兰州。", value["正文"])
                self.assertIn("北京是中国的首都，故宫位于北京市中心。", value["正文"])

    def test_wrong_explicit_json_encoding_fails_without_body_or_export(self):
        path = SAMPLES / "json_gb18030.json"

        result = content.convert_file(path, encoding="utf-8")

        self.assertFalse(result.success)
        self.assertIsNone(result.markdown)
        self.assertIn("decoding", result.error.lower())
        self.assertIn("utf-8", result.error)
        self.assertEqual(result.source, content.Source(str(path), "json"))
        self.assertEqual(result.warnings, [])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed.md"
            with self.assertRaises(ValueError):
                content.export_markdown(result, output)
            self.assertFalse(output.exists())

    def test_bytes_keep_array_order_nested_values_and_exact_value_types(self):
        path = SAMPLES / "json_types.json"

        result = content.convert_bytes(
            path.read_bytes(), format="json", source="types-upload.json"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source, content.Source("types-upload.json", "json"))
        self.assertTrue(result.markdown.startswith("```json\n"))
        self.assertTrue(result.markdown.endswith("\n```\n"))
        body = result.markdown.removeprefix("```json\n").removesuffix("\n```\n")
        actual = json.loads(body)
        self.assertIs(type(actual), list)
        self.assertEqual(actual, json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(actual[0]["integer"], 9007199254740993)
        self.assertIs(type(actual[0]["integer"]), int)
        self.assertIs(type(actual[0]["fraction"]), float)
        self.assertEqual(actual[0]["exponent"], 1250.0)
        self.assertIs(actual[0]["enabled"], True)
        self.assertIs(actual[0]["disabled"], False)
        self.assertIsNone(actual[0]["missing"])
        self.assertEqual(actual[0]["城市"], "北京")
        self.assertEqual(actual[1][0], "first")
        self.assertIsNone(actual[1][1]["child"][0])
        self.assertIs(actual[1][1]["child"][1], False)
        self.assertIs(type(actual[1][1]["child"][2]), int)
        self.assertIs(type(actual[1][1]["child"][3]), float)
        self.assertEqual(actual[1][1]["child"][4], {"leaf": "末尾"})
        self.assertEqual(actual[2], '文本\n\t```json "引用" \\路径')
        for index, value_type in enumerate(
            (dict, list, str, int, int, float, bool, bool, type(None), dict, list)
        ):
            with self.subTest(index=index):
                self.assertIs(type(actual[index]), value_type)

    def test_scalar_and_empty_container_root_values_remain_valid_exportable_json(self):
        for kind, expected in (
            ("string", ""),
            ("integer", 9007199254740993),
            ("float", -1.25),
            ("true", True),
            ("false", False),
            ("null", None),
            ("empty_object", {}),
            ("empty_array", []),
        ):
            with self.subTest(kind=kind):
                result = content.convert_file(SAMPLES / f"json_root_{kind}.json")

                self.assertTrue(result.success, result.error)
                with tempfile.TemporaryDirectory() as directory:
                    output = content.export_markdown(result, Path(directory) / "root.md")
                    exported = output.read_text(encoding="utf-8")
                self.assertEqual(exported, result.markdown)
                self.assertTrue(exported.startswith("```json\n"))
                self.assertTrue(exported.endswith("\n```\n"))
                actual = json.loads(
                    exported.removeprefix("```json\n").removesuffix("\n```\n")
                )
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), type(expected))

    def test_utf8_bom_chinese_json_exports_only_body_for_file_and_bytes(self):
        path = SAMPLES / "json_utf8_bom.json"
        source = content.Source("upload-bom.json", "txt")

        for encoding, used_encoding in ((None, "utf-8-sig"), ("UTF-8", "utf-8")):
            for entry in ("file", "bytes"):
                with self.subTest(encoding=encoding, entry=entry):
                    options = dict(
                        format=".JSON", source=source, encoding=encoding, mode="full"
                    )
                    if entry == "file":
                        result = content.convert_file(path, **options)
                    else:
                        result = content.convert_bytes(path.read_bytes(), **options)

                    self.assertTrue(result.success, result.error)
                    self.assertIsNone(result.error)
                    self.assertEqual(result.encoding, used_encoding)
                    self.assertEqual(result.source, content.Source("upload-bom.json", "json"))
                    self.assertEqual(source.format, "txt")
                    self.assertEqual(result.warnings, [])
                    self.assertTrue(result.markdown.startswith("```json\n"))
                    self.assertTrue(result.markdown.endswith("\n```\n"))
                    body = result.markdown.removeprefix("```json\n").removesuffix("\n```\n")
                    self.assertEqual(
                        json.loads(body),
                        {
                            "城市": "北京",
                            "河流": ["长江", "黄河"],
                            "内嵌标记": "\ufeff保留",
                            "文本": "NaN Infinity -Infinity",
                        },
                    )
                    self.assertIn("北京", result.markdown)
                    self.assertFalse(body.startswith("\ufeff"))
                    with tempfile.TemporaryDirectory() as directory:
                        output = Path(directory) / "converted.md"
                        written = content.export_markdown(result, output)
                        exported = output.read_bytes()

                    self.assertEqual(written, output)
                    self.assertEqual(exported.decode("utf-8"), result.markdown)
                    self.assertFalse(exported.startswith(b"\xef\xbb\xbf"))
                    self.assertNotIn(b"\r", exported)
                    self.assertNotIn(source.location, exported.decode("utf-8"))

    def test_invalid_json_fails_without_body_and_cannot_create_or_replace_export(self):
        successful = content.convert_file(SAMPLES / "json_schema_2020_12.json")

        with tempfile.TemporaryDirectory() as directory:
            existing = content.export_markdown(successful, Path(directory) / "existing.md")
            original = existing.read_bytes()
            missing = Path(directory) / "missing.md"
            for filename in (
                "json_trailing_comma.json",
                "json_multiple_documents.json",
                "json_invalid_escape.json",
                "json_nan.json",
                "json_infinity.json",
                "json_negative_infinity.json",
                "json_empty.json",
                "json_whitespace.json",
            ):
                path = SAMPLES / filename
                for entry in ("file", "bytes"):
                    with self.subTest(filename=filename, entry=entry):
                        if entry == "file":
                            result = content.convert_file(path)
                        else:
                            result = content.convert_bytes(
                                path.read_bytes(), format="json", source=filename
                            )

                        self.assertFalse(result.success)
                        self.assertIsNone(result.markdown)
                        self.assertIn("json", result.error.lower())
                        self.assertEqual(result.encoding, "utf-8")
                        self.assertEqual(result.warnings, [])
                        self.assertEqual(result.source.format, "json")
                        for output in (existing, missing):
                            with self.assertRaises(ValueError):
                                content.export_markdown(result, output)
                        self.assertFalse(missing.exists())
                        self.assertEqual(existing.read_bytes(), original)

    def test_public_nested_json_file_becomes_complete_formatted_json_fence(self):
        path = SAMPLES / "json_schema_2020_12.json"

        result = content.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertIsNone(result.error)
        self.assertEqual(result.source, content.Source(str(path), "json"))
        self.assertEqual(result.encoding, "utf-8")
        self.assertEqual(result.warnings, [])
        self.assertTrue(result.markdown.startswith("```json\n"))
        self.assertTrue(result.markdown.endswith("\n```\n"))
        body = result.markdown.removeprefix("```json\n").removesuffix("\n```\n")
        self.assertGreater(len(body.splitlines()), 2)
        actual = json.loads(body)
        self.assertEqual(actual, json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(actual["type"], ["object", "boolean"])
        self.assertEqual(
            actual["allOf"],
            [
                {"$ref": "meta/core"},
                {"$ref": "meta/applicator"},
                {"$ref": "meta/unevaluated"},
                {"$ref": "meta/validation"},
                {"$ref": "meta/meta-data"},
                {"$ref": "meta/format-annotation"},
                {"$ref": "meta/content"},
            ],
        )
        self.assertIs(actual["properties"]["definitions"]["deprecated"], True)
        self.assertEqual(actual["properties"]["dependencies"]["default"], {})


if __name__ == "__main__":
    unittest.main()
