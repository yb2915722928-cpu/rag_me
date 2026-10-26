import codecs

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
