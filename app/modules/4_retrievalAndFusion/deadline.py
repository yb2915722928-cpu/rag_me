"""Compatibility entry point for the shared monotonic budget implementation."""
from app.models.deadline import (
    Deadline, DeadlineExceeded, current_deadline, deadline_scope, positive_seconds,
)

__all__ = ["Deadline", "DeadlineExceeded", "current_deadline", "deadline_scope", "positive_seconds"]
