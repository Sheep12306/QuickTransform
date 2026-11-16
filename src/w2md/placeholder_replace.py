"""Shared Markdown placeholder scanning and replacement helpers.

``upload_result`` uses :func:`replace_placeholders` to fill *normal* image
placeholders after uploads succeed.  ``special_images`` uses the scanning
helpers and replaces only ``unsupported`` / ``oversized`` /
``conversion_failed`` tokens.  Neither workflow replaces by "the Nth URL";
callers always pass an explicit token -> URL mapping.

Placeholders inside fenced / indented / inline code are never replaced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


PLACEHOLDER_TOKEN = re.compile(r"\{\{SHOWDOC_IMAGE_[A-Z0-9_]+\}\}")
PLACEHOLDER_DIGITS = re.compile(r"(\d+)\}\}$")
DATA_IMAGE = re.compile(r"data:image/", re.IGNORECASE)
FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


@dataclass
class PlaceholderOccurrence:
    placeholder: str
    order: int
    line: int
    column: int
    in_code: bool = False

    def to_dict(self):
        return {
            "placeholder": self.placeholder,
            "order": self.order,
            "line": self.line,
            "column": self.column,
            "in_code": self.in_code,
        }


@dataclass
class ReplacementResult:
    markdown: str
    replaced_count: int = 0
    skipped_code_count: int = 0
    skipped_missing_count: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self):
        return {
            "markdown": self.markdown,
            "replaced_count": self.replaced_count,
            "skipped_code_count": self.skipped_code_count,
            "skipped_missing_count": self.skipped_missing_count,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def list_placeholders(markdown):
    """Return placeholder occurrences, including ones inside code blocks."""

    occurrences = []
    for line_number, (content, _ending, is_code) in enumerate(_scan_lines(markdown), start=1):
        masked = content if is_code else _mask_inline_code(content)
        for match in PLACEHOLDER_TOKEN.finditer(content):
            token = content[match.start():match.end()]
            inside_inline_code = (
                not is_code and not masked[match.start():match.end()].strip()
            )
            occurrences.append(
                PlaceholderOccurrence(
                    placeholder=token,
                    order=_placeholder_order(token) or (len(occurrences) + 1),
                    line=line_number,
                    column=match.start() + 1,
                    in_code=is_code or inside_inline_code,
                )
            )
    return occurrences


def replace_placeholders(
    markdown,
    mapping,
    alt_by_placeholder=None,
    analysis=None,
    partial=False,
):
    """Replace placeholders outside code blocks using an explicit token map.

    ``partial=True`` leaves tokens that are not present in ``mapping``
    untouched instead of failing.  This is what the upload-result importer
    needs: successful images become URLs, while failed / not-uploaded images
    keep their placeholder for a later retry.
    """

    mapping = _mapping_dict(mapping)
    alt_by_placeholder = alt_by_placeholder or {}
    errors = []
    warnings = []
    replaced = 0
    skipped_code = 0
    skipped_missing = 0
    output = []

    outside = _unique_placeholders(
        [item for item in list_placeholders(markdown) if not item.in_code]
    )
    for item in outside:
        token = item.placeholder
        url = mapping.get(token)
        if not url:
            if partial:
                skipped_missing += 1
                continue
            errors.append("占位符 {0} 没有对应的 URL".format(token))
            continue
        url_error = _url_error(url)
        if url_error:
            errors.append("占位符 {0} 的 URL 非法：{1}".format(token, url_error))

    if errors:
        return ReplacementResult(
            markdown=markdown,
            errors=errors,
            warnings=warnings,
        )

    for content, ending, is_code in _scan_lines(markdown):
        if is_code:
            skipped_code += len(PLACEHOLDER_TOKEN.findall(content))
            output.append(content + ending)
            continue

        masked = _mask_inline_code(content)
        matches = list(PLACEHOLDER_TOKEN.finditer(masked))
        skipped_code += len(PLACEHOLDER_TOKEN.findall(content)) - len(matches)
        for match in reversed(matches):
            token = content[match.start():match.end()]
            url = mapping.get(token)
            if not url:
                continue
            alt = alt_by_placeholder.get(token) or _fallback_alt(token)
            replacement = "![{0}]({1})".format(
                _escape_alt(alt), _format_url(url)
            )
            content = content[:match.start()] + replacement + content[match.end():]
            replaced += 1
        output.append(content + ending)

    final = "".join(output)
    if DATA_IMAGE.search(final):
        errors.append("最终 Markdown 仍包含 data:image Base64，已停止生成")

    if analysis is not None and analysis.code_block_placeholders:
        warnings.append(
            "代码块中有 {0} 个占位符未替换".format(len(analysis.code_block_placeholders))
        )

    return ReplacementResult(
        markdown=final if not errors else markdown,
        replaced_count=replaced,
        skipped_code_count=skipped_code,
        skipped_missing_count=skipped_missing,
        errors=errors,
        warnings=warnings,
    )


def _scan_lines(text):
    """Yield ``(content, line_ending, is_code_block)`` per line."""

    raw_lines = text.splitlines(keepends=True)
    contents = []
    endings = []
    for raw in raw_lines:
        if raw.endswith("\r\n"):
            contents.append(raw[:-2])
            endings.append("\r\n")
        elif raw.endswith("\n") or raw.endswith("\r"):
            contents.append(raw[:-1])
            endings.append(raw[-1])
        else:
            contents.append(raw)
            endings.append("")

    flags = _code_block_flags(contents)
    return [
        (content, ending, flag)
        for content, ending, flag in zip(contents, endings, flags)
    ]


def _code_block_flags(lines):
    flags = []
    fence = None
    indented = False
    previous_blank = True
    previous_nonblank = ""

    for line in lines:
        stripped = line.strip()
        match = FENCE.match(line)
        if fence is not None:
            flags.append(True)
            if (
                match is not None
                and match.group(2)[0] == fence[0]
                and len(match.group(2)) >= fence[1]
                and not match.group(3).strip()
            ):
                fence = None
            previous_blank = False
            if stripped:
                previous_nonblank = line
            continue

        if match is not None:
            fence = (match.group(2)[0], len(match.group(2)))
            flags.append(True)
            previous_blank = False
            previous_nonblank = line
            continue

        if indented:
            if not stripped or line.startswith("    ") or line.startswith("\t"):
                flags.append(True)
                previous_blank = not stripped
                if stripped:
                    previous_nonblank = line
                continue
            indented = False

        if (
            (previous_blank or not flags)
            and stripped
            and (line.startswith("    ") or line.startswith("\t"))
            and not LIST_ITEM.match(previous_nonblank)
        ):
            indented = True
            flags.append(True)
            previous_blank = False
            previous_nonblank = line
            continue

        flags.append(False)
        previous_blank = not stripped
        if stripped:
            previous_nonblank = line

    return flags


def _mask_inline_code(line):
    chars = list(line)
    index = 0
    while index < len(line):
        if line[index] != "`":
            index += 1
            continue
        start = index
        while index < len(line) and line[index] == "`":
            index += 1
        ticks = index - start
        search = index
        closed = False
        while search < len(line):
            if line[search] != "`":
                search += 1
                continue
            run_start = search
            while search < len(line) and line[search] == "`":
                search += 1
            if search - run_start == ticks:
                for position in range(start, search):
                    chars[position] = " "
                index = search
                closed = True
                break
        if not closed:
            break
    return "".join(chars)


def _unique_placeholders(occurrences):
    result = []
    seen = set()
    for item in occurrences:
        if item.placeholder in seen:
            continue
        seen.add(item.placeholder)
        result.append(item)
    return result


def _placeholder_order(token):
    match = PLACEHOLDER_DIGITS.search(token)
    return int(match.group(1)) if match else None


def _fallback_alt(token):
    return "图片{0}".format(_placeholder_order(token) or "")


def _escape_alt(alt):
    text = re.sub(r"\s+", " ", str(alt or "")).strip()
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _format_url(url):
    if re.search(r"[\s()]", url):
        return "<{0}>".format(url)
    return url


def _url_error(url):
    if not url:
        return "URL 为空"
    if url.lower().startswith("data:"):
        return "不允许使用 data:image Base64 URL"
    if not url.lower().startswith(("http://", "https://")):
        return "URL 必须以 http:// 或 https:// 开头"
    if re.search(r"\s", url):
        return "URL 不能包含空白字符"
    return None


def _explicit_mapping(mapping):
    if mapping is None:
        return None
    result = {}
    if isinstance(mapping, dict):
        for token, url in mapping.items():
            result[str(token)] = str(url) if url else None
        return result
    for item in mapping:
        token = item.get("placeholder") if isinstance(item, dict) else getattr(item, "placeholder", None)
        url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
        if token:
            result[str(token)] = str(url) if url else None
    return result


def _mapping_dict(mapping):
    if isinstance(mapping, dict):
        return {str(token): str(url) for token, url in mapping.items() if url}
    result = {}
    for item in mapping or []:
        token = item.get("placeholder") if isinstance(item, dict) else getattr(item, "placeholder", None)
        url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
        if token and url:
            result[str(token)] = str(url)
    return result
