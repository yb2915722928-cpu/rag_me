import re


def normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    has_final_newline = text.endswith("\n")
    lines = text.split("\n")
    if has_final_newline:
        lines.pop()
    normalized = []
    fence = None
    blank_lines = 0
    for line in lines:
        if fence is not None:
            normalized.append(line)
            marker, length = fence
            if re.fullmatch(rf" {{0,3}}{re.escape(marker)}{{{length},}}[ \t]*", line):
                fence = None
            continue
        if line == "":
            blank_lines += 1
            continue
        _append_blank_lines(normalized, blank_lines, line)
        blank_lines = 0
        opening = re.match(
            r" {0,3}(?:(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)?(`{3,}|~{3,})(.*)$", line
        )
        if opening and not (opening[1][0] == "`" and "`" in opening[2]):
            fence = (opening[1][0], len(opening[1]))
        normalized.append(line)
    _append_blank_lines(normalized, blank_lines, "")
    return "\n".join(normalized) + ("\n" if has_final_newline else "")


def _append_blank_lines(lines: list[str], count: int, following: str) -> None:
    if count:
        previous = lines[-1] if lines else ""
        # Blank lines adjoining indented code may belong to its literal content.
        indented = previous.startswith(("    ", "\t")) or following.startswith(("    ", "\t"))
        lines.extend([""] * (count if indented else 1))
