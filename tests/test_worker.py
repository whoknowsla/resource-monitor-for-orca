"""Tests for the background worker."""

import threading
import unittest

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.worker import MAX_PENDING_JOBS, Worker

TIMEOUT = 5


class CollectingDelivery:
    """Runs delivered callbacks at once and records that it did."""

    def __init__(self, expected):
        self.expected = expected
        self.results = []
        self.done = threading.Event()

    def deliver(self, callback):
        callback()

    def on_result(self, value):
        self.results.append(value)
        if len(self.results) == self.expected:
            self.done.set()


class WorkerTests(unittest.TestCase):
    def test_runs_jobs_in_order_and_delivers_results(self):
        delivery = CollectingDelivery(expected=3)
        worker = Worker(deliver=delivery.deliver)
        self.addCleanup(worker.stop)
        for value in ("a", "b", "c"):
            self.assertTrue(worker.submit(lambda value=value: value, delivery.on_result))
        self.assertTrue(delivery.done.wait(TIMEOUT))
        self.assertEqual(delivery.results, ["a", "b", "c"])

    def test_limits_backlog(self):
        release = threading.Event()
        delivery = CollectingDelivery(expected=MAX_PENDING_JOBS)
        worker = Worker(deliver=delivery.deliver)
        self.addCleanup(worker.stop)
        self.addCleanup(release.set)
        accepted = [
            worker.submit(lambda: release.wait(TIMEOUT) and "done", delivery.on_result)
            for _ in range(MAX_PENDING_JOBS + 2)
        ]
        self.assertEqual(accepted.count(True), MAX_PENDING_JOBS)
        release.set()
        self.assertTrue(delivery.done.wait(TIMEOUT))

    def test_failing_job_does_not_stop_the_thread(self):
        delivery = CollectingDelivery(expected=1)
        worker = Worker(deliver=delivery.deliver)
        self.addCleanup(worker.stop)

        def fail():
            raise RuntimeError("boom")

        with self.assertLogs("resource_monitor.worker", level="ERROR"):
            worker.submit(fail, delivery.on_result)
            worker.submit(lambda: "after", delivery.on_result)
            self.assertTrue(delivery.done.wait(TIMEOUT))
        self.assertEqual(delivery.results, ["after"])

    def test_stopped_worker_refuses_jobs(self):
        worker = Worker(deliver=lambda callback: callback())
        worker.stop()
        self.assertFalse(worker.submit(lambda: "x", lambda _value: None))


if __name__ == "__main__":
    unittest.main()
