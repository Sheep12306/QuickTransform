"""Markdown escaping for literal text."""

import re


_ESCAPE_CHARS = set(["\\", "`", "*", "[", "]", "_"])

# ShowDoc image placeholders contain underscores and must survive verbatim so
# the later URL replacement can match them exactly.  Normal and special
# placeholders share the same rule.
_PLACEHOLDER = re.compile(
    r"\{\{(?:SHOWDOC_IMAGE_[A-Z0-9_]+|"
    r"SHOWDOC_(?:UNSUPPORTED|OVERSIZED|CONVERSION_FAILED)_IMAGE_[A-Z0-9_]+|"
    r"SHOWDOC_EMBEDDED_\d{6})\}\}"
)
_PLACEHOLDER_SPLIT = re.compile(
    r"(\{\{(?:SHOWDOC_IMAGE_[A-Z0-9_]+|"
    r"SHOWDOC_(?:UNSUPPORTED|OVERSIZED|CONVERSION_FAILED)_IMAGE_[A-Z0-9_]+|"
    r"SHOWDOC_EMBEDDED_\d{6})\}\})"
)


def escape_text(text):
    if "{{SHOWDOC_" not in text:
        return _escape_literal(text)
    parts = _PLACEHOLDER_SPLIT.split(text)
    return "".join(
        part if _PLACEHOLDER.fullmatch(part) else _escape_literal(part)
        for part in parts
    )


def _escape_literal(text):
    return "".join("\\" + ch if ch in _ESCAPE_CHARS else ch for ch in text)
