"""Fixed daemon workers, bounded admission, and no executor per query.

Uncooperative calls retain their slots until they actually exit. No Python thread
is killed; saturation makes later operations wait within their original budget.
Only accepted on-time results leave this module. close() never waits for a hung
backend. Workers are daemon threads so such calls cannot hold process shutdown.
"""
from __future__ import annotations

from dataclasses import dataclass
import queue
import threading

from .deadline import DeadlineExceeded, deadline_scope, positive_seconds


@dataclass(frozen=True)
class ScheduledResult:
    status: str
    value: object = None
    error: Exception | None = None


class _Call:
    def __init__(self, function, remaining, timeout):
        self.function, self.remaining, self.timeout = function, remaining, timeout
        self.lock = threading.Lock()
        self.started = False
        self.budget = None
        self.result = None
        self.abandoned = False
        self.finished = threading.Event()


class BoundedScheduler:
    def __init__(self, capacity=4):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("scheduler capacity must be a positive integer")
        self.capacity = capacity
        self._slots = threading.BoundedSemaphore(capacity)
        self._queue = queue.Queue(maxsize=capacity)
        self._changed = threading.Condition()
        self._closed = False
        self._threads = tuple(threading.Thread(target=self._worker, daemon=True,
                                               name=f"retrieval-{index}")
                              for index in range(capacity))
        for thread in self._threads:
            thread.start()

    def _worker(self):
        while True:
            try:
                call = self._queue.get(timeout=.05)
            except queue.Empty:
                if self._closed:
                    return
                continue
            try:
                with call.lock:
                    if call.abandoned or call.remaining.remaining() <= 0:
                        call.result = ScheduledResult("not_executed")
                        continue
                    call.started = True
                    call.budget = call.remaining.child(call.timeout)
                try:
                    with deadline_scope(call.budget):
                        value = call.function(call.budget)
                        call.budget.check()
                    result = ScheduledResult("completed", value)
                except DeadlineExceeded as exc:
                    result = ScheduledResult("timeout", error=exc)
                except Exception as exc:
                    result = ScheduledResult("failed", error=exc)
                with call.lock:
                    if not call.abandoned:
                        # Completion is stamped by the worker, not collector wakeup.
                        call.result = result if call.budget.remaining() > 0 else ScheduledResult("timeout")
            finally:
                call.finished.set()
                self._queue.task_done()
                self._slots.release()
                with self._changed:
                    self._changed.notify_all()

    def run(self, functions, *, remaining, route_timeout=5, max_concurrency=4):
        positive_seconds(route_timeout, "route_timeout")
        if (isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int)
                or not 1 <= max_concurrency <= self.capacity):
            raise ValueError("max_concurrency must be within scheduler capacity")
        calls = [_Call(function, remaining, route_timeout) for function in functions]
        results = [None] * len(calls)
        active = {}
        outstanding = []
        next_index = 0
        while next_index < len(calls) or active:
            for index, call in tuple(active.items()):
                with call.lock:
                    if call.result is not None:
                        results[index] = call.result
                    elif self._closed or remaining.remaining() <= 0 or (call.budget and call.budget.remaining() <= 0):
                        call.abandoned = True
                        if call.budget:
                            call.budget.cancel()
                        results[index] = ScheduledResult("timeout" if call.started else "not_executed")
                    else:
                        continue
                del active[index]
            if remaining.remaining() <= 0 or self._closed:
                for index in range(next_index, len(calls)):
                    results[index] = ScheduledResult("not_executed")
                next_index = len(calls)
            outstanding = [call for call in outstanding if not call.finished.is_set()]
            while next_index < len(calls) and len(outstanding) < max_concurrency:
                if not self._slots.acquire(blocking=False):
                    break
                call = calls[next_index]
                active[next_index] = call
                outstanding.append(call)
                self._queue.put_nowait(call)
                next_index += 1
            if next_index < len(calls) or active:
                timeout = min(.01, remaining.remaining())
                if timeout > 0:
                    with self._changed:
                        self._changed.wait(timeout)
        return tuple(results)

    def close(self):
        """Stop accepting work. Running calls are cooperatively bounded by adapters."""
        self._closed = True
        with self._changed:
            self._changed.notify_all()


_shared = None
_shared_lock = threading.Lock()


def shared_scheduler():
    """One lazily-created thread pool shared by service instances and requests."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = BoundedScheduler(32)
        return _shared
