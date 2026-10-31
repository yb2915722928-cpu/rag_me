"""文档切分文件夹的来源追踪辅助函数。

这里严格执行交接契约：只有每个单元的区间都能在正文中还原其文本时，才信任 exact 区间。
不会通过搜索文本来猜测重复内容或乱序内容的区间。
"""
from __future__ import annotations


def diagnostic_dict(item):
    """在不修改原对象的前提下，规范化上游诊断信息。"""
    if isinstance(item, dict):
        return dict(item)
    return {
        "level": getattr(item, "level", "warning"),
        "code": getattr(item, "code", "HANDOFF_DIAGNOSTIC"),
        "message": getattr(item, "message", str(item)),
        "document_id": getattr(item, "document_id", None),
        "unit_id": getattr(item, "unit_id", None),
        "source_id": getattr(item, "source_id", None),
        "details": dict(getattr(item, "details", {}) or {}),
    }


def unit_text(unit) -> str:
    """只返回交接单元实际提供的文本。"""
    return unit.text if isinstance(unit.text, str) else ""


def verified_body_range(document, group):
    """返回经过完整校验的 exact 单元组对应的连续正文区间。"""
    if not document.body or not group or any(unit.alignment != "exact" or unit.body_span is None for unit in group):
        return None
    spans = []
    for unit in group:
        span = unit.body_span
        if not isinstance(span.start, int) or not isinstance(span.end, int):
            return None
        if span.start < 0 or span.end < span.start or span.end > len(document.body):
            return None
        if document.body[span.start:span.end] != unit_text(unit):
            return None
        spans.append((span.start, span.end))
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        return None
    return spans[0][0], spans[-1][1]


def structure_path(group) -> tuple[str, ...]:
    """从单元组中提取第一个可用的标题或祖先路径。"""
    for unit in group:
        metadata = unit.metadata or {}
        path = metadata.get("structure_path") or metadata.get("heading_path") or metadata.get("ancestors")
        if path:
            return tuple(path) if not isinstance(path, str) else (path,)
    return ()
