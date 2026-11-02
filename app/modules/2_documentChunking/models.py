"""文档切分文件夹的公开结果模型。

这些模型在公开接口处保持不可变：切分过程返回新对象，不修改调用方传入的交接对象。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .errors import InvalidChunkingConfiguration


@dataclass(frozen=True)
class ChunkingConfig:
    """所有切分策略共用的配置项。"""

    size: int = 500
    overlap: int = 0
    count_mode: str = "characters"
    token_counter: Callable[[str], int] | None = None
    strategy: str = "auto"
    table_mode: str = "rows"
    context_projection: bool = False
    parent_size: int | None = None
    parent_child: bool = False

    def validate(self) -> None:
        """在检查输入文档前，先拒绝无效的配置组合。"""
        if not isinstance(self.size, int) or isinstance(self.size, bool) or self.size <= 0:
            raise InvalidChunkingConfiguration("size must be a positive integer")
        if not isinstance(self.overlap, int) or isinstance(self.overlap, bool) or self.overlap < 0:
            raise InvalidChunkingConfiguration("overlap must be a nonnegative integer")
        if self.overlap >= self.size:
            raise InvalidChunkingConfiguration("overlap must be smaller than size")
        if self.count_mode not in {"characters", "tokens"}:
            raise InvalidChunkingConfiguration("count_mode must be characters or tokens")
        if self.count_mode == "tokens" and self.token_counter is None:
            raise InvalidChunkingConfiguration("token_counter is required for token mode")
        if self.strategy not in {"auto", "fixed", "structured", "parent_child"}:
            raise InvalidChunkingConfiguration("unsupported strategy")
        if self.table_mode not in {"whole", "rows"}:
            raise InvalidChunkingConfiguration("table_mode must be whole or rows")
        if self.parent_size is not None and self.parent_size <= 0:
            raise InvalidChunkingConfiguration("parent_size must be positive")
        if self.parent_child and self.parent_size is None:
            raise InvalidChunkingConfiguration("parent_size is required for parent_child mode")


@dataclass(frozen=True)
class Chunk:
    """一个检索块及其来源追踪和关系元数据。"""

    chunk_id: str
    document_id: str
    business_id: str | None
    version: str | None
    text: str
    order: int
    unit_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    structure_path: tuple[str, ...] = ()
    alignment: str = "unmapped"
    body_span: tuple[int, int] | None = None
    strategy: str = "fixed"
    count_mode: str = "characters"
    count: int = 0
    diagnostics: tuple[dict, ...] = ()
    requires_review: bool = False
    projected_context: bool = False
    parent_chunk_id: str | None = None
    child_chunk_ids: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """返回适合 JSON 的集合，同时不暴露可变的内部对象。"""
        result = dict(self.__dict__)
        result["unit_ids"] = list(self.unit_ids)
        result["source_ids"] = list(self.source_ids)
        result["structure_path"] = list(self.structure_path)
        result["diagnostics"] = [dict(item) for item in self.diagnostics]
        result["child_chunk_ids"] = list(self.child_chunk_ids)
        return result


@dataclass(frozen=True)
class ChunkingResult:
    """公开入口返回的切分块和文档级诊断信息。"""

    chunks: tuple[Chunk, ...]
    diagnostics: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"chunks": [chunk.to_dict() for chunk in self.chunks], "diagnostics": list(self.diagnostics)}
