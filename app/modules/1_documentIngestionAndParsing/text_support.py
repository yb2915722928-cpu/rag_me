"""Shared decoding and strict JSON support, independent of format parsers."""

import codecs
import json

from charset_normalizer import from_bytes


def decode_bytes(
    data: bytes, encoding: str | None = None, declarations: tuple[str, ...] = ()
) -> tuple[str, str, list[str]]:
    if encoding is not None:
        used_encoding = codecs.lookup(encoding).name
        return data.decode(used_encoding, errors="strict"), used_encoding, []
    # UTF-32 LE starts with the UTF-16 LE signature, so check it first.
    for signature, used_encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF8, "utf-8-sig"),
    ):
        if data.startswith(signature):
            return data.decode(used_encoding, errors="strict"), used_encoding, []
    warnings = []
    for declaration in declarations:
        try:
            used_encoding = codecs.lookup(declaration).name
            text = data.decode(used_encoding, errors="strict")
        except (UnicodeError, LookupError) as exc:
            warnings.append(f"Declared encoding {declaration!r} could not decode text: {exc}")
        else:
            return text, used_encoding, warnings
    try:
        return data.decode("utf-8", errors="strict"), "utf-8", warnings
    except UnicodeDecodeError:
        detected = from_bytes(data).best()
    if detected is None:
        raise UnicodeError("No usable text encoding detected")
    used_encoding = codecs.lookup(detected.encoding).name
    return (
        data.decode(used_encoding, errors="strict"),
        used_encoding,
        warnings + [f"Encoding automatically detected as {used_encoding}; verify the text."],
    )


def convert_json(text: str) -> str:
    """移除必要的 UTF-8 BOM 后解析 JSON，以代码围栏保留结构和值的归属。

    不将数组转成数字键对象，也不按长度预分组或切块；非法常量明确失败。
    """

    return render_json(load_json(text))


def load_json(text: str):
    """与正文转换共用严格解析，让节点来源复用同一份解析结果。"""

    return json.loads(text.removeprefix("\ufeff"), parse_constant=_reject_constant)


def render_json(value) -> str:
    """保留合法根值、数组顺序和值类型，不将对象字段排列解释为业务步骤顺序。"""

    body = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    return f"```json\n{body}\n```\n"


def _reject_constant(value: str):
    """Python 默认接受 NaN 和 Infinity，但它们不属于合法 JSON，必须显式拒绝。"""

    raise ValueError(f"{value} is not a JSON constant")
