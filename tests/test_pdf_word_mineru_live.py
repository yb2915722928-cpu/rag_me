import dataclasses
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import time
import unittest

from bs4 import BeautifulSoup


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
)
SAMPLES = Path(__file__).parent / "testFile"


@unittest.skipUnless(os.environ.get("MINERU_LIVE_TEST") == "1",
                     "Explicit MINERU_LIVE_TEST=1 and MINERU_API_TOKEN required")
class MinerULiveAcceptanceTests(unittest.TestCase):
    def test_real_scan_preserves_rules_table_relationships_and_two_page_sources(self):
        path = SAMPLES / "pdf_scanned_maintenance_table.pdf"
        started = time.perf_counter()
        result = content.convert_file(
            path, source=path.name, mineru=content.MinerUConfig(language="en"),
        )
        elapsed = time.perf_counter() - started
        evidence = {
            "input": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "model_version": "vlm", "language": "en", "seconds": round(elapsed, 3),
            "result": dataclasses.asdict(result),
        }
        target = os.environ.get("MINERU_LIVE_EVIDENCE")
        if target:
            Path(target).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assertTrue(result.success, result.error)
        normalized = re.sub(r"[^a-z0-9]", "", result.markdown.lower())
        for statement in (
            "Equipment Maintenance", "Disconnect power before maintenance.",
            "Do not service while power is on.", "Inspect every 30 days.",
            "Restart after inspection.", "Temperature must not exceed 60 C.",
        ):
            self.assertIn(re.sub(r"[^a-z0-9]", "", statement.lower()), normalized)
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            for row in BeautifulSoup(result.markdown, "html.parser").find_all("tr")
        ]
        self.assertIn(["Equipment", "Interval"], rows)
        self.assertIn(["Pump", "Monthly"], rows)
        self.assertIn(["Valve", "Quarterly"], rows)
        self.assertLess(result.markdown.index("Disconnect"), result.markdown.index("<table"))
        self.assertLess(result.markdown.index("<table"), result.markdown.index("Restart"))
        self.assertEqual([s.pdf_page_number for s in result.sources], [1, 2])
        first, second = result.sources
        self.assertIn("<table", result.markdown[first.markdown_start:first.markdown_end])
        self.assertIn("60", result.markdown[second.markdown_start:second.markdown_end])
        self.assertNotIn("Temperature", result.markdown[first.markdown_start:first.markdown_end])


if __name__ == "__main__":
    unittest.main()
