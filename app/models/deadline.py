"""Monotonic budgets shared by retrieval, body reads and post-processing.

Cancellation is cooperative. A deadline cannot kill arbitrary Python code.
Adapters must bound their own blocking I/O using the remaining budget.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import math
import threading
import time


class DeadlineExceeded(TimeoutError):
    """The original query or a child operation exhausted its budget."""


def positive_seconds(value, name="timeout"):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


class Deadline:
    def __init__(self, seconds, *, clock=time.monotonic, _parent=None):
        seconds = positive_seconds(seconds)
        self.clock = clock
        self._parent = _parent
        self.expires_at = clock() + seconds
        if _parent is not None:
            self.expires_at = min(self.expires_at, _parent.expires_at)
        self._cancelled = threading.Event()

    def remaining(self) -> float:
        if self._cancelled.is_set():
            return 0.0
        remaining = max(0.0, self.expires_at - self.clock())
        return min(remaining, self._parent.remaining()) if self._parent else remaining

    def check(self) -> None:
        if self.remaining() <= 0:
            raise DeadlineExceeded("retrieval deadline exhausted or cancelled")

    def child(self, seconds) -> Deadline:
        return Deadline(seconds, clock=self.clock, _parent=self)

    def cancel(self) -> None:
        self._cancelled.set()


_current = ContextVar("retrieval_remaining", default=None)


def current_deadline():
    """Adapter fallback for calls inside a scheduled retrieval operation."""
    return _current.get()


@contextmanager
def deadline_scope(remaining):
    token = _current.set(remaining)
    try:
        if remaining is not None:
            remaining.check()
        yield
    finally:
        _current.reset(token)
