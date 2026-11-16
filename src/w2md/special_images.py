"""Handle special image placeholders left after automatic upload-result filling.

The upload-result importer replaces normal images that were uploaded
successfully.  Images classified as ``unsupported`` / ``oversized`` /
``conversion_failed`` deliberately keep a special placeholder such as
``{{SHOWDOC_OVERSIZED_IMAGE_000012}}``.  A human uploads those images to
ShowDoc manually and then uses this module to paste one URL per special image.

This module never touches normal ``{{SHOWDOC_IMAGE_000001}}`` placeholders:
normal images belong to the upload-result workflow.  It does, however, report
any normal placeholder residue so a half-finished document cannot silently be
published.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from .placeholder_replace import (
    DATA_IMAGE,
    _escape_alt,
    _explicit_mapping,
    _fallback_alt,
    _format_url,
    _mapping_dict,
    _mask_inline_code,
    _scan_lines,
    _url_error,
)
from .upload_result import normalize_manifest


SPECIAL_PLACEHOLDER = re.compile(
    r"\{\{SHOWDOC_(UNSUPPORTED|OVERSIZED|CONVERSION_FAILED)_IMAGE_\d{6}\}\}"
)
NORMAL_PLACEHOLDER = re.compile(r"\{\{SHOWDOC_IMAGE_\d{6}\}\}")
ANY_PLACEHOLDER = re.compile(r"\{\{SHOWDOC_[A-Z0-9_]+\}\}")

COMPATIBILITY_LABELS = {
    "unsupported": "不支持格式",
    "oversized": "图片超限",
    "conversion_failed": "转换失败",
}

STATUS_LABELS = {
    "pending": "待处理",
    "matched": "已填写 URL",
    "invalid_url": "URL 非法",
    "not_in_markdown": "Markdown 中无占位符",
    "in_code_only": "仅出现在代码块",
}


@dataclass
class SpecialImageItem:
    index: int
    sequence: int
    occurrence_id: str
    placeholder: str
    compatibility: str
    compatibility_label: str
    alt_text: str
    file_name: str | None = None
    source_file: str | None = None
    upload_file: str | None = None
    section: str = ""
    reason: str = ""
    size: int | None = None
    source_format: str | None = None
    url: str | None = None
    status: str = "pending"
    status_label: str = "待处理"
    error: str | None = None
    in_markdown: bool = False
    occurrence_count: int = 0
    code_occurrence_count: int = 0
    line: int | None = None
    column: int | None = None
    occurrences: list = field(default_factory=list)

    def to_dict(self):
        return {
            "index": self.index,
            "sequence": self.sequence,
            "occurrence_id": self.occurrence_id,
            "placeholder": self.placeholder,
            "compatibility": self.compatibility,
            "compatibility_label": self.compatibility_label,
            "alt_text": self.alt_text,
            "file_name": self.file_name,
            "source_file": self.source_file,
            "upload_file": self.upload_file,
            "section": self.section,
            "reason": self.reason,
            "size": self.size,
            "source_format": self.source_format,
            "url": self.url,
            "status": self.status,
            "status_label": self.status_label,
            "error": self.error,
            "in_markdown": self.in_markdown,
            "occurrence_count": self.occurrence_count,
            "code_occurrence_count": self.code_occurrence_count,
            "line": self.line,
            "column": self.column,
            "occurrences": list(self.occurrences),
        }


@dataclass
class SpecialAnalysisResult:
    items: list = field(default_factory=list)
    normal_residue: list = field(default_factory=list)
    other_residue: list = field(default_factory=list)
    unknown_placeholders: list = field(default_factory=list)
    code_block_placeholders: list = field(default_factory=list)
    occurrence_duplicates: list = field(default_factory=list)
    placeholder_duplicates: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    can_generate: bool = False
    manifest_provided: bool = False
    document_id: str | None = None

    def to_dict(self):
        return {
            "items": [item.to_dict() for item in self.items],
            "normal_residue": list(self.normal_residue),
            "other_residue": list(self.other_residue),
            "unknown_placeholders": list(self.unknown_placeholders),
            "code_block_placeholders": list(self.code_block_placeholders),
            "occurrence_duplicates": list(self.occurrence_duplicates),
            "placeholder_duplicates": list(self.placeholder_duplicates),
            "counts": self.counts,
            "checks": self.checks,
            "errors": self.errors,
            "warnings": self.warnings,
            "can_generate": self.can_generate,
            "manifest_provided": self.manifest_provided,
            "document_id": self.document_id,
        }


@dataclass
class SpecialReplacementResult:
    markdown: str
    replaced_count: int = 0
    skipped_code_count: int = 0
    final_check: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self):
        return {
            "markdown": self.markdown,
            "replaced_count": self.replaced_count,
            "skipped_code_count": self.skipped_code_count,
            "final_check": self.final_check,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def scan_placeholders(markdown):
    """Return ``(body_occurrences, code_occurrences)`` for every token kind."""

    body = []
    code = []
    for line_number, (content, _ending, is_code) in enumerate(
        _scan_lines(markdown or ""), start=1
    ):
        masked = content if is_code else _mask_inline_code(content)
        for match in ANY_PLACEHOLDER.finditer(content):
            token = content[match.start():match.end()]
            inside_inline = (
                not is_code and not masked[match.start():match.end()].strip()
            )
            occurrence = {
                "placeholder": token,
                "kind": _token_kind(token),
                "line": line_number,
                "column": match.start() + 1,
                "in_code": is_code or inside_inline,
            }
            if occurrence["in_code"]:
                code.append(occurrence)
            else:
                body.append(occurrence)
    return body, code


def analyze_special_images(markdown, manifest, urls=None):
    """Validate a Markdown document and its special images.

    ``urls`` maps special placeholder tokens to manually entered ShowDoc URLs.
    An explicit empty value clears a URL that may already be stored in the
    manifest.
    """

    markdown = markdown or ""
    document_id, images = normalize_manifest(manifest)
    special_images = [image for image in images if image.is_special]
    manifest_provided = isinstance(manifest, dict) and bool(images)

    body, code = scan_placeholders(markdown)
    body_by_token = _group_occurrences(body)
    code_by_token = _group_occurrences(code)

    normal_residue = [
        occurrence for occurrence in body if occurrence["kind"] == "normal"
    ]
    other_residue = [
        occurrence for occurrence in body if occurrence["kind"] == "other"
    ]
    code_block_placeholders = list(code)

    occurrence_duplicates = _duplicate_occurrences(images)
    placeholder_duplicates = _duplicate_special_placeholders(special_images)
    duplicate_tokens = {item["placeholder"] for item in placeholder_duplicates}

    explicit = _explicit_mapping(urls) if urls is not None else {}
    manifest_special = {image.placeholder: image for image in special_images}
    unknown_placeholders = [
        {
            "placeholder": token,
            "occurrences": occurrences,
        }
        for token, occurrences in sorted(body_by_token.items())
        if _token_kind(token) == "special" and token not in manifest_special
    ]

    items = []
    for index, image in enumerate(special_images, start=1):
        plan = explicit.get(image.placeholder) if explicit else None
        if image.placeholder in explicit:
            url = (plan or "").strip() or None
        else:
            url = _manifest_url(image)

        body_occurrences = body_by_token.get(image.placeholder, [])
        code_occurrences = code_by_token.get(image.placeholder, [])
        first = body_occurrences[0] if body_occurrences else None
        in_markdown = bool(body_occurrences)
        status = "pending"
        status_label = "待处理"
        error = None

        if url:
            url_error = _url_error(url)
            if url_error:
                status = "invalid_url"
                status_label = "URL 非法"
                error = url_error
            elif in_markdown:
                status = "matched"
                status_label = "已填写 URL"
            else:
                status = "not_in_markdown"
                status_label = "Markdown 中无占位符"
        elif in_markdown:
            status = "pending"
            status_label = "待处理"
        elif code_occurrences:
            status = "in_code_only"
            status_label = "仅出现在代码块"
        else:
            status = "not_in_markdown"
            status_label = "Markdown 中无占位符"

        if image.placeholder in duplicate_tokens:
            error = error or "manifest 中该占位符重复，无法确定对应图片"

        items.append(
            SpecialImageItem(
                index=index,
                sequence=image.sequence,
                occurrence_id=image.occurrence_id,
                placeholder=image.placeholder,
                compatibility=image.compatibility,
                compatibility_label=COMPATIBILITY_LABELS.get(
                    image.compatibility, image.compatibility
                ),
                alt_text=image.alt_text,
                file_name=image.file_name,
                source_file=image.source_file_name,
                upload_file=image.upload_file_name,
                section=image.section,
                reason=image.reason or image.compatibility_reason,
                size=image.size,
                source_format=image.source_format,
                url=url,
                status=status,
                status_label=status_label,
                error=error,
                in_markdown=in_markdown,
                occurrence_count=len(body_occurrences),
                code_occurrence_count=len(code_occurrences),
                line=first["line"] if first else None,
                column=first["column"] if first else None,
                occurrences=body_occurrences,
            )
        )

    pending = [item for item in items if item.status == "pending"]
    invalid = [item for item in items if item.status == "invalid_url"]
    matched = [item for item in items if item.status == "matched"]
    in_markdown = [item for item in items if item.in_markdown]
    not_in_markdown = [item for item in items if not item.in_markdown]
    in_code_only = [item for item in items if item.status == "in_code_only"]

    errors = []
    warnings = []

    if not manifest_provided:
        errors.append("缺少 manifest.json，或 manifest 中没有图片记录")
    elif not special_images:
        errors.append(
            "manifest 中没有特殊图片（unsupported / oversized / conversion_failed），"
            "无需使用本工具"
        )
    if not markdown.strip():
        errors.append("请选择或粘贴 Markdown 源码")

    if normal_residue:
        tokens = _unique_tokens(normal_residue)
        errors.append(
            "普通占位符残留 {0} 个（{1} 个唯一 token）：{2}。"
            "请先使用「上传结果导入」完成普通图片回填。".format(
                len(normal_residue),
                len(tokens),
                _join_tokens(tokens),
            )
        )
    if other_residue:
        tokens = _unique_tokens(other_residue)
        errors.append(
            "Markdown 中有 {0} 个未识别的占位符残留：{1}".format(
                len(other_residue), _join_tokens(tokens)
            )
        )
    if pending:
        errors.append(
            "仍有 {0} 张特殊图片待处理：{1}".format(
                len(pending), _join_tokens([item.placeholder for item in pending])
            )
        )
    if invalid:
        errors.append(
            "有 {0} 个 URL 无效：{1}".format(
                len(invalid),
                "；".join(
                    "{0}（{1}）".format(item.placeholder, item.error)
                    for item in invalid
                ),
            )
        )
    if occurrence_duplicates:
        errors.append(
            "manifest 中 occurrence_id 不唯一：{0}".format(
                "；".join(
                    "{0}（{1}）".format(
                        item["occurrence_id"],
                        _join_tokens(item["placeholders"]),
                    )
                    for item in occurrence_duplicates
                )
            )
        )
    if placeholder_duplicates:
        errors.append(
            "manifest 中特殊图片占位符重复：{0}".format(
                _join_tokens([item["placeholder"] for item in placeholder_duplicates])
            )
        )
    if unknown_placeholders:
        errors.append(
            "Markdown 中有 {0} 个 manifest 未包含的特殊占位符：{1}".format(
                len(unknown_placeholders),
                _join_tokens([item["placeholder"] for item in unknown_placeholders]),
            )
        )

    if not in_markdown and special_images:
        warnings.append(
            "Markdown 正文中没有发现 manifest 里的特殊占位符；"
            "如果图片已经处理过，可以直接生成并做最终残留检查"
        )
    if in_code_only:
        warnings.append(
            "有 {0} 张特殊图片只出现在代码块中，生成时不会替换：{1}".format(
                len(in_code_only),
                _join_tokens([item.placeholder for item in in_code_only]),
            )
        )
    if code_block_placeholders:
        warnings.append(
            "代码块中有 {0} 个占位符，生成时会保持原样".format(
                len(code_block_placeholders)
            )
        )
    unused_urls = [
        token
        for token in (explicit or {})
        if token not in manifest_special
    ]
    if unused_urls:
        warnings.append(
            "以下 URL 对应的占位符不在 manifest 中，已忽略：{0}".format(
                _join_tokens(sorted(unused_urls))
            )
        )
    filled_without_placeholder = [
        item.placeholder
        for item in items
        if item.url and item.status == "not_in_markdown"
    ]
    if filled_without_placeholder:
        warnings.append(
            "已填写 URL，但 Markdown 正文中没有对应占位符：{0}".format(
                _join_tokens(filled_without_placeholder)
            )
        )

    checks = {
        "normal_residue": {
            "ok": not normal_residue,
            "count": len(normal_residue),
            "tokens": _unique_tokens(normal_residue),
        },
        "pending": {
            "ok": not pending,
            "count": len(pending),
        },
        "urls": {
            "ok": not invalid,
            "invalid": len(invalid),
            "filled": len(matched),
        },
        "occurrence_ids": {
            "ok": not occurrence_duplicates,
            "duplicates": len(occurrence_duplicates),
        },
        "final_residue": {
            "ok": None,
            "count": None,
        },
    }

    return SpecialAnalysisResult(
        items=items,
        normal_residue=normal_residue,
        other_residue=other_residue,
        unknown_placeholders=unknown_placeholders,
        code_block_placeholders=code_block_placeholders,
        occurrence_duplicates=occurrence_duplicates,
        placeholder_duplicates=placeholder_duplicates,
        counts={
            "manifest_images": len(images),
            "special_images": len(special_images),
            "normal_images": len(images) - len(special_images),
            "in_markdown": len(in_markdown),
            "in_code_only": len(in_code_only),
            "matched": len(matched),
            "pending": len(pending),
            "invalid_url": len(invalid),
            "not_in_markdown": len(not_in_markdown),
            "unknown_placeholders": len(unknown_placeholders),
            "normal_residue_occurrences": len(normal_residue),
            "normal_residue_tokens": len(_unique_tokens(normal_residue)),
            "other_residue_occurrences": len(other_residue),
            "code_block_placeholders": len(code_block_placeholders),
            "occurrence_id_duplicates": len(occurrence_duplicates),
            "placeholder_duplicates": len(placeholder_duplicates),
        },
        checks=checks,
        errors=_dedupe(errors),
        warnings=_dedupe(warnings),
        can_generate=not errors,
        manifest_provided=manifest_provided,
        document_id=document_id,
    )


def apply_special_images(markdown, mapping, alt_by_placeholder=None):
    """Replace special placeholders outside code blocks with image links."""

    mapping = _mapping_dict(mapping)
    alt_by_placeholder = alt_by_placeholder or {}
    errors = []
    warnings = []

    for token, url in mapping.items():
        if not SPECIAL_PLACEHOLDER.fullmatch(token):
            continue
        url_error = _url_error(url)
        if url_error:
            errors.append("占位符 {0} 的 URL 非法：{1}".format(token, url_error))
    if errors:
        return SpecialReplacementResult(
            markdown=markdown,
            errors=errors,
            warnings=warnings,
            final_check={"passed": False, "errors": list(errors)},
        )

    replaced = 0
    skipped_code = 0
    output = []
    for content, ending, is_code in _scan_lines(markdown or ""):
        if is_code:
            skipped_code += len(SPECIAL_PLACEHOLDER.findall(content))
            output.append(content + ending)
            continue

        masked = _mask_inline_code(content)
        matches = list(SPECIAL_PLACEHOLDER.finditer(masked))
        skipped_code += len(SPECIAL_PLACEHOLDER.findall(content)) - len(matches)
        for match in reversed(matches):
            token = content[match.start():match.end()]
            url = mapping.get(token)
            if not url:
                continue
            alt = alt_by_placeholder.get(token) or _fallback_alt(token)
            replacement = "![{0}]({1})".format(_escape_alt(alt), _format_url(url))
            content = content[:match.start()] + replacement + content[match.end():]
            replaced += 1
        output.append(content + ending)

    final = "".join(output)
    body, code = scan_placeholders(final)
    remaining_normal = [
        occurrence for occurrence in body if occurrence["kind"] == "normal"
    ]
    remaining_special = [
        occurrence for occurrence in body if occurrence["kind"] == "special"
    ]
    remaining_other = [
        occurrence for occurrence in body if occurrence["kind"] == "other"
    ]

    if remaining_normal:
        errors.append(
            "最终 Markdown 仍包含 {0} 个普通占位符：{1}".format(
                len(remaining_normal), _join_tokens(_unique_tokens(remaining_normal))
            )
        )
    if remaining_special:
        errors.append(
            "最终 Markdown 仍包含 {0} 个特殊占位符：{1}".format(
                len(remaining_special), _join_tokens(_unique_tokens(remaining_special))
            )
        )
    if remaining_other:
        errors.append(
            "最终 Markdown 仍包含 {0} 个未识别占位符：{1}".format(
                len(remaining_other), _join_tokens(_unique_tokens(remaining_other))
            )
        )
    if code:
        warnings.append(
            "代码块中仍有 {0} 个占位符（按规则不替换）".format(len(code))
        )
    if DATA_IMAGE.search(final):
        errors.append("最终 Markdown 包含 data:image Base64，已停止生成")

    final_check = {
        "passed": not errors,
        "remaining_total": len(body),
        "remaining_normal": len(remaining_normal),
        "remaining_special": len(remaining_special),
        "remaining_other": len(remaining_other),
        "code_block": len(code),
        "tokens": _unique_tokens(body),
        "errors": list(errors),
    }

    return SpecialReplacementResult(
        markdown=final if not errors else markdown,
        replaced_count=replaced,
        skipped_code_count=skipped_code,
        final_check=final_check,
        errors=errors,
        warnings=warnings,
    )


def update_special_manifest(manifest, mapping, analysis=None):
    """Return a copy of the manifest with manually supplied special URLs."""

    if not isinstance(manifest, dict):
        return None
    updated = copy.deepcopy(manifest)
    mapping = _mapping_dict(mapping)
    _document_id, images = normalize_manifest(updated)
    resolved_urls = (
        {item.placeholder: item.url for item in analysis.items}
        if analysis is not None
        else {}
    )

    matched = 0
    pending = 0
    for image in images:
        if not image.is_special:
            continue
        entry = image.raw
        if not isinstance(entry, dict):
            continue
        url = mapping.get(image.placeholder)
        if url:
            entry["showdoc_url"] = url
            entry["upload_status"] = "url_received"
            entry["replacement_status"] = "replaced"
            entry["special_url_manual"] = True
            matched += 1
        else:
            entry["showdoc_url"] = resolved_urls.get(image.placeholder)
            entry["replacement_status"] = "pending"
            pending += 1

    updated["special_replacement"] = {
        "matched": matched,
        "pending": pending,
        "total": matched + pending,
    }
    return updated


def _token_kind(token):
    if SPECIAL_PLACEHOLDER.fullmatch(token):
        return "special"
    if NORMAL_PLACEHOLDER.fullmatch(token):
        return "normal"
    return "other"


def _group_occurrences(occurrences):
    grouped = {}
    for occurrence in occurrences:
        grouped.setdefault(occurrence["placeholder"], []).append(occurrence)
    return grouped


def _manifest_url(image):
    raw = image.raw if isinstance(image.raw, dict) else {}
    url = raw.get("showdoc_url") or raw.get("replaced_url")
    return str(url).strip() if url else None


def _duplicate_occurrences(images):
    grouped = {}
    for image in images:
        grouped.setdefault(image.occurrence_id, []).append(image.placeholder)
    return [
        {"occurrence_id": occurrence_id, "placeholders": placeholders}
        for occurrence_id, placeholders in sorted(grouped.items())
        if len(placeholders) > 1
    ]


def _duplicate_special_placeholders(special_images):
    grouped = {}
    for image in special_images:
        grouped.setdefault(image.placeholder, 0)
        grouped[image.placeholder] += 1
    return [
        {"placeholder": token, "count": count}
        for token, count in sorted(grouped.items())
        if count > 1
    ]


def _unique_tokens(occurrences):
    result = []
    seen = set()
    for occurrence in occurrences:
        token = occurrence["placeholder"]
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def _join_tokens(tokens, limit=12):
    tokens = list(tokens)
    if len(tokens) > limit:
        return "、".join(tokens[:limit]) + " 等 {0} 个".format(len(tokens))
    return "、".join(tokens)


def _dedupe(items):
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
