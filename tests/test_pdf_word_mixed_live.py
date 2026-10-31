import dataclasses
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import re
import time
import unittest

from bs4 import BeautifulSoup
import pypdf


content = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.pdfAndDocxExtraction"
)
SAMPLES = Path(__file__).parent / "testFile"


@unittest.skipUnless(os.environ.get("MINERU_MIXED_LIVE_TEST") == "1",
                     "Explicit MINERU_MIXED_LIVE_TEST=1 and MINERU_API_TOKEN required")
class MixedPdfLiveAcceptanceTests(unittest.TestCase):
    def test_real_mixed_pdf_keeps_independent_facts_and_original_noncontiguous_page_sources(self):
        path = SAMPLES / "pdf_mixed_maintenance.pdf"
        started = time.perf_counter()
        result = content.convert_file(
            path, source=path.name, mineru=content.MinerUConfig(language="en"),
        )
        elapsed = time.perf_counter() - started
        evidence = {
            "input": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "input_bytes": path.stat().st_size,
            "input_pages": [
                {"pdf_page_number": number, "text_layer": page.extract_text(),
                 "image_count": len(page.images)}
                for number, page in enumerate(pypdf.PdfReader(path).pages, start=1)
            ],
            "expected_upload_mapping": {"0": 2, "1": 4},
            "model_version": "vlm", "language": "en", "enable_table": True,
            "python_version": platform.python_version(), "pypdf_version": pypdf.__version__,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "seconds": round(elapsed, 3),
            "result": dataclasses.asdict(result),
        }
        target = os.environ.get("MINERU_MIXED_LIVE_EVIDENCE")
        if target:
            with Path(target).open("w", encoding="utf-8", newline="\n") as output:
                json.dump(evidence, output, ensure_ascii=False, indent=2)
                output.write("\n")

        self.assertTrue(result.success, result.error)
        self.assertEqual([s.pdf_page_number for s in result.sources], [1, 2, 3, 4])
        self.assertEqual([s.extraction_method for s in result.sources],
                         ["text_layer", "mineru_api", "text_layer", "mineru_api"])
        pages = [result.markdown[s.markdown_start:s.markdown_end] for s in result.sources]
        self.assertEqual(pages[0], "Digital Intake\nAsset code: PUMP-A17.\nPrinted page 90\n")
        self.assertEqual(pages[2], "Digital Release\nTorque setting: 12 Nm.\nPrinted page 12\n")
        expected_facts = (
            ("Digital Intake", "Asset code: PUMP-A17."),
            ("Equipment Maintenance", "Disconnect power before maintenance.",
             "Do not service while power is on.", "Inspect every 30 days.",
             "Restart after inspection."),
            ("Digital Release", "Torque setting: 12 Nm."),
            ("Inspection Limits", "Temperature must not exceed 60 C."),
        )
        for page_index, facts in enumerate(expected_facts):
            for fact in facts:
                needle = re.sub(r"[^a-z0-9]", "", fact.lower())
                for actual_index, page in enumerate(pages):
                    normalized = re.sub(r"[^a-z0-9]", "", page.lower())
                    self.assertEqual(normalized.count(needle), int(page_index == actual_index), fact)
        self.assertEqual(result.markdown, "\n".join(pages))
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            for row in BeautifulSoup(pages[1], "html.parser").find_all("tr")
        ]
        self.assertIn(["Equipment", "Interval"], rows)
        self.assertIn(["Pump", "Monthly"], rows)
        self.assertIn(["Valve", "Quarterly"], rows)
        self.assertLess(pages[1].index("Disconnect"), pages[1].index("<table"))
        self.assertLess(pages[1].index("<table"), pages[1].index("Restart"))
        for warning in result.warnings:
            self.assertNotIn(warning, result.markdown)


if __name__ == "__main__":
    unittest.main()
