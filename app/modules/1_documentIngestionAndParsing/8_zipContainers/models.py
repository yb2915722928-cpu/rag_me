from dataclasses import dataclass, field, fields, is_dataclass
import time


class _StopProcessing(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"ZIP processing stopped: {reason}")


def _check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise _StopProcessing("deadline_exceeded")


@dataclass(frozen=True)
class ZipLimits:
    max_archive_bytes: int = 100 * 1024**2
    max_members: int = 1000
    max_member_bytes: int = 64 * 1024**2
    max_total_bytes: int = 256 * 1024**2
    timeout_seconds: float = 300


@dataclass(frozen=True)
class MemberSource:
    """entry_index 从 1 开始，包含目录；同路径重复条目也拥有不同序号。"""

    container: str
    member_path: str
    entry_index: int


@dataclass
class MemberResult:
    source: MemberSource
    format: str
    status: str
    result_kind: str | None = None
    result: object = None
    error: str | None = None
    reason: str | None = None
    bytes_read: int = 0


@dataclass
class ZipResult:
    source: str
    members: list[MemberResult] = field(default_factory=list)
    error: str | None = None
    stop_reason: str | None = None
    total_bytes_read: int = 0

    @property
    def counts(self) -> dict[str, int]:
        return {
            "total": len(self.members),
            **{status: sum(member.status == status for member in self.members)
               for status in ("success", "failed", "ignored", "unprocessed")},
        }

    @property
    def status(self) -> str:
        counts = self.counts
        if not counts["success"]:
            return "failed"
        if self.error or counts["failed"] or counts["unprocessed"]:
            return "partial_success"
        return "success"

    @property
    def success(self) -> bool:
        return self.status == "success"

    @property
    def requires_review(self) -> bool:
        return any(getattr(member.result, "requires_review", False) for member in self.members)

    def to_dict(self) -> dict:
        """原生 dataclass 字段之外还投影计算属性；不保存也不回显调用方配置。"""
        return {**_project(self), "status": self.status, "counts": self.counts}


def _project(value):
    """原生结果仍保留各自来源结构，不将不同格式折叠成共同正文。"""
    if is_dataclass(value):
        projected = {item.name: _project(getattr(value, item.name)) for item in fields(value)}
        if hasattr(value, "success"):
            projected["success"] = value.success
            projected["requires_review"] = bool(getattr(value, "requires_review", False))
        return projected
    if isinstance(value, (list, tuple)):
        return [_project(item) for item in value]
    if isinstance(value, dict):
        return {key: _project(item) for key, item in value.items()}
    return value
