import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = "app.modules.1_documentIngestionAndParsing.8_zipContainers"


class ZipCliTests(unittest.TestCase):
    def test_cli_applies_name_and_category_encoding_without_writing_member_paths(self):
        completed = subprocess.run(
            [sys.executable, "-m", MODULE, str(ROOT / "tests/testFile/zip_legacy_names.zip"),
             "--metadata-encoding", "gb18030", "--parser-options", '{"text":{"encoding":"utf-16"}}'],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["members"][0]["source"]["member_path"], "资料.txt")
        self.assertEqual(report["members"][0]["result"]["markdown"], "独立正文编码")
        self.assertFalse((ROOT / "资料.txt").exists())

    def test_cli_reports_full_partial_and_failed_results_with_stable_exit_codes(self):
        for name, code, status, extra in (
            ("zip_text.zip", 0, "success", []),
            ("zip_members.zip", 2, "partial_success", []),
            ("zip_corrupt.zip", 1, "failed", []),
            ("zip_budgets.zip", 2, "partial_success", ["--max-total-bytes", "8"]),
            ("zip_missing.zip", 1, "failed", []),
        ):
            with self.subTest(name=name):
                completed = subprocess.run(
                    [sys.executable, "-m", MODULE, str(ROOT / "tests" / "testFile" / name),
                     "--source", "CLI上传.zip", "--parser-options",
                     '{"document":{"unused_marker":"DO_NOT_ECHO_CONFIG"}}', *extra],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(completed.returncode, code, completed.stderr)
                self.assertEqual(completed.stderr, "")
                report = json.loads(completed.stdout)
                self.assertEqual(report["status"], status)
                self.assertEqual(report["source"], "CLI上传.zip")
                self.assertNotIn("DO_NOT_ECHO_CONFIG", completed.stdout)
                if status == "success":
                    self.assertEqual(report["members"][0]["result"]["markdown"], "ZIP 容器示例\n两行原文\n")
                    self.assertTrue(report["members"][0]["result"]["success"])
                if extra:
                    self.assertEqual(report["stop_reason"], "max_total_bytes")
                    self.assertEqual(report["counts"]["unprocessed"], 2)


if __name__ == "__main__":
    unittest.main()
