"""文档切分文件夹：将交接数据转换为确定性的检索块。

这里是实现对外暴露的简洁接口。调用方提供统一交接报告或文档，内部模块负责保留来源追踪、
来源边界、结构信息、受保护单元以及可选的父子块关系。
"""

from .chunking import (
    Chunk,
    ChunkingConfig,
    ChunkingError,
    ChunkingResult,
    InvalidChunkingConfiguration,
    InvalidHandoffReference,
    chunk,
    chunk_document,
    chunk_documents,
    chunk_report,
)

__all__ = [
    "Chunk", "ChunkingConfig", "ChunkingError", "ChunkingResult",
    "InvalidChunkingConfiguration", "InvalidHandoffReference", "chunk",
    "chunk_document", "chunk_documents", "chunk_report",
]
