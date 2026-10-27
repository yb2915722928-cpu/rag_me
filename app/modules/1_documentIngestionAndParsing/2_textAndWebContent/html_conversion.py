import re

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter


def html_encoding_declarations(data: bytes) -> tuple[str, ...]:
    """用 Latin-1 逐字节映射提取 ASCII 编码声明，不在此猜测正文编码。

    返回的声明供严格解码器使用，其优先级低于调用方显式编码、BOM 和 MIME 声明。
    """

    document = BeautifulSoup(data.decode("latin-1"), "html.parser")
    declarations = []
    for meta in document.find_all("meta"):
        if meta.get("charset"):
            declarations.append(meta["charset"])
        elif meta.get("http-equiv", "").lower() == "content-type":
            match = re.search(
                r"charset\s*=\s*[\"']?([^\s;\"']+)",
                meta.get("content", ""), re.IGNORECASE,
            )
            if match:
                declarations.append(match[1])
    return tuple(declarations)


def html_to_markdown(text: str, mode: str = "article") -> str:
    """转换已解码的静态 HTML，两种模式只在内容筛选范围上有所不同。

    脚本、样式等非正文内容统一清理，不执行 JavaScript；清理从子节点向父节点进行。
    图片扩展点不接管正文，来源和诊断由调用方单独记录；无可用文字时明确失败。
    """

    document = BeautifulSoup(text.replace("\r\n", "\n").replace("\r", "\n"), "html.parser")
    for element in reversed(document.select("head, title, script, style, noscript, template")):
        element.decompose()
    body = _article_body(document) if mode == "article" else document.body or document
    if not body.get_text(strip=True):
        raise ValueError("No usable HTML body")
    _process_images(body)
    return _BodyMarkdownConverter(heading_style="ATX").convert_soup(body).strip() + "\n"


def _article_body(document):
    """先清理明显的附属内容，再按主体语义选择正文，同类候选取文字最多者。

    正文脚注可能使用 aside，需保留脚注及其所在的 aside 容器，不能当作侧栏删除。
    反向遍历待删除节点，避免父节点销毁后继续访问它的子节点。
    """

    for element in reversed(document.select(
        "nav, aside:not([role=doc-footnote]):not(:has([role=doc-footnote])), "
        "footer, [role=navigation], [role=banner], "
        "[role=contentinfo], [role=complementary]"
    )):
        element.decompose()
    noise_marker = re.compile(
        r"(?:^|[-_\s])(?:nav|navigation|navbar|sidebar|footer|advertisement|"
        r"advertising|advert|ads|ad|sponsored)(?:$|[-_\s])", re.IGNORECASE
    )
    for element in reversed(document.select("[class], [id]")):
        markers = " ".join(element.get("class", [])) + " " + element.get("id", "")
        if noise_marker.search(markers):
            element.decompose()
    for selector in (
        "main", "article", "[role=main]",
        "#main-content, #content, .entry-content, .post-content",
    ):
        candidates = [
            element for element in document.select(selector) if element.get_text(strip=True)
        ]
        if candidates:
            return max(candidates, key=lambda element: len(element.get_text(strip=True)))
    return document.body or document


def _process_images(body):
    """仅保留未来图片模块的接入位置，调用方不能用此空返回值替换文字正文。"""

    pass


class _BodyMarkdownConverter(MarkdownConverter):
    def convert_td(self, el, text, parent_tags):
        """表格中的管道符即使位于行内代码中也要转义，否则会被误认为新增列。"""

        return super().convert_td(el, text.replace("|", r"\|"), parent_tags)

    convert_th = convert_td

    def convert_pre(self, el, text, parent_tags):
        """直接读取原始预格式化文字，避免子标签转换时裁掉代码所需的空白。

        输出围栏长于代码中已有的连续反引号，避免代码内容提前关闭围栏。
        """

        code = el.get_text()
        longest_run = max((len(run) for run in re.findall(r"`+", code)), default=0)
        fence = "`" * max(3, longest_run + 1)
        separator = "" if code.endswith("\n") else "\n"
        return f"\n\n{fence}\n{code}{separator}{fence}\n\n"
