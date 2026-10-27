from email import policy
from email.parser import BytesParser
from email.utils import collapse_rfc2231_value
import re

from .decoding import decode_bytes
from .html_conversion import html_encoding_declarations


def select_mhtml_html(data: bytes, encoding: str | None = None):
    """优先选择外层 related 的 start 明确指向的主 HTML 部分，不合并框架。

    无明确标识时比较原始解码字符串的字符数，包含标记和换行；
    不以载荷字节数或转换后的 Markdown 长度排序，并列时保留 MIME 顺序。
    启发式选择需独立警告供调用方核验，选中部分的来源也单独返回。
    """

    archive = BytesParser(policy=policy.strict).parsebytes(data)
    candidates = [
        (index, part) for index, part in enumerate(archive.walk())
        if part.get_content_type() == "text/html" and not part.is_multipart()
        and part.get_content_disposition() != "attachment"
    ]
    if not candidates:
        raise ValueError("No HTML part in MHTML archive")
    start = archive.get_param("start") if archive.get_content_type() == "multipart/related" else None
    if start:
        start = collapse_rfc2231_value(start, errors="strict")
        root = next((
            part for part in archive.iter_parts()
            if str(part.get("Content-ID", "")).strip().strip("<>") == start.strip().strip("<>")
        ), None)
        candidates = [(index, part) for index, part in candidates if part is root]
        if not candidates:
            raise ValueError("Explicit MHTML start does not identify an HTML part")
    decoded = [
        (*_decode_html_part(part, encoding), index, part) for index, part in candidates
    ]
    text, used_encoding, warnings, index, part = max(
        decoded, key=lambda item: len(item[0])
    )
    if not start:
        warnings.append(
            "No explicit main HTML identifier; selected by largest decoded HTML character "
            "count (MIME order breaks ties). Verify the selected page."
        )
    return text, used_encoding, warnings, {
        "content_id": part.get("Content-ID"),
        "content_location": part.get("Content-Location"),
        "mime_index": index,
    }


def _decode_html_part(part, encoding):
    """先解开 MIME 传输编码，再按共享优先级严格解码 HTML；MIME 声明先于 HTML 声明。

    标准库即使启用严格策略，仍会静默丢弃 quoted-printable 末尾的孤立等号，
    因此解包前需额外检查转义序列，防止文字在字符集解码之前已经丢失。
    """

    transfer_encoding = str(part.get("Content-Transfer-Encoding", "7bit")).strip().lower()
    if transfer_encoding == "quoted-printable":
        raw = part.get_payload(decode=False).encode("ascii", errors="strict")
        if re.search(rb"=(?![0-9a-fA-F]{2}|\r?\n)", raw):
            raise ValueError("Invalid quoted-printable HTML payload")
    elif transfer_encoding not in ("7bit", "8bit", "binary", "base64"):
        raise ValueError(f"Unsupported HTML transfer encoding: {transfer_encoding}")
    payload = part.get_payload(decode=True)
    charset = part.get_content_charset()
    declarations = ((charset,) if charset else ()) + html_encoding_declarations(payload)
    return decode_bytes(payload, encoding, declarations)
