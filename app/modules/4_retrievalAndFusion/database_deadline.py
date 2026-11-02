"""Budget-aware SQL and bounded best-effort psycopg cancellation.

statement_timeout is enforced by PostgreSQL. cancel_safe requires psycopg 3.2;
its dedicated monitor has a bounded cancel timeout and never blocks the caller.
Connection establishment still obeys libpq's whole-second timeout granularity;
the scheduler bounds caller wait while occupied workers retain their capacity.
"""
from contextlib import contextmanager
import math
import threading


class DeadlineCursor:
    def __init__(self, cursor, remaining):
        self._cursor, self.remaining = cursor, remaining

    def execute(self, sql, parameters=None, **kwargs):
        self.remaining.check()
        milliseconds = max(1, math.floor(self.remaining.remaining() * 1000))
        self._cursor.execute("SELECT set_config('statement_timeout', %s, true)",
                             (str(milliseconds),))
        self.remaining.check()
        return self._cursor.execute(sql, parameters, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _CancellationMonitor:
    """One process-wide monitor; registrations capped independently of callers."""
    def __init__(self, capacity=64):
        self.capacity = capacity
        self._changed = threading.Condition()
        self._entries = {}
        threading.Thread(target=self._run, name="retrieval-db-cancel", daemon=True).start()

    @contextmanager
    def watch(self, connection, remaining):
        key = object()
        with self._changed:
            if len(self._entries) >= self.capacity:
                raise RuntimeError("database cancellation capacity exhausted")
            self._entries[key] = (connection, remaining)
            self._changed.notify_all()
        try:
            yield
        finally:
            with self._changed:
                self._entries.pop(key, None)

    def _run(self):
        while True:
            with self._changed:
                expired = [(key, conn) for key, (conn, budget) in self._entries.items()
                           if budget.remaining() <= 0]
                for key, _ in expired:
                    self._entries.pop(key, None)
                if not expired:
                    self._changed.wait(.01 if self._entries else None)
                    continue
            for _, connection in expired:
                try:
                    # Never use legacy cancel(), which can block without a bound.
                    connection.cancel_safe(timeout=.05)
                except Exception:
                    # Server statement_timeout remains the primary boundary.
                    pass


_monitor = None
_monitor_lock = threading.Lock()


def watch_connection(connection, remaining):
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = _CancellationMonitor()
    return _monitor.watch(connection, remaining)
