"""文档切分文件夹的兼容门面。

本文件夹将统一摄取交接文档转换为确定性的检索块。具体实现已拆分到多个职责清晰的内部模块，
本门面保留原有导入路径，确保已有调用方无需修改。
"""

from .errors import ChunkingError, InvalidChunkingConfiguration, InvalidHandoffReference
from .models import Chunk, ChunkingConfig, ChunkingResult
from .pipeline import chunk, chunk_document, chunk_documents, chunk_documents_result, chunk_report

__all__ = [
    "Chunk",
    "ChunkingConfig",
    "ChunkingError",
    "ChunkingResult",
    "InvalidChunkingConfiguration",
    "InvalidHandoffReference",
    "chunk",
    "chunk_document",
    "chunk_documents",
    "chunk_documents_result",
    "chunk_report",
]
