"""文档切分文件夹的切分策略。

本模块在不跨越来源或受保护内容边界的前提下，合并相邻交接单元，
然后对文本执行确定性的字符或 token 窗口切分。
"""
from __future__ import annotations

from .provenance import unit_text, verified_body_range

_PROTECTED_KINDS = {"table", "table_row", "cell", "media", "service", "image", "audio", "video"}


def counter_for(config):
    """仅在 token 模式使用注入的计数器；字符模式使用 len。"""
    return config.token_counter if config.count_mode == "tokens" else len


def groups(units, config):
    """当来源或受保护分组键变化时拆分单元。"""
    result = []
    current = []
    current_key = None
    for unit in units:
        key = group_key(unit, config)
        if current and key != current_key:
            result.append(current)
            current = []
        current.append(unit)
        current_key = key
    if current:
        result.append(current)
    return result


def group_key(unit, config):
    """在保持来源内文本连续区段的同时，保护表格和媒体单元完整。"""
    kind = (unit.kind or "").lower()
    metadata = unit.metadata or {}
    if kind.startswith("table") or kind in _PROTECTED_KINDS:
        table_id = metadata.get("table_id", unit.parent_id or unit.id)
        if config.table_mode == "whole" and kind in {"table", "table_row", "cell"}:
            return ("protected", tuple(unit.source_ids), table_id)
        if kind in {"table", "table_row", "cell"}:
            return ("protected", tuple(unit.source_ids), table_id, metadata.get("row_index", unit.id))
        return ("protected", unit.id)
    return ("text", tuple(unit.source_ids))


def is_protected(group):
    return bool(group) and (group[0].kind or "").lower() in _PROTECTED_KINDS


def selected_strategy(group, config, structure_path):
    """根据显式配置和结构信息确定性地解析 auto 模式。"""
    if config.strategy == "fixed":
        return "fixed"
    if config.strategy == "structured":
        return "structured"
    if config.strategy == "parent_child":
        return "fixed"
    return "structured" if structure_path(group) else "fixed"


def protected_text(group):
    return "\n".join(unit_text(unit) for unit in group if unit_text(unit))


def fit_end(text, start, size, counter):
    """寻找预算内最大的前缀，并确保至少允许一个字符。"""
    end = start
    while end < len(text) and counter(text[start:end + 1]) <= size:
        end += 1
    return end


def overlap_start(text, end, overlap, counter):
    """按配置的计数单位计算重叠范围，同时支持注入的 token 模式。"""
    if overlap <= 0:
        return end
    start = end
    while start > 0 and counter(text[start - 1:end]) <= overlap:
        start -= 1
    return start


def fixed_group(document, group, config, start_order, counter, strategy, make_chunk):
    """对一个来源内的单元组执行窗口切分，并把来源追踪交给块构造函数。"""
    verified = verified_body_range(document, group)
    if verified is not None:
        start, finish = verified
        text = document.body[start:finish]
    else:
        start = None
        text = "\n".join(unit_text(unit) for unit in group if unit_text(unit))
    if not text:
        return []
    chunks = []
    pos = 0
    while pos < len(text):
        end = fit_end(text, pos, config.size, counter)
        if end <= pos:
            end = pos + 1
        span_hint = (start + pos, start + end) if start is not None else None
        chunks.append(make_chunk(group, text[pos:end], start_order + len(chunks), strategy, [], span_hint))
        if end >= len(text):
            break
        pos = max(pos + 1, overlap_start(text, end, config.overlap, counter))
    return chunks
