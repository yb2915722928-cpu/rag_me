import json


def convert_json(text: str) -> str:
    """移除必要的 UTF-8 BOM 后解析 JSON，以代码围栏保留结构和值的归属。

    不将数组转成数字键对象，也不按长度预分组或切块；非法常量明确失败。
    """

    value = json.loads(text.removeprefix("\ufeff"), parse_constant=_reject_constant)
    body = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    return f"```json\n{body}\n```\n"


def _reject_constant(value: str):
    """Python 默认接受 NaN 和 Infinity，但它们不属于合法 JSON，必须显式拒绝。"""

    raise ValueError(f"{value} is not a JSON constant")
