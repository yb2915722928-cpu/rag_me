"""Compatibility entry point for the shared monotonic budget implementation."""
from app.models.deadline import (
    Deadline, DeadlineExceeded, current_deadline, deadline_scope, positive_seconds,
)

def budgeted(values, remaining=None):
    """Bound local CPU loops by the same request deadline as external work."""
    for value in values:
        if remaining is not None:
            remaining.check()
        yield value
    if remaining is not None:
        remaining.check()


__all__ = ["Deadline", "DeadlineExceeded", "current_deadline", "deadline_scope", "positive_seconds"]
