from dataclasses import dataclass
import time


class ArchiveProcessingStopped(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"ZIP processing stopped: {reason}")


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise ArchiveProcessingStopped("deadline_exceeded")


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 100 * 1024**2
    max_members: int = 1000
    max_member_bytes: int = 64 * 1024**2
    max_total_bytes: int = 256 * 1024**2
    timeout_seconds: float = 300
