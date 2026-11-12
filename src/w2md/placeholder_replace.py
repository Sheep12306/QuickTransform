"""Fill ShowDoc image URLs back into Markdown image placeholders.

The generated Markdown contains tokens such as ``{{SHOWDOC_IMAGE_000001}}``.
After a human pastes the images into ShowDoc, ShowDoc returns Markdown image
links.  This module validates the three counts (placeholders, extracted images,
ShowDoc URLs), builds an explicit placeholder -> URL mapping, and replaces only
the placeholders that are outside Markdown code blocks.

It never modifies the input files; callers write a new Markdown file and an
updated manifest.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path


PLACEHOLDER_TOKEN = re.compile(r"\{\{SHOWDOC_IMAGE_[A-Z0-9_]+\}\}")
PLACEHOLDER_DIGITS = re.compile(r"(\d+)\}\}$")
IMAGE_LINK = re.compile(
    r"!\[([^\]]*)\]\((?![<])([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)"
)
IMAGE_LINK_ANGLE = re.compile(
    r"!\[([^\]]*)\]\(<([^>\s]+)>(?:\s+[\"'][^\"']*[\"'])?\)"
)
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
class UrlItem:
    index: int
    url: str
    alt: str = ""
    line: int = 0
    valid: bool = True
    error: str | None = None

    def to_dict(self):
        return {
            "index": self.index,
            "url": self.url,
            "alt": self.alt,
            "line": self.line,
            "valid": self.valid,
            "error": self.error,
        }


@dataclass
class MappingItem:
    placeholder: str
    order: int
    url: str | None
    alt_text: str
    local_path: str | None = None
    filename: str | None = None
    status: str = "pending"
    error: str | None = None

    def to_dict(self):
        return {
            "placeholder": self.placeholder,
            "order": self.order,
            "url": self.url,
            "alt_text": self.alt_text,
            "local_path": self.local_path,
            "filename": self.filename,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class AnalysisResult:
    placeholders: list = field(default_factory=list)
    urls: list = field(default_factory=list)
    mapping: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    code_block_placeholders: list = field(default_factory=list)
    can_generate: bool = False
    manifest_provided: bool = False

    def to_dict(self):
        return {
            "placeholders": [item.to_dict() for item in self.placeholders],
            "urls": [item.to_dict() for item in self.urls],
            "mapping": [item.to_dict() for item in self.mapping],
            "counts": self.counts,
            "errors": self.errors,
            "warnings": self.warnings,
            "code_block_placeholders": [
                item.to_dict() for item in self.code_block_placeholders
            ],
            "can_generate": self.can_generate,
            "manifest_provided": self.manifest_provided,
        }


@dataclass
class ReplacementResult:
    markdown: str
    replaced_count: int = 0
    skipped_code_count: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self):
        return {
            "markdown": self.markdown,
            "replaced_count": self.replaced_count,
            "skipped_code_count": self.skipped_code_count,
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


def extract_image_urls(showdoc_markdown):
    """Extract Markdown image URLs in source order, skipping code blocks."""

    urls = []
    for line_number, (content, _ending, is_code) in enumerate(
        _scan_lines(showdoc_markdown), start=1
    ):
        if is_code:
            continue
        masked = _mask_inline_code(content)
        for match in _iter_image_links(masked):
            url = match.group(2)
            error = _url_error(url)
            urls.append(
                UrlItem(
                    index=len(urls) + 1,
                    url=url,
                    alt=match.group(1).strip(),
                    line=line_number,
                    valid=error is None,
                    error=error,
                )
            )
    return urls


def analyze_replacement(markdown, showdoc_markdown, manifest=None, mapping=None):
    """Validate counts and build the default or manually supplied mapping."""

    occurrences = list_placeholders(markdown)
    outside = [item for item in occurrences if not item.in_code]
    code_items = [item for item in occurrences if item.in_code]
    unique = _unique_placeholders(outside)
    urls = extract_image_urls(showdoc_markdown)
    manifest_entries = _manifest_entries(manifest)
    manifest_provided = bool(manifest_entries)

    explicit = _explicit_mapping(mapping)
    default_urls = [item.url for item in urls]
    mapping_items = []
    used_urls = set()
    errors = []
    warnings = []

    if not unique:
        errors.append("没有检测到可替换的占位符")
    if not urls:
        errors.append("没有检测到 ShowDoc 图片 URL")

    if code_items:
        warnings.append(
            "代码块中有 {0} 个占位符，已跳过，不会参与替换".format(len(code_items))
        )
    if len(unique) < len(outside):
        warnings.append(
            "Markdown 中有 {0} 个占位符出现位置，但只有 {1} 个唯一占位符；"
            "重复占位符会共用同一 URL".format(len(outside), len(unique))
        )

    for index, occurrence in enumerate(unique):
        entry = _manifest_entry_for(manifest_entries, occurrence.placeholder, occurrence.order)
        alt_text = (entry or {}).get("alt_text") or "图片{0}".format(occurrence.order)
        local_path = (entry or {}).get("local_path")
        filename = Path(local_path).name if local_path else None

        if explicit is not None:
            url = explicit.get(occurrence.placeholder)
            source = "manual"
        else:
            url = default_urls[index] if index < len(default_urls) else None
            source = "order"

        status = "matched"
        error = None
        if not url:
            status = "missing_url"
            error = "没有为 {0} 分配 ShowDoc URL".format(occurrence.placeholder)
        else:
            url_error = _url_error(url)
            if url_error:
                status = "invalid_url"
                error = url_error
            elif source == "manual" and url not in default_urls:
                warnings.append(
                    "{0} 使用了 ShowDoc 源码之外的 URL：{1}".format(
                        occurrence.placeholder, url
                    )
                )
            used_urls.add(url)

        mapping_items.append(
            MappingItem(
                placeholder=occurrence.placeholder,
                order=occurrence.order,
                url=url,
                alt_text=alt_text,
                local_path=local_path,
                filename=filename,
                status=status,
                error=error,
            )
        )

    missing = [item for item in mapping_items if not item.url]
    invalid = [item for item in mapping_items if item.status == "invalid_url"]
    if missing:
        errors.append(
            "缺少 URL 的占位符：{0}".format("、".join(item.placeholder for item in missing))
        )
    if invalid:
        errors.append(
            "URL 非法的占位符：{0}".format("、".join(item.placeholder for item in invalid))
        )

    if len(unique) != len(urls):
        errors.append(
            "数量不一致：Markdown 有 {0} 个可替换占位符，ShowDoc 源码检测到 {1} 个图片 URL".format(
                len(unique), len(urls)
            )
        )
        if len(urls) > len(unique):
            extra = urls[len(unique):]
            errors.append(
                "多余 URL：{0}".format(
                    "、".join("第{0}个 {1}".format(item.index, item.url) for item in extra)
                )
            )
        elif len(unique) > len(urls):
            missing_tokens = [item.placeholder for item in unique[len(urls):]]
            errors.append("缺少 URL 的占位符：{0}".format("、".join(missing_tokens)))

    if manifest_entries and len(manifest_entries) != len(unique):
        errors.append(
            "manifest 有 {0} 张图片，Markdown 有 {1} 个唯一占位符，数量不一致".format(
                len(manifest_entries), len(unique)
            )
        )

    if not manifest_provided:
        warnings.append("未提供 manifest，缩略图、原 alt 文本和 manifest 更新不可用")

    if DATA_IMAGE.search(markdown) or DATA_IMAGE.search(showdoc_markdown):
        errors.append("输入内容包含 data:image Base64，最终 Markdown 不允许包含 Base64 图片")

    unused = [item.url for item in urls if item.url not in used_urls]
    if unused:
        warnings.append("有 {0} 个 ShowDoc URL 未被映射使用".format(len(unused)))

    errors = _dedupe(errors)
    warnings = _dedupe(warnings)
    can_generate = not errors and all(item.status == "matched" for item in mapping_items)

    return AnalysisResult(
        placeholders=outside,
        urls=urls,
        mapping=mapping_items,
        counts={
            "placeholder_occurrences": len(outside),
            "placeholders": len(unique),
            "code_block_placeholders": len(code_items),
            "urls": len(urls),
            "manifest_images": len(manifest_entries),
            "matched": sum(1 for item in mapping_items if item.status == "matched"),
            "missing": len(missing),
            "invalid": len(invalid),
        },
        errors=errors,
        warnings=warnings,
        code_block_placeholders=code_items,
        can_generate=can_generate,
        manifest_provided=manifest_provided,
    )


def replace_placeholders(markdown, mapping, alt_by_placeholder=None, analysis=None):
    """Replace placeholders outside code blocks using an explicit token map."""

    mapping = _mapping_dict(mapping)
    alt_by_placeholder = alt_by_placeholder or {}
    errors = []
    warnings = []
    replaced = 0
    skipped_code = 0
    output = []

    outside = _unique_placeholders(
        [item for item in list_placeholders(markdown) if not item.in_code]
    )
    for item in outside:
        token = item.placeholder
        url = mapping.get(token)
        if not url:
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
            url = mapping[token]
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
        errors=errors,
        warnings=warnings,
    )


def update_manifest(manifest, mapping):
    """Return a copy of the manifest with final URLs and replacement status."""

    if not isinstance(manifest, dict):
        return None
    updated = copy.deepcopy(manifest)
    mapping = _mapping_dict(mapping)
    images = updated.get("images")
    if not isinstance(images, list):
        return updated

    matched = 0
    missing = 0
    for entry in images:
        if not isinstance(entry, dict):
            continue
        token = entry.get("placeholder")
        url = mapping.get(token)
        if url:
            entry["showdoc_url"] = url
            entry["upload_status"] = "url_received"
            entry["replacement_status"] = "replaced"
            matched += 1
        else:
            entry["showdoc_url"] = None
            entry["replacement_status"] = "pending"
            missing += 1

    updated["replacement"] = {
        "matched": matched,
        "missing": missing,
        "total": len(images),
    }
    return updated


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


def _iter_image_links(line):
    seen = set()
    for match in IMAGE_LINK.finditer(line):
        seen.add(match.start())
        yield match
    for match in IMAGE_LINK_ANGLE.finditer(line):
        if match.start() not in seen:
            yield match


def _dedupe(items):
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


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
    if not url.startswith(("http://", "https://")):
        return "URL 必须以 http:// 或 https:// 开头"
    if re.search(r"\s", url):
        return "URL 不能包含空白字符"
    return None


def _manifest_entries(manifest):
    if not isinstance(manifest, dict):
        return []
    images = manifest.get("images")
    return images if isinstance(images, list) else []


def _manifest_entry_for(entries, placeholder, order):
    for entry in entries:
        if isinstance(entry, dict) and entry.get("placeholder") == placeholder:
            return entry
    for entry in entries:
        if isinstance(entry, dict) and entry.get("order") == order:
            return entry
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
