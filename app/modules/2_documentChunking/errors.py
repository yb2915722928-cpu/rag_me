"""文档切分文件夹的异常定义。

本模块区分配置错误和交接引用错误，便于调用方准确处理失败原因。
"""


class ChunkingError(ValueError):
    """切分配置或交接关系无效时的基础异常。"""


class InvalidChunkingConfiguration(ChunkingError):
    """切分选项内部不一致时抛出。"""


class InvalidHandoffReference(ChunkingError):
    """文档引用未知或无效的交接对象时抛出。"""
