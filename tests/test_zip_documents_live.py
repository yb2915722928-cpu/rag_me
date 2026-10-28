"""仅 ZIP_DOCUMENT_LIVE_TEST=1 才加载显式环境文件并调用真实服务。"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unittest
from zipfile import ZipFile

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from tests.zip_document_support import SAMPLES, mineru, zip_containers


def normalized(value):
    return re.sub(r"[^\w]", "", value).casefold()


def table_rows(markdown):
    """服务可能输出 HTML 表或 Markdown 表，两种表示均按实际单元格核验。"""
    rows = [[cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            for row in BeautifulSoup(markdown, "html.parser").find_all("tr")]
    rows.extend([cell.strip() for cell in line.strip().strip("|").split("|")]
                for line in markdown.splitlines() if "|" in line)
    return [[normalized(cell) for cell in row] for row in rows]


def sanitized(value, token):
    """证据不记录任何 URL；正文和结构 JSON 中出现的 URL 同样脱敏。"""
    if isinstance(value, str):
        return re.sub(r"https?://\S+", "[redacted URL]", value.replace(token, "[redacted]"))
    if isinstance(value, list):
        return [sanitized(item, token) for item in value]
    if isinstance(value, dict):
        return {sanitized(key, token): sanitized(item, token) for key, item in value.items()}
    return value


def verification(case, specification, report):
    member = report["members"][0] if report["members"] else {}
    native = member.get("result") or {}
    markdown = native.get("markdown") or ""
    body = normalized(markdown)
    rows = table_rows(markdown)
    facts = {fact: normalized(fact) in body for fact in specification["facts"]}
    row_checks = {" / ".join(row): [normalized(cell) for cell in row] in rows
                  for row in specification["table_rows"]}
    pages = sorted({source["pdf_page_number"] for source in native.get("sources", [])
                    if source.get("pdf_page_number") is not None})
    checks = {"api_success": report["success"], "facts": all(facts.values()),
              "table_rows": all(row_checks.values()), "review_is_explicit": native.get("requires_review", False),
              "markdown_ranges_unavailable": all(source["markdown_start"] is None and source["markdown_end"] is None
                                                 for source in native.get("sources", []))}
    if specification["pdf_pages"]:
        checks["pdf_original_pages"] = pages == specification["pdf_pages"]
    if case in ("docx", "pptx", "xlsx"):
        checks["office_native_page_not_invented"] = all(source["pdf_page_number"] is None
                                                       for source in native.get("sources", []))
    if case in ("docx", "html", "mhtml"):
        before, after = (("维护前必须断电", "检查后重新启动") if case == "docx" else
                         ("Disconnect power before maintenance", "Restart after inspection"))
        table_start = markdown.lower().find("<table")
        if table_start < 0:
            table_start = markdown.find("|")
        checks["body_table_reading_order"] = (table_start >= 0 and normalized(before) in normalized(markdown[:table_start])
                                               and normalized(after) in normalized(markdown[table_start:]))
    if case == "pptx":
        blocks = native.get("structured_json", {}).get(native.get("content_list_file"), [])
        start_pages = {block.get("page_idx") for block in blocks
                       if "maintenancestart" in normalized(json.dumps(block))}
        schedule_pages = {block.get("page_idx") for block in blocks
                          if "maintenanceschedule" in normalized(json.dumps(block))}
        table_pages = {block.get("page_idx") for block in blocks
                       if block.get("type") == "table" and "pump" in normalized(json.dumps(block))}
        checks["observed_service_page_ownership"] = (start_pages == {0} and schedule_pages == {1}
                                                     and table_pages == {1})
    observations = {"facts": facts, "table_rows": row_checks, "pdf_pages": pages,
                    "service_page_indices": sorted({source["service_page_index"] for source in native.get("sources", [])
                                                    if source["service_page_index"] is not None}),
                    "json_shapes": {name: {"type": type(value).__name__,
                                           "first_fields": sorted(value[0]) if isinstance(value, list) and value
                                                           and isinstance(value[0], dict) else [],
                                           "fields": sorted(value) if isinstance(value, dict) else []}
                                    for name, value in native.get("structured_json", {}).items()}}
    if case == "xlsx":
        observations["native_location_conclusion"] = (
            "Worksheet/cell/merged-range/formula-cache provenance remains unavailable; raw JSON is retained for review. "
            "The constructed formula SUM(B3:B4) has no saved calculated cache; no result is inferred."
        )
        observations["merged_header_terms"] = {term: normalized(term) in body for term in ("Allowance", "Hotel", "Meals")}
        checks["merged_header_terms"] = all(observations["merged_header_terms"].values())
    return checks, observations


@unittest.skipUnless(os.environ.get("ZIP_DOCUMENT_LIVE_TEST") == "1",
                     "Explicit ZIP_DOCUMENT_LIVE_TEST=1 and STEP_ENV_FILE required")
class ZipDocumentLiveTests(unittest.TestCase):
    def test_representative_documents_through_public_zip_entry(self):
        env_file = os.environ.get("STEP_ENV_FILE")
        self.assertTrue(env_file and Path(env_file).is_file(), "STEP_ENV_FILE must identify the explicit environment file")
        load_dotenv(dotenv_path=env_file, override=False)
        token = os.environ.get("MINERU_API_TOKEN")
        self.assertTrue(token, "MINERU_API_TOKEN required")
        target = os.environ.get("ZIP_DOCUMENT_LIVE_EVIDENCE")
        self.assertTrue(target, "ZIP_DOCUMENT_LIVE_EVIDENCE must identify a new evidence file")
        target = Path(target)
        manifest = json.loads((SAMPLES / "zip_document_live_manifest.json").read_text(encoding="utf-8"))
        selected = os.environ.get("ZIP_DOCUMENT_LIVE_CASES")
        cases = [case.strip() for case in selected.split(",")] if selected else list(manifest)
        self.assertTrue(cases and set(cases) <= manifest.keys(), "Unknown or empty ZIP_DOCUMENT_LIVE_CASES")
        evidence = {"kind": "ZIP public-entry live acceptance", "started_at": datetime.now(timezone.utc).isoformat(),
                    "selected_cases": cases, "cases": []}
        with target.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(evidence, output, ensure_ascii=False, indent=2)
        options = {"document": {"mineru": mineru.MinerUConfig(language="en")}}
        for case in cases:
            with self.subTest(case=case):
                specification = manifest[case]
                path = SAMPLES / specification["archive"]
                with ZipFile(path) as archive:
                    source_digest = hashlib.sha256(archive.read(specification["member"])).hexdigest()
                archive_digest = hashlib.sha256(path.read_bytes()).hexdigest()
                checks = {"source_sha256": source_digest == specification["source_sha256"],
                          "archive_sha256": archive_digest == specification["archive_sha256"]}
                record = {"case": case, "input": specification["member"], "source_sha256": source_digest,
                          "archive_sha256": archive_digest, "verification": checks}
                evidence["cases"].append(record)
                target.write_text(json.dumps(sanitized(evidence, token), ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8", newline="\n")
                self.assertTrue(all(checks.values()), "Source sample digests changed")
                started = time.perf_counter()
                if case in ("pdf_digital", "pdf_scan", "html", "xlsx"):
                    result = zip_containers.convert_file(path, source=path.name, parser_options=options)
                    record["entry"] = "convert_file"
                else:
                    result = zip_containers.convert_bytes(path.read_bytes(), source=path.name, parser_options=options)
                    record["entry"] = "convert_bytes"
                report = result.to_dict()
                record.update(seconds=round(time.perf_counter() - started, 3), result=report)
                target.write_text(json.dumps(sanitized(evidence, token), ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8", newline="\n")
                quality, observations = verification(case, specification, report)
                checks.update(quality)
                record["observations"] = observations
                target.write_text(json.dumps(sanitized(evidence, token), ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8", newline="\n")
                self.assertTrue(all(checks.values()), f"{case}: failed checks: {[key for key, value in checks.items() if not value]}; see saved evidence")


if __name__ == "__main__":
    unittest.main()
