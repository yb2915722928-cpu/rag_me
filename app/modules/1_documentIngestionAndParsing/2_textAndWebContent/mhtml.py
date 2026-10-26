from email import policy
from email.parser import BytesParser
import re

from .decoding import decode_bytes
from .html_conversion import html_encoding_declarations


def select_mhtml_html(data: bytes, encoding: str | None = None):
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
    transfer_encoding = str(part.get("Content-Transfer-Encoding", "7bit")).strip().lower()
    if transfer_encoding == "quoted-printable":
        raw = part.get_payload(decode=False).encode("ascii", errors="strict")
        # email's QP decoder silently drops a trailing '=' even under strict policy.
        if re.search(rb"=(?![0-9a-fA-F]{2}|\r?\n)", raw):
            raise ValueError("Invalid quoted-printable HTML payload")
    elif transfer_encoding not in ("7bit", "8bit", "binary", "base64"):
        raise ValueError(f"Unsupported HTML transfer encoding: {transfer_encoding}")
    payload = part.get_payload(decode=True)
    charset = part.get_content_charset()
    declarations = ((charset,) if charset else ()) + html_encoding_declarations(payload)
    return decode_bytes(payload, encoding, declarations)
