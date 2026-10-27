import importlib
from pathlib import Path
import tempfile
import unittest


presentations = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
SAMPLES = Path(__file__).parent / "testFile"


class StructuredXmlTests(unittest.TestCase):
    def test_refund_xml_has_distinct_branches_and_ordered_steps(self):
        path = SAMPLES / "xml_refund_rules.xml"
        result = presentations.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.markdown, "```xml\n" + path.read_bytes().decode("utf-8") + "\n```\n")
        self.assertIn('<rule order_type="普通订单"><owner>客服</owner>', result.markdown)
        self.assertIn('<rule order_type="企业订单" amount_max_inclusive="10000"><owner>企业财务</owner>', result.markdown)
        self.assertIn('<rule order_type="企业订单" amount_gt="10000"><owner>企业专属负责人</owner>', result.markdown)
        nodes = {source.node_path: source for source in result.sources}
        self.assertEqual(len(result.sources), 20)
        self.assertEqual(nodes["/refund[1]"].parent_path, None)
        for branch in (1, 2, 3):
            path = f"/refund[1]/rule[{branch}]"
            self.assertEqual(nodes[path].parent_path, "/refund[1]")
            self.assertEqual(nodes[f"{path}/owner[1]"].parent_path, path)
            self.assertEqual(
                [node.node_path for node in result.sources if node.parent_path == f"{path}/steps[1]"],
                [f"{path}/steps[1]/step[{index}]" for index in range(1, 5 if branch == 3 else 4)],
            )

    def test_xml_namespaces_mixed_content_comments_attributes_and_parent_paths(self):
        path = SAMPLES / "xml_relationships.xml"
        result = presentations.convert_bytes(path.read_bytes(), format="xml", source="mixed-upload.xml")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.markdown, "```xml\n" + path.read_bytes().decode("utf-8") + "\n```\n")
        self.assertIn('note="&quot;保留&quot;"', result.markdown)
        self.assertIn("普通订单<owner>客服</owner>核验后退款<!--归属注释-->", result.markdown)
        self.assertIn("金额 <em>10000</em> 元以下；<![CDATA[大于10000 <企业> & 专属]]>。", result.markdown)
        self.assertIn('<?workflow preserve="yes"?>\r\n', result.markdown)
        root = "/%7Burn%3Arefund%3Arules%7Drules[1]"
        branch = "%7Burn%3Arefund%3Arules%7Dbranch"
        owner = "%7Burn%3Arefund%3Arules%7Downer"
        corporate = "%7Bhttps%3A%2F%2Fexample.invalid%2Frefund%2Fcorporate%7D"
        other = "%7Burn%3Arefund%3Aother%7Downer"
        note = "%7Burn%3Arefund%3Arules%7Dnote"
        emphasis = "%7Burn%3Arefund%3Arules%7Dem"
        self.assertEqual(
            [(source.node_path, source.parent_path) for source in result.sources],
            [
                (root, None),
                (f"{root}/{branch}[1]", root),
                (f"{root}/{branch}[1]/{owner}[1]", f"{root}/{branch}[1]"),
                (f"{root}/{branch}[2]", root),
                (f"{root}/{branch}[2]/{corporate}owner[1]", f"{root}/{branch}[2]"),
                (f"{root}/{branch}[2]/{other}[1]", f"{root}/{branch}[2]"),
                (f"{root}/{branch}[2]/owner[1]", f"{root}/{branch}[2]"),
                (f"{root}/{corporate}branch[1]", root),
                (f"{root}/{corporate}branch[1]/{corporate}owner[1]", f"{root}/{corporate}branch[1]"),
                (f"{root}/{corporate}branch[1]/{corporate}owner[2]", f"{root}/{corporate}branch[1]"),
                (f"{root}/{note}[1]", root),
                (f"{root}/{note}[1]/{emphasis}[1]", f"{root}/{note}[1]"),
            ],
        )
        self.assertEqual(result.source, presentations.Source("mixed-upload.xml", "xml"))
        self.assertTrue(all(source.kind == "xml_element" and source.node_type == "element" for source in result.sources))
        self.assertTrue(all(source.markdown_start is None and source.markdown_end is None for source in result.sources))
        self.assertFalse(result.requires_review)

    def test_xml_fence_does_not_end_inside_raw_content(self):
        path = SAMPLES / "xml_fenced.xml"
        result = presentations.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.markdown, "`````xml\n" + path.read_bytes().decode("utf-8") + "\n`````\n")
        self.assertEqual([source.node_path for source in result.sources], ["/note[1]"])

    def test_bom_declaration_and_explicit_encodings_follow_shared_precedence(self):
        for filename, explicit, codec in (
            ("xml_utf8_bom.xml", None, "utf-8-sig"),
            ("xml_utf8_bom.xml", "utf-8", "utf-8"),
            ("xml_utf16_le_bom.xml", None, "utf-16"),
            ("xml_utf16_be_bom.xml", None, "utf-16"),
            ("xml_utf32_le_bom.xml", None, "utf-32"),
            ("xml_utf32_be_bom.xml", None, "utf-32"),
            ("xml_utf16_le_declaration.xml", None, "utf-16-le"),
            ("xml_utf16_be_declaration.xml", None, "utf-16-be"),
            ("xml_utf32_le_declaration.xml", None, "utf-32-le"),
            ("xml_utf32_be_declaration.xml", None, "utf-32-be"),
            ("xml_gb18030_declaration.xml", None, "gb18030"),
            ("xml_latin1_declaration.xml", None, "iso8859-1"),
            ("xml_explicit_over_declaration.xml", "GB18030", "gb18030"),
            ("xml_bom_over_declaration.xml", None, "utf-8-sig"),
            ("xml_utf16_le_bom.xml", "utf-16-le", "utf-16-le"),
            ("xml_utf16_be_bom.xml", "utf-16-be", "utf-16-be"),
        ):
            for entry in ("file", "bytes"):
                with self.subTest(filename=filename, explicit=explicit, entry=entry):
                    path = SAMPLES / filename
                    if entry == "file":
                        result = presentations.convert_file(path, encoding=explicit)
                    else:
                        result = presentations.convert_bytes(
                            path.read_bytes(), format="xml", source=str(path), encoding=explicit,
                        )

                    self.assertTrue(result.success, result.error)
                    self.assertEqual(result.encoding, codec)
                    self.assertEqual(result.warnings, [])
                    self.assertEqual(result.source, presentations.Source(str(path), "xml"))
                    self.assertEqual(result.markdown, "```xml\n" + path.read_bytes().decode(codec) + "\n```\n")
                    self.assertEqual([source.node_path for source in result.sources], ["/refund[1]", "/refund[1]/rule[1]"] if "latin1" not in filename else ["/note[1]"])

    def test_unavailable_declaration_warns_and_preserves_original_xml(self):
        path = SAMPLES / "xml_unknown_declaration.xml"
        result = presentations.convert_file(path)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.encoding, "utf-8")
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("unknown-structured-codec", result.warnings[0])
        self.assertEqual(result.markdown, "```xml\n" + path.read_bytes().decode("utf-8") + "\n```\n")
        self.assertNotIn(result.warnings[0], result.markdown)

    def test_invalid_xml_fails_without_partial_sources_and_keeps_diagnostics(self):
        for filename in (
            "xml_mismatched_tags.xml", "xml_multiple_roots.xml", "xml_unbound_prefix.xml",
            "xml_duplicate_attribute.xml", "xml_external_entity.xml", "xml_empty.xml",
            "xml_bom_only.xml", "xml_invalid_gb18030.xml",
        ):
            for entry in ("file", "bytes"):
                with self.subTest(filename=filename, entry=entry):
                    path = SAMPLES / filename
                    if entry == "file":
                        result = presentations.convert_file(path)
                    else:
                        result = presentations.convert_bytes(path.read_bytes(), format="xml", source=str(path))

                    self.assertFalse(result.success)
                    self.assertIsNone(result.markdown)
                    self.assertEqual(result.sources, [])
                    self.assertEqual(result.source, presentations.Source(str(path), "xml"))
                    self.assertIn("Invalid XML", result.error)
                    self.assertIsNotNone(result.encoding)
                    self.assertFalse(result.requires_review)
                    if filename == "xml_invalid_gb18030.xml":
                        self.assertEqual(len(result.warnings), 2)
                        self.assertIn("unknown-structured-codec", result.warnings[0])
                        self.assertIn("Encoding automatically", result.warnings[1])
                    else:
                        self.assertEqual(result.warnings, [])

    def test_strict_xml_decoding_failure_has_no_body_or_sources(self):
        for filename, encoding in (
            ("xml_truncated_utf16.xml", None),
            ("xml_gb18030_declaration.xml", "utf-8"),
            ("xml_utf16_le_bom.xml", "utf-8"),
            ("xml_utf8_bom.xml", "unknown-structured-codec"),
        ):
            with self.subTest(filename=filename, encoding=encoding):
                result = presentations.convert_file(SAMPLES / filename, encoding=encoding)

                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                self.assertIsNone(result.encoding)
                self.assertEqual(result.warnings, [])
                self.assertIn("Decoding failed", result.error)

    def test_failed_declared_encoding_warns_before_utf8_fallback(self):
        path = SAMPLES / "xml_failed_declaration.xml"
        for entry in ("file", "bytes"):
            with self.subTest(entry=entry):
                if entry == "file":
                    result = presentations.convert_file(path)
                else:
                    result = presentations.convert_bytes(path.read_bytes(), format="xml", source=str(path))

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.encoding, "utf-8")
                self.assertEqual(len(result.warnings), 1)
                self.assertIn("Declared encoding 'ASCII' could not decode text", result.warnings[0])
                self.assertEqual(result.markdown, "```xml\n" + path.read_bytes().decode("utf-8") + "\n```\n")
                self.assertNotIn(result.warnings[0], result.markdown)
                self.assertEqual(result.source, presentations.Source(str(path), "xml"))
                self.assertEqual([source.node_path for source in result.sources], ["/refund[1]", "/refund[1]/rule[1]"])

    def test_xml_file_format_override_and_bytes_keep_normalized_source(self):
        path = SAMPLES / "xml_refund_override.txt"
        options = dict(format=" .XML ", source="uploaded-refund", encoding="UTF-8")
        from_file = presentations.convert_file(path, **options)
        from_bytes = presentations.convert_bytes(path.read_bytes(), **options)

        self.assertTrue(from_file.success, from_file.error)
        self.assertEqual(from_file, from_bytes)
        self.assertEqual(from_file.source, presentations.Source("uploaded-refund", "xml"))
        self.assertEqual(from_file.encoding, "utf-8")
        self.assertEqual(from_file.markdown, "```xml\n" + path.read_bytes().decode("utf-8") + "\n```\n")
        self.assertEqual(from_file.warnings, [])
        inferred = presentations.convert_file(SAMPLES / "xml_refund_rules.xml")
        self.assertEqual(inferred.source, presentations.Source(str(SAMPLES / "xml_refund_rules.xml"), "xml"))
        self.assertEqual(from_file.sources, inferred.sources)
        unsupported = presentations.convert_file(path)
        self.assertFalse(unsupported.success)
        self.assertIn("Unsupported format", unsupported.error)
        self.assertIsNone(unsupported.markdown)
        self.assertEqual(unsupported.sources, [])

    def test_xml_export_preserves_utf8_body_and_original_line_endings(self):
        for filename in ("xml_relationships.xml", "xml_gb18030_declaration.xml", "xml_unknown_declaration.xml"):
            with self.subTest(filename=filename):
                result = presentations.convert_file(SAMPLES / filename, source="uploaded-xml")
                self.assertTrue(result.success, result.error)

                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "refund.md"
                    self.assertEqual(presentations.export_markdown(result, output), output)
                    self.assertEqual(output.read_bytes(), result.markdown.encode("utf-8"))
                    self.assertFalse(output.read_bytes().startswith(b"\xef\xbb\xbf"))
                    self.assertNotIn(result.source.location, result.markdown)
                    for warning in result.warnings:
                        self.assertNotIn(warning, result.markdown)
                    with self.assertRaises(OSError):
                        presentations.export_markdown(result, Path(directory))

    def test_failed_xml_cannot_create_or_overwrite_export(self):
        failures = [
            presentations.convert_file(SAMPLES / "missing.xml"),
            presentations.convert_file(SAMPLES / "xml_invalid_gb18030.xml"),
            presentations.convert_file(SAMPLES / "xml_gb18030_declaration.xml", encoding="utf-8"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.md"
            existing.write_bytes(b"existing body")
            missing = Path(directory) / "missing.md"
            for result in failures:
                self.assertFalse(result.success)
                self.assertIsNone(result.markdown)
                self.assertEqual(result.sources, [])
                for output in (existing, missing):
                    with self.subTest(error=result.error, output=output):
                        with self.assertRaises(ValueError):
                            presentations.export_markdown(result, output)
                self.assertEqual(existing.read_bytes(), b"existing body")
                self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
