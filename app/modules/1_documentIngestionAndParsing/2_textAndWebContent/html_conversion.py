import re

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter


def html_encoding_declarations(data: bytes) -> tuple[str, ...]:
    """Collect HTML charset hints for decode_bytes, after any caller/MIME hints."""
    # Latin-1 exposes ASCII declaration syntax without guessing the document encoding.
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
    """Convert decoded HTML; source and decoding diagnostics belong to the caller."""
    document = BeautifulSoup(text.replace("\r\n", "\n").replace("\r", "\n"), "html.parser")
    for element in reversed(document.select("head, title, script, style, noscript, template")):
        element.decompose()
    body = _article_body(document) if mode == "article" else document.body or document
    if not body.get_text(strip=True):
        raise ValueError("No usable HTML body")
    _process_images(body)
    return _BodyMarkdownConverter(heading_style="ATX").convert_soup(body).strip() + "\n"


def _article_body(document):
    # Keep both footnote asides and the asides that contain them.
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
    pass


class _BodyMarkdownConverter(MarkdownConverter):
    def convert_td(self, el, text, parent_tags):
        # Table pipes need escaping even inside Markdown code spans.
        return super().convert_td(el, text.replace("|", r"\|"), parent_tags)

    convert_th = convert_td

    def convert_pre(self, el, text, parent_tags):
        # Converted child spans can trim spaces, so read the original preformatted text.
        code = el.get_text()
        longest_run = max((len(run) for run in re.findall(r"`+", code)), default=0)
        fence = "`" * max(3, longest_run + 1)
        separator = "" if code.endswith("\n") else "\n"
        return f"\n\n{fence}\n{code}{separator}{fence}\n\n"
