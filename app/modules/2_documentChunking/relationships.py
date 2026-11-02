"""文档切分文件夹的父子块关系处理。

父块只在兼容子块的连续区段内生成，因此来源变化和受保护内容边界
不会被更大的父块窗口掩盖。
"""
from __future__ import annotations

from .models import Chunk


def add_parent_child(document, children, config, counter):
    """创建父块，并将每个子块关联到唯一的父块。"""
    if not children:
        return children
    parent_size = config.parent_size or config.size
    parents = []
    mapping = {}
    step = max(1, parent_size // config.size)
    runs = []
    current = []
    current_key = None
    for child in children:
        key = (child.source_ids, child.strategy == "protected")
        if current and key != current_key:
            runs.append(current)
            current = []
        current.append(child)
        current_key = key
    if current:
        runs.append(current)
    for run in runs:
        for index in range(0, len(run), step):
            group = run[index:index + step]
            text = "\n".join(chunk.text for chunk in group)
            parent_id = f"chunk-{document.id}-parent-{len(parents) + 1}"
            parent = Chunk(
                chunk_id=parent_id,
                document_id=document.id,
                business_id=document.business_id,
                version=document.version,
                text=text,
                order=len(children) + len(parents),
                unit_ids=tuple(i for chunk in group for i in chunk.unit_ids),
                source_ids=tuple(dict.fromkeys(i for chunk in group for i in chunk.source_ids)),
                strategy="parent",
                count_mode=config.count_mode,
                count=counter(text),
                child_chunk_ids=tuple(chunk.chunk_id for chunk in group),
            )
            parents.append(parent)
            for child in group:
                mapping[child.chunk_id] = parent_id
    children = [Chunk(**{**child.__dict__, "parent_chunk_id": mapping[child.chunk_id]}) for child in children]
    return children + parents
