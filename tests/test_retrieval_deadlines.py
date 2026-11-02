"""Deadline public contract; authored test-first, NOT RUN (#87)."""
import importlib
import unittest

budgets = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")


class DeadlineTests(unittest.TestCase):
    def test_child_and_later_processing_share_original_expiry(self):
        instant = [100.0]
        root = budgets.Deadline(10, clock=lambda: instant[0])
        instant[0] = 108.0
        child = root.child(5)
        self.assertEqual(child.remaining(), 2)
        instant[0] = 110.0
        self.assertEqual(root.remaining(), 0)
        with self.assertRaises(budgets.DeadlineExceeded):
            child.check()

    def test_root_cancel_propagates_but_route_cancel_is_local(self):
        root = budgets.Deadline(10)
        child, sibling = root.child(5), root.child(5)
        child.cancel()
        with self.assertRaises(budgets.DeadlineExceeded):
            child.check()
        sibling.check()
        root.cancel()
        with self.assertRaises(budgets.DeadlineExceeded):
            sibling.check()

    def test_invalid_timeouts_are_rejected_before_work(self):
        for value in (0, -1, float("nan"), float("inf"), True, "5"):
            with self.assertRaises(ValueError):
                budgets.Deadline(value)
