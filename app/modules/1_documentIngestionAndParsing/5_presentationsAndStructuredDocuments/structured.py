from importlib import import_module

from .models import ContentSource, ConversionResult, Source


decode_bytes = import_module("..2_textAndWebContent.decoding", __package__).decode_bytes
json_content = import_module("..2_textAndWebContent.json_content", __package__)

_JSON_NODE_TYPES = {
    dict: "object", list: "array", str: "string", int: "number",
    float: "number", bool: "boolean", type(None): "null",
}


def convert_structured(
    data: bytes, source: Source, encoding: str | None,
) -> ConversionResult:
    """公共 API 将 JSON/XML 直接分派到这里，XML 实现可在此边界接入。

    节点路径不是 Markdown 字符区间，不为节点填写推测的正文偏移。
    """

    if source.format == "xml":
        return ConversionResult(None, source, error="Unsupported format: xml (not implemented)")
    try:
        text, used_encoding, warnings = decode_bytes(data, encoding)
    except (UnicodeError, LookupError) as exc:
        return ConversionResult(None, source, error=f"Decoding failed: {exc}")
    try:
        value = json_content.load_json(text)
        markdown = json_content.render_json(value)
        sources = list(_json_sources(value))
    except (ValueError, RecursionError) as exc:
        return ConversionResult(
            None, source, encoding=used_encoding, warnings=warnings,
            error=f"Invalid {source.format.upper()}: {exc}",
        )
    return ConversionResult(
        markdown, source, sources=sources, encoding=used_encoding, warnings=warnings,
    )


def _json_sources(value, path="", parent_path=None):
    """RFC 6901：先转义 ~ 再转义 /；根路径为空串，数组索引从 0 开始。"""

    yield ContentSource(
        kind="json_node", node_path=path, parent_path=parent_path,
        node_type=_JSON_NODE_TYPES[type(value)],
    )
    if isinstance(value, dict):
        children = value.items()
    elif isinstance(value, list):
        children = enumerate(value)
    else:
        return
    for key, child in children:
        token = str(key).replace("~", "~0").replace("/", "~1")
        yield from _json_sources(child, f"{path}/{token}", path)
