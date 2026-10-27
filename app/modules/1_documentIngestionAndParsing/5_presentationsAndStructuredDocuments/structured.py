import re
from importlib import import_module
from urllib.parse import quote
from xml.etree import ElementTree

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
    """公共入口已确定格式；解析树只用于来源关系，XML 正文保留解码原文。

    节点路径不是 Markdown 字符区间，不为节点填写推测的正文偏移。
    """

    declarations = _xml_encoding_declarations(data) if source.format == "xml" else ()
    try:
        text, used_encoding, warnings = decode_bytes(data, encoding, declarations)
    except (UnicodeError, LookupError) as exc:
        return ConversionResult(None, source, error=f"Decoding failed: {exc}")
    try:
        if source.format == "json":
            value = json_content.load_json(text)
            markdown = json_content.render_json(value)
            sources = list(_json_sources(value))
        else:
            root = ElementTree.fromstring(text)
            markdown = _render_xml(text)
            sources = list(_xml_sources(root))
    except (ValueError, ElementTree.ParseError, RecursionError) as exc:
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


def _xml_encoding_declarations(data: bytes) -> tuple[str, ...]:
    """读取 XML 起始字节序签名或 ASCII 编码声明，不探测正文编码。

    无 BOM 的 UTF-16/32 声明本身也按对应端序保存，需先由起始字节确定端序；
    这里返回格式依据，显式编码与 BOM 的更高优先级仍由共用解码器决定。
    """

    for signature, encoding in (
        (b"\x00\x00\x00<", "utf-32-be"), (b"<\x00\x00\x00", "utf-32-le"),
        (b"\x00<\x00?", "utf-16-be"), (b"<\x00?\x00", "utf-16-le"),
    ):
        if data.startswith(signature):
            return (encoding,)
    match = re.match(
        rb"""<\?xml\s+[^?]*?\bencoding\s*=\s*(['"])([A-Za-z][A-Za-z0-9._-]*)\1""",
        data,
    )
    return (match[2].decode("ascii"),) if match else ()


def _render_xml(text: str) -> str:
    """不重新序列化，保留属性、命名空间、混合正文、注释及原换行。

    围栏长于原文所有反引号串，避免 XML 正文提前关闭 Markdown 代码块。
    """

    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}xml\n{text}\n{fence}\n"


def _xml_sources(element, parent_path=None, ordinal=1):
    """每段为百分号转义的展开名称加 [同名序号]，序号在同父同名元素间从 1 计。

    展开名称采用 ElementTree 的 {命名空间 URI}局部名，无命名空间时为局部名；
    整段名称转义使 URI 内的 / 等字符不会与路径分隔符混淆。这不是 XPath。
    """

    path = f"{parent_path or ''}/{quote(element.tag, safe='')}[{ordinal}]"
    yield ContentSource(
        kind="xml_element", node_path=path, parent_path=parent_path, node_type="element",
    )
    counts = {}
    for child in element:
        counts[child.tag] = counts.get(child.tag, 0) + 1
        yield from _xml_sources(child, path, counts[child.tag])
