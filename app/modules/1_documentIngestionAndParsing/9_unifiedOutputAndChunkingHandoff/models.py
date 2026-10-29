from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import count


@dataclass
class BodySpan:
    """统一文档 body 上的 Python 字符半开区间；不表示原文件字节位置。"""

    start: int
    end: int


@dataclass
class Source:
    id: str
    kind: str
    locator: dict


@dataclass
class Diagnostic:
    level: str
    code: str
    message: str
    document_id: str | None = None
    unit_id: str | None = None
    source_id: str | None = None
    details: dict = field(default_factory=dict)


@dataclass
class ContentUnit:
    """body_span 仅承载上游确有的字符映射；来源与结构定位独立于该区间。"""

    id: str
    kind: str
    text: str | None
    source_ids: list[str] = field(default_factory=list)
    body_span: BodySpan | None = None
    alignment: str = "unmapped"
    parent_id: str | None = None
    status: str = "success"
    metadata: dict = field(default_factory=dict)


@dataclass
class Document:
    """status 表示技术处理状态；requires_review=False 也不表示内容已核验。"""

    id: str
    body: str | None
    body_format: str
    status: str
    business_id: str | None = None
    version: str | None = None
    sources: list[Source] = field(default_factory=list)
    units: list[ContentUnit] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    structure: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    requires_review: bool = False


@dataclass
class HandoffReport:
    status: str
    documents: list[Document] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """返回独立 JSON 投影；日期保留原精度，不补时区或改变普通标量类型。"""
        return _json_values(asdict(self))


def _json_values(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return _iso_duration(value)
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_values(item) for item in value]
    return value


def _iso_duration(value: timedelta) -> str:
    """用带符号的 ISO 总秒数区分持续时间与时刻，并保留微秒精度。"""
    microseconds = value // timedelta(microseconds=1)
    sign = "-" if microseconds < 0 else ""
    seconds, remainder = divmod(abs(microseconds), 1_000_000)
    fraction = f".{remainder:06d}".rstrip("0") if remainder else ""
    return f"{sign}PT{seconds}{fraction}S"


class IdAllocator:
    """每份报告共享一个分配器；ID 只供本次结果引用，不承诺跨次稳定。"""

    def __init__(self):
        self._numbers = count(1)

    def new_id(self, kind: str) -> str:
        return f"{kind}-{next(self._numbers)}"
