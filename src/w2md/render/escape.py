"""Markdown escaping for literal text."""


_ESCAPE_CHARS = set(["\\", "`", "*", "[", "]", "_"])


def escape_text(text):
    return "".join("\\" + ch if ch in _ESCAPE_CHARS else ch for ch in text)

