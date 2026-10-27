from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re

from openpyxl.worksheet.formula import ArrayFormula

from .models import Cell


def adapt_cell(cell, cached_cell, source, warnings: list[str]) -> Cell:
    """保留公式但不计算；缓存视图的 str 类型可区分空文本缓存与缺失缓存。"""
    text = _display_value(cell, source, warnings) if cell.data_type != "f" else ""
    value = cell.value.text if isinstance(cell.value, ArrayFormula) else cell.value
    result = Cell(value, text, source, cell.data_type, cell.number_format)
    if cell.data_type == "f":
        result.formula = value
        result.cached_value = cached_cell.value
        if cached_cell.value is None and cached_cell.data_type == "str":
            result.cached_value = ""
        if result.cached_value is not None:
            result.cache_status = "cached"
            cached_text = "空文本" if result.cached_value == "" else _display_value(cached_cell, source, warnings)
            result.text = f"{value}（文件缓存：{cached_text}；非实时计算结果）"
            return result
        result.cache_status = "unknown"
        result.text = f"{value}（结果未知）"
        warnings.append(f"XLSX {source.sheet}!{source.coordinate}: formula result unknown; not calculated.")
    return result


def _display_value(cell, source, warnings):
    """只识别明确格式子集；错误、布尔和文本不进入数值格式化。"""
    value = cell.value
    if value is None:
        return ""
    if cell.data_type == "e":
        return f"错误：{value}"
    if isinstance(value, (str, bool)):
        return str(value)
    if isinstance(value, datetime):
        if cell.number_format == "yyyy-mm-dd":
            return value.date().isoformat()
        if cell.number_format == "yyyy-mm-dd h:mm:ss":
            return value.isoformat()
    if isinstance(value, date) and cell.number_format == "yyyy-mm-dd":
        return value.isoformat()
    if isinstance(value, time) and cell.number_format == "h:mm:ss":
        return value.isoformat()
    if cell.number_format == "General":
        return str(value)
    match = re.fullmatch(r'(?P<currency>[$¥￥€£]|"[$¥￥€£]")?(?P<group>#,##)?0(?:\.(?P<decimals>0{1,6}))?(?P<percent>%)?',
                         cell.number_format)
    if type(value) in (int, float) and match and not (match["currency"] and match["percent"]):
        currency = (match["currency"] or "").strip('"')
        precision = len(match["decimals"] or "")
        number = Decimal(str(value))
        if match["percent"]:
            number *= 100
        sign = "-" if number < 0 else ""
        grouping = "," if match["group"] else ""
        with localcontext(rounding=ROUND_HALF_UP):
            return f"{sign}{currency}{abs(number):{grouping}.{precision}f}{match['percent'] or ''}"
    warnings.append(f"XLSX {source.sheet}!{source.coordinate}: unsupported number format "
                    f"{cell.number_format}; original value retained.")
    return str(value)
