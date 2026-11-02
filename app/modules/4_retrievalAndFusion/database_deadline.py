"""Compatibility entry point for shared PostgreSQL deadline handling."""
from app.models.db.deadline import DeadlineCursor, watch_connection

__all__ = ["DeadlineCursor", "watch_connection"]
