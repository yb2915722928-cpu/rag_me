import importlib
from pathlib import Path
import unittest
from unittest.mock import patch


zip_containers = importlib.import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
SAMPLES = Path(__file__).parent / "testFile"


class ZipBudgetTests(unittest.TestCase):
    def test_zero_remaining_budget_stops_next_member_but_not_exactly_completed_archive(self):
        result = zip_containers.convert_file(
            SAMPLES / "zip_budgets.zip", limits=zip_containers.ZipLimits(max_total_bytes=5),
        )
        self.assertEqual(result.members[0].result.markdown, "first")
        self.assertEqual(result.total_bytes_read, 5)
        self.assertEqual(result.stop_reason, "max_total_bytes")
        self.assertEqual(result.counts["unprocessed"], 2)

    def test_crc_failed_read_still_consumes_budget_and_can_stop_a_later_member(self):
        result = zip_containers.convert_file(
            SAMPLES / "zip_crc_budget.zip", limits=zip_containers.ZipLimits(max_total_bytes=70008),
        )

        self.assertEqual(result.status, "partial_success")
        self.assertEqual(result.members[1].status, "failed")
        self.assertIn("CRC", result.members[1].error)
        self.assertEqual(result.members[1].bytes_read, 70000)
        self.assertEqual(result.total_bytes_read, 70005)
        self.assertEqual(result.members[2].status, "unprocessed")
        self.assertEqual(result.stop_reason, "max_total_bytes")

    def test_deadline_before_first_member_never_reports_success(self):
        with patch("time.monotonic", side_effect=[0] + [10] * 20):
            result = zip_containers.convert_file(
                SAMPLES / "zip_budgets.zip", limits=zip_containers.ZipLimits(timeout_seconds=5),
            )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.counts, dict(total=4, success=0, failed=0, ignored=1, unprocessed=3))
        self.assertEqual(result.total_bytes_read, 0)
        self.assertEqual(result.stop_reason, "deadline_exceeded")

    def test_deadline_during_chunked_read_keeps_completed_content_and_spent_budget(self):
        with patch("time.monotonic", side_effect=[0] * 6 + [10] * 20):
            result = zip_containers.convert_file(
                SAMPLES / "zip_budgets.zip", limits=zip_containers.ZipLimits(timeout_seconds=5),
            )

        self.assertEqual(result.status, "partial_success")
        self.assertEqual(result.stop_reason, "deadline_exceeded")
        self.assertEqual([m.status for m in result.members], ["success", "unprocessed", "unprocessed", "ignored"])
        self.assertEqual(result.members[0].result.markdown, "first")
        self.assertIsNone(result.members[1].result)
        self.assertGreater(result.members[1].bytes_read, 0)
        self.assertLess(result.members[1].bytes_read, 100000)
        self.assertEqual(result.total_bytes_read, 5 + result.members[1].bytes_read)

    def test_total_budget_keeps_completed_members_and_marks_remaining_documents_unprocessed(self):
        result = zip_containers.convert_file(
            SAMPLES / "zip_budgets.zip", limits=zip_containers.ZipLimits(max_total_bytes=8),
        )

        self.assertEqual(result.status, "partial_success")
        self.assertEqual(result.stop_reason, "max_total_bytes")
        self.assertEqual(result.counts, dict(total=4, success=1, failed=0, ignored=1, unprocessed=2))
        self.assertEqual(result.members[0].result.markdown, "first")
        self.assertEqual(result.total_bytes_read, 5)
        for member in result.members[1:3]:
            self.assertEqual(member.reason, "max_total_bytes")
            self.assertIsNone(member.result)
            self.assertEqual(member.bytes_read, 0)
        exact = zip_containers.convert_file(
            SAMPLES / "zip_budgets.zip", limits=zip_containers.ZipLimits(max_total_bytes=100009),
        )
        self.assertTrue(exact.success)
        self.assertEqual(exact.total_bytes_read, 100009)

    def test_oversized_member_fails_without_preventing_smaller_members(self):
        result = zip_containers.convert_file(
            SAMPLES / "zip_budgets.zip", limits=zip_containers.ZipLimits(max_member_bytes=5),
        )

        self.assertEqual(result.status, "partial_success")
        self.assertEqual([member.status for member in result.members], ["success", "failed", "success", "ignored"])
        self.assertEqual(result.members[1].reason, "max_member_bytes")
        self.assertEqual(result.members[1].bytes_read, 0)
        self.assertEqual(result.members[2].result.markdown, "last")
        self.assertEqual(result.total_bytes_read, 9)
        self.assertIsNone(result.stop_reason)

    def test_archive_size_and_member_count_are_checked_before_any_member_is_parsed(self):
        path = SAMPLES / "zip_text.zip"
        data = path.read_bytes()
        for limits, code in (
            (zip_containers.ZipLimits(max_archive_bytes=len(data) - 1), "max_archive_bytes"),
            (zip_containers.ZipLimits(max_members=1), "max_members"),
        ):
            for result in (zip_containers.convert_file(path, limits=limits),
                           zip_containers.convert_bytes(data, source=str(path), limits=limits)):
                with self.subTest(code=code):
                    self.assertEqual(result.status, "failed")
                    self.assertEqual(result.stop_reason, code)
                    self.assertTrue(result.error)
                    self.assertEqual(result.members, [])
                    self.assertEqual(result.total_bytes_read, 0)
        accepted = zip_containers.convert_file(
            path, limits=zip_containers.ZipLimits(max_archive_bytes=len(data), max_members=2),
        )
        self.assertTrue(accepted.success)


if __name__ == "__main__":
    unittest.main()
