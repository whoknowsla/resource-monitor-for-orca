"""Runs blocking queries off Orca's main thread.

Sampling the processor, running nvidia-smi or nmcli, and querying a network
drive can each take a noticeable time. Doing that on Orca's main thread would
freeze speech, so jobs run on one background thread, in the order they were
requested, and their results come back through the GLib main loop.
"""

from __future__ import annotations

import functools
import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402  pylint: disable=wrong-import-position

_log = logging.getLogger(__name__)

# Holding a key down should not build up a long backlog of stale answers.
MAX_PENDING_JOBS = 3

Deliver = Callable[[Callable[[], None]], None]


def deliver_on_main_loop(callback: Callable[[], None]) -> None:
    """Runs callback on the GLib main loop, where Orca may be called safely."""

    def run() -> bool:
        callback()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(run)


class Worker:
    """A single background thread that runs jobs in order."""

    def __init__(self, deliver: Deliver = deliver_on_main_loop) -> None:
        self._deliver = deliver
        self._jobs: queue.SimpleQueue[tuple[Callable[[], Any], Callable[[Any], None]] | None] = (
            queue.SimpleQueue()
        )
        self._lock = threading.Lock()
        self._pending = 0
        self._thread: threading.Thread | None = None
        self._stopped = False

    def submit(self, job: Callable[[], Any], on_result: Callable[[Any], None]) -> bool:
        """Queues job; on_result later receives its return value on the main loop.

        Returns False, without queueing, when stopped or when too many jobs are waiting.
        """

        with self._lock:
            if self._stopped or self._pending >= MAX_PENDING_JOBS:
                return False
            self._pending += 1
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name="resource-monitor-worker",
                    daemon=True,
                )
                self._thread.start()
        self._jobs.put((job, on_result))
        return True

    def stop(self) -> None:
        """Stops accepting jobs and lets the thread finish. Does not wait for it."""

        with self._lock:
            self._stopped = True
        self._jobs.put(None)

    def _run(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            job, on_result = item
            try:
                result = job()
            except Exception:  # pylint: disable=broad-exception-caught
                # Jobs are expected to handle their own errors; keep the thread alive regardless.
                _log.exception("Resource Monitor: background job failed")
                result = None
            with self._lock:
                self._pending -= 1
                stopped = self._stopped
            if not stopped and result is not None:
                # Bind both now: delivery runs later, after this loop has moved on.
                self._deliver(functools.partial(on_result, result))
