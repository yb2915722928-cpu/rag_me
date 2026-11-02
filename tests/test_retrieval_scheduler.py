"""Public bounded scheduler behavior; authored test-first, NOT RUN (#87)."""
import importlib
import threading
import unittest

scheduling = importlib.import_module("app.modules.4_retrievalAndFusion.scheduler")
budgets = importlib.import_module("app.modules.4_retrievalAndFusion.deadline")


class SchedulerTests(unittest.TestCase):
    def test_hung_worker_keeps_capacity_and_late_value_is_discarded(self):
        release = threading.Event()
        started = threading.Event()
        scheduler = scheduling.BoundedScheduler(1)
        def stuck(remaining):
            started.set()
            release.wait(2)
            return "late evidence"
        try:
            results = scheduler.run([stuck, lambda remaining: "queued"],
                                    remaining=budgets.Deadline(.05), route_timeout=.01,
                                    max_concurrency=1)
            self.assertTrue(started.is_set())
            self.assertEqual([item.status for item in results], ["timeout", "not_executed"])
            self.assertTrue(all(item.value is None for item in results))
            next_results = scheduler.run([lambda remaining: "new"],
                                         remaining=budgets.Deadline(.02), route_timeout=1,
                                         max_concurrency=1)
            self.assertEqual(next_results[0].status, "not_executed")
        finally:
            release.set()
            scheduler.close()

    def test_success_and_failure_remain_distinct_in_input_order(self):
        scheduler = scheduling.BoundedScheduler(2)
        def fail(remaining):
            raise RuntimeError("backend failed")
        try:
            results = scheduler.run([lambda remaining: [], fail, lambda remaining: ["hit"]],
                                    remaining=budgets.Deadline(2), route_timeout=1,
                                    max_concurrency=2)
            self.assertEqual([item.status for item in results], ["completed", "failed", "completed"])
            self.assertEqual(results[0].value, [])
            self.assertIsInstance(results[1].error, RuntimeError)
        finally:
            scheduler.close()

    def test_expired_queue_does_not_start_backend(self):
        instant = [0.0]
        remaining = budgets.Deadline(1, clock=lambda: instant[0])
        instant[0] = 2.0
        scheduler = scheduling.BoundedScheduler(1)
        try:
            result = scheduler.run([lambda budget: self.fail("must not start")],
                                   remaining=remaining, route_timeout=1, max_concurrency=1)
            self.assertEqual(result[0].status, "not_executed")
        finally:
            scheduler.close()
