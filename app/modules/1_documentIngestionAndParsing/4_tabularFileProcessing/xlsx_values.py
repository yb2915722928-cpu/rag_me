from .models import Cell


def adapt_cell(cell, cached_cell, source, warnings: list[str]) -> Cell:
    """公式暂只保留表达式并标记未知；cached_cell 为后续缓存读取保留边界。"""
    text = "" if cell.value is None else str(cell.value)
    result = Cell(cell.value, text, source, cell.data_type, cell.number_format)
    if cell.data_type == "f":
        result.formula = cell.value
        result.cache_status = "unknown"
        result.text = f"{cell.value}（结果未知）"
        warnings.append(f"XLSX {source.sheet}!{source.coordinate}: formula result unknown; not calculated.")
    return result
