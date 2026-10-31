"""Thread-safe local quotas shared by calls, including every retry attempt."""
from __future__ import annotations

from collections import deque
import math
import threading
import time
import weakref
from typing import Callable


class QuotaWaitExceeded(RuntimeError):
    pass


class QuotaCapacityExceeded(ValueError):
    pass


def _positive_integer(value, name, *, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _seconds(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'nonnegative'} number")


class WaitBudget:
    """Bound both real elapsed time and injected sleepers that do not advance clocks."""

    def __init__(self, limit, clock, sleeper):
        _seconds(limit, "max_wait_seconds")
        self.limit, self.clock, self.sleeper = limit, clock, sleeper
        self.started = clock()
        self.slept = 0.0

    @property
    def remaining(self):
        return max(0.0, self.limit - max(self.slept, self.clock() - self.started))

    def sleep(self, duration):
        if duration > self.remaining or self.remaining <= 0:
            raise QuotaWaitExceeded("local quota or retry wait exceeded max_wait_seconds")
        self.sleeper(duration)
        self.slept += duration


class LocalRateLimiter:
    """Sliding-window request/token quotas and a shared in-flight concurrency bound.

    A reservation is charged once acquired, even if the subsequent request fails.
    Sharing this object shares the provider/account budget across adapters as well.
    """

    def __init__(self, *, request_budget=None, token_budget=None, window_seconds=1.0,
                 max_concurrency=1, clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep):
        _positive_integer(request_budget, "request_budget", optional=True)
        _positive_integer(token_budget, "token_budget", optional=True)
        _positive_integer(max_concurrency, "max_concurrency")
        _seconds(window_seconds, "window_seconds", positive=True)
        self.request_budget, self.token_budget = request_budget, token_budget
        self.window_seconds, self.max_concurrency = window_seconds, max_concurrency
        self.clock, self.sleeper = clock, sleeper
        self._lock = threading.Lock()
        self._events = deque()
        self._tokens = self._inflight = 0

    def acquire(self, tokens: int, *, max_wait_seconds=30, wait_budget=None):
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            raise ValueError("tokens must be a nonnegative integer")
        if self.token_budget is not None and tokens > self.token_budget:
            raise QuotaCapacityExceeded("one request exceeds the entire token budget")
        waiting = wait_budget or WaitBudget(max_wait_seconds, self.clock, self.sleeper)
        while True:
            with self._lock:
                now = self.clock()
                while self._events and now - self._events[0][0] >= self.window_seconds:
                    _, expired_tokens = self._events.popleft()
                    self._tokens -= expired_tokens
                quota_full = ((self.request_budget is not None and len(self._events) >= self.request_budget)
                              or (self.token_budget is not None and self._tokens + tokens > self.token_budget))
                if not quota_full and self._inflight < self.max_concurrency:
                    # Do not retain unlimited zero-token calls when only tokens are bounded.
                    if self.request_budget is not None or self.token_budget is not None and tokens:
                        self._events.append((now, tokens))
                        self._tokens += tokens
                    self._inflight += 1
                    return
                delay = max(0.0, self.window_seconds - (now - self._events[0][0])) if quota_full else 0.01
            waiting.sleep(delay if quota_full else min(delay, waiting.remaining))

    def release(self):
        with self._lock:
            if self._inflight <= 0:
                raise RuntimeError("cannot release a quota reservation that was not acquired")
            self._inflight -= 1


_registry_lock = threading.Lock()
_registry = weakref.WeakKeyDictionary()


def shared_limiter(adapter, *, request_budget=None, token_budget=None, window_seconds=1.0,
                   max_concurrency=1, clock=time.monotonic, sleeper=time.sleep):
    """Keep quota state for the adapter's lifetime instead of resetting per call."""
    config = (request_budget, token_budget, window_seconds, max_concurrency, clock, sleeper)
    with _registry_lock:
        limiters = _registry.setdefault(adapter, {})
        if config not in limiters:
            limiters[config] = LocalRateLimiter(request_budget=request_budget, token_budget=token_budget,
                window_seconds=window_seconds, max_concurrency=max_concurrency, clock=clock, sleeper=sleeper)
        return limiters[config]
