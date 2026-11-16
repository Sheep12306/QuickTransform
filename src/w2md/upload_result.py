"""Import ShowDoc upload records and fill only the images that succeeded.

The browser extension records one upload per image and reports the original
file SHA-256.  This module deliberately never maps by "the Nth successful URL".
Every replacement is an explicit mapping:

    occurrence_id / placeholder -> manifest SHA-256 -> successful URL

A failed image in the middle of the document therefore keeps its placeholder
and cannot shift later images.  Successful images that share the same media
bytes (same SHA-256) reuse the same URL.
"""

from __future__ import annotations

import base64
import csv
import html
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .image_extract import (
    COMPATIBILITY_CONVERSION_FAILED,
    COMPATIBILITY_CONVERTED,
    COMPATIBILITY_OVERSIZED,
    COMPATIBILITY_EMBEDDED,
    COMPATIBILITY_SUPPORTED,
    COMPATIBILITY_UNSUPPORTED,
    CONVERSION_FAILED_PREFIX,
    EMBEDDED_PREFIX,
    OVERSIZED_PREFIX,
    SPECIAL_COMPATIBILITIES,
    UNSUPPORTED_PREFIX,
    occurrence_id_for,
    placeholder_for,
    placeholder_for_compatibility,
)
from .placeholder_replace import (
    DATA_IMAGE,
    _mask_inline_code,
    _scan_lines,
    replace_placeholders,
)


SCHEMA_VERSION = 1
MODES = ("partial", "strict", "fill_remaining")
MODE_ALIASES = {
    "partial": "partial",
    "partial_success": "partial",
    "strict": "strict",
    "fill": "fill_remaining",
    "fill_remaining": "fill_remaining",
    "fill-remaining": "fill_remaining",
    "remaining": "fill_remaining",
}
IMAGE_STATUSES = (
    "success",
    "failed",
    "not_uploaded",
    "unmatched",
    "pending",
    "interrupted",
    "unsupported",
    "oversized",
    "conversion_failed",
    "unexpected_upload",
)
UPLOAD_STATUSES = {
    "success",
    "failed",
    "not_uploaded",
    "unmatched",
    "pending",
    "interrupted",
    "unsupported",
    "oversized",
    "conversion_failed",
    "unexpected_upload",
}

SPECIAL_PLACEHOLDER_PREFIXES = {
    COMPATIBILITY_UNSUPPORTED: UNSUPPORTED_PREFIX,
    COMPATIBILITY_OVERSIZED: OVERSIZED_PREFIX,
    COMPATIBILITY_CONVERSION_FAILED: CONVERSION_FAILED_PREFIX,
    COMPATIBILITY_EMBEDDED: EMBEDDED_PREFIX,
}
SPECIAL_PLACEHOLDER = re.compile(
    r"\{\{SHOWDOC_(?:UNSUPPORTED|OVERSIZED|CONVERSION_FAILED)_IMAGE_\d{6}\}\}"
    r"|\{\{SHOWDOC_EMBEDDED_\d{6}\}\}"
)

_HTTP_URL = re.compile(r"^https?://", re.IGNORECASE)
_DATA_URL = re.compile(r"^data:", re.IGNORECASE)
_DIGITS = re.compile(r"(\d+)")


@dataclass
class ManifestImage:
    index: int
    sequence: int
    occurrence_id: str
    placeholder: str
    source_path: str | None = None
    source_file_name: str | None = None
    upload_path: str | None = None
    upload_file_name: str | None = None
    local_file: str | None = None
    local_path: str | None = None
    file_name: str | None = None
    source_sha256: str | None = None
    upload_sha256: str | None = None
    sha256: str | None = None
    source_format: str | None = None
    upload_format: str | None = None
    source_size: int | None = None
    size: int | None = None
    mime_type: str | None = None
    compatibility: str = COMPATIBILITY_SUPPORTED
    requires_conversion: bool = False
    compatibility_reason: str = ""
    source_width: int | None = None
    source_height: int | None = None
    upload_width: int | None = None
    upload_height: int | None = None
    alt_text: str = ""
    section: str = ""
    context_before: str = ""
    context_after: str = ""
    is_duplicate: bool = False
    duplicate_of: str | None = None
    extraction_status: str = "extracted"
    raw: dict = field(default_factory=dict)

    # Import result fields.
    upload_status: str = "not_uploaded"
    url: str | None = None
    reason: str = ""
    needs_review: bool = False
    reused_by_sha: bool = False
    upload_ids: list = field(default_factory=list)
    in_markdown: bool = False
    line: int | None = None
    in_code: bool = False
    in_target: bool = False
    replaced: bool = False

    @property
    def is_special(self):
        return self.compatibility in SPECIAL_COMPATIBILITIES

    @property
    def target_hash(self):
        return self.upload_sha256 or self.sha256 or self.source_sha256

    def to_dict(self):
        return {
            "sequence": self.sequence,
            "occurrence_id": self.occurrence_id,
            "placeholder": self.placeholder,
            "source_file": self.source_path,
            "source_file_name": self.source_file_name,
            "source_format": self.source_format,
            "source_sha256": self.source_sha256,
            "upload_file": self.upload_path,
            "upload_file_name": self.upload_file_name,
            "upload_format": self.upload_format,
            "upload_sha256": self.upload_sha256,
            "sha256": self.sha256,
            "local_file": self.local_file,
            "local_path": self.local_path,
            "file_name": self.file_name,
            "size": self.size,
            "source_size": self.source_size,
            "mime_type": self.mime_type,
            "compatibility": self.compatibility,
            "requires_conversion": self.requires_conversion,
            "compatibility_reason": self.compatibility_reason,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "upload_width": self.upload_width,
            "upload_height": self.upload_height,
            "alt_text": self.alt_text,
            "section": self.section,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "is_duplicate": self.is_duplicate,
            "duplicate_of": self.duplicate_of,
            "extraction_status": self.extraction_status,
            "upload_status": self.upload_status,
            "url": self.url,
            "reason": self.reason,
            "needs_review": self.needs_review,
            "reused_by_sha": self.reused_by_sha,
            "upload_ids": list(self.upload_ids),
            "in_markdown": self.in_markdown,
            "line": self.line,
            "in_code": self.in_code,
            "in_target": self.in_target,
            "replaced": self.replaced,
            "is_special": self.is_special,
        }


@dataclass
class UploadRecord:
    index: int
    upload_id: str
    sequence: int | None
    occurrence_id: str | None
    placeholder: str | None
    file_name: str | None
    sha256: str | None
    status: str
    http_status: int | None
    response_success: object
    url: str | None
    error: str
    raw: dict = field(default_factory=dict)
    matched_index: int | None = None
    match_kind: str = ""
    reason: str = ""

    def to_dict(self):
        return {
            "upload_id": self.upload_id,
            "sequence": self.sequence,
            "occurrence_id": self.occurrence_id,
            "placeholder": self.placeholder,
            "file_name": self.file_name,
            "sha256": self.sha256,
            "status": self.status,
            "http_status": self.http_status,
            "response_success": self.response_success,
            "url": self.url,
            "error": self.error,
            "matched_index": self.matched_index,
            "match_kind": self.match_kind,
            "reason": self.reason,
        }


@dataclass
class ImportAnalysis:
    mode: str
    markdown: str = ""
    manifest: dict | None = None
    upload_result: dict | None = None
    manifest_provided: bool = False
    synthesized_manifest: bool = False
    upload_result_provided: bool = False
    document_id: str | None = None
    upload_document_id: str | None = None
    images: list = field(default_factory=list)
    uploads: list = field(default_factory=list)
    missing_entries: list = field(default_factory=list)
    targets: list = field(default_factory=list)
    unexpected_uploads: list = field(default_factory=list)
    ignored_special_uploads: list = field(default_factory=list)
    unknown_placeholders: list = field(default_factory=list)
    unknown_special_placeholders: list = field(default_factory=list)
    special_placeholders: list = field(default_factory=list)
    markdown_placeholders: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    declared: dict = field(default_factory=dict)
    declared_differences: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    requires_confirmation: bool = False
    can_generate: bool = False

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "manifest_provided": self.manifest_provided,
            "synthesized_manifest": self.synthesized_manifest,
            "upload_result_provided": self.upload_result_provided,
            "document_id": self.document_id,
            "upload_document_id": self.upload_document_id,
            "document_id_match": (
                None
                if not self.document_id or not self.upload_document_id
                else self.document_id == self.upload_document_id
            ),
            "images": [image.to_dict() for image in self.images],
            "targets": [image.to_dict() for image in self.targets],
            "uploads": [record.to_dict() for record in self.uploads],
            "unexpected_uploads": self.unexpected_uploads,
            "ignored_special_uploads": self.ignored_special_uploads,
            "unknown_placeholders": list(self.unknown_placeholders),
            "unknown_special_placeholders": list(self.unknown_special_placeholders),
            "special_placeholders": list(self.special_placeholders),
            "markdown_placeholders": list(self.markdown_placeholders),
            "counts": self.counts,
            "declared": self.declared,
            "declared_differences": list(self.declared_differences),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "requires_confirmation": self.requires_confirmation,
            "can_generate": self.can_generate,
        }


@dataclass
class ImportOutcome:
    markdown: str
    replaced_count: int = 0
    skipped_code_count: int = 0
    skipped_missing_count: int = 0
    remaining_placeholders: list = field(default_factory=list)
    post_errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.post_errors

    def to_dict(self):
        return {
            "markdown": self.markdown,
            "replaced_count": self.replaced_count,
            "skipped_code_count": self.skipped_code_count,
            "skipped_missing_count": self.skipped_missing_count,
            "remaining_placeholders": list(self.remaining_placeholders),
            "post_errors": list(self.post_errors),
            "warnings": list(self.warnings),
            "ok": self.ok,
        }


# ---------------------------------------------------------------------------
# Normalization


def normalize_mode(mode):
    key = str(mode or "partial").strip().lower()
    return MODE_ALIASES.get(key, "partial")


def normalize_manifest(manifest):
    """Return ``(document_id, images)`` from new or legacy manifests."""

    if not isinstance(manifest, dict):
        return None, []

    images = []
    entries = manifest.get("images")
    if not isinstance(entries, list):
        entries = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        sequence = _first_int(
            entry.get("sequence"), entry.get("order"), _digits(entry.get("placeholder"))
        )
        if sequence is None:
            sequence = index + 1

        compatibility = _normalize_compatibility(
            entry.get("compatibility"), entry.get("placeholder")
        )
        placeholder = (
            entry.get("placeholder")
            or placeholder_for_compatibility(compatibility, sequence)
        )
        occurrence_id = entry.get("occurrence_id") or occurrence_id_for(sequence)

        source_path = (
            entry.get("source_file")
            or entry.get("source_path")
            or entry.get("local_path")
            or entry.get("local_file")
        )
        upload_path = entry.get("upload_file") or entry.get("upload_path")
        if compatibility in (
            COMPATIBILITY_UNSUPPORTED,
            COMPATIBILITY_CONVERSION_FAILED,
            COMPATIBILITY_EMBEDDED,
        ):
            upload_path = None
        local_file = upload_path or source_path
        file_name = (
            entry.get("upload_file_name")
            or entry.get("file_name")
            or _base_name(local_file)
        )
        source_format = (
            entry.get("source_format") or _format_from_path(source_path)
        )
        upload_format = (
            entry.get("upload_format") or _format_from_path(upload_path)
        )
        source_sha256 = _hash(entry.get("source_sha256") or entry.get("sha256"))
        upload_sha256 = _hash(entry.get("upload_sha256"))
        if upload_sha256 is None and compatibility == COMPATIBILITY_SUPPORTED:
            upload_sha256 = source_sha256
        if compatibility in (
            COMPATIBILITY_UNSUPPORTED,
            COMPATIBILITY_CONVERSION_FAILED,
            COMPATIBILITY_EMBEDDED,
        ):
            upload_sha256 = None

        images.append(
            ManifestImage(
                index=index,
                sequence=sequence,
                occurrence_id=str(occurrence_id),
                placeholder=str(placeholder),
                source_path=source_path,
                source_file_name=_base_name(source_path),
                upload_path=upload_path,
                upload_file_name=_base_name(upload_path),
                local_file=local_file,
                local_path=entry.get("local_path") or local_file,
                file_name=file_name,
                source_sha256=source_sha256,
                upload_sha256=upload_sha256,
                sha256=source_sha256,
                source_format=source_format,
                upload_format=upload_format,
                source_size=_int(entry.get("source_size")) or _int(entry.get("size")),
                size=_int(entry.get("size")),
                mime_type=entry.get("mime_type"),
                compatibility=compatibility,
                requires_conversion=bool(
                    entry.get("requires_conversion")
                    if entry.get("requires_conversion") is not None
                    else compatibility != COMPATIBILITY_SUPPORTED
                ),
                compatibility_reason=str(
                    entry.get("compatibility_reason") or entry.get("error") or ""
                ),
                source_width=_int(entry.get("source_width")),
                source_height=_int(entry.get("source_height")),
                upload_width=_int(entry.get("upload_width")),
                upload_height=_int(entry.get("upload_height")),
                alt_text=str(entry.get("alt_text") or ""),
                section=str(entry.get("section") or ""),
                context_before=str(entry.get("context_before") or ""),
                context_after=str(entry.get("context_after") or ""),
                is_duplicate=bool(entry.get("is_duplicate")),
                duplicate_of=entry.get("duplicate_of"),
                extraction_status=str(entry.get("status") or "extracted"),
                raw=entry,
                upload_status=(
                    compatibility
                    if compatibility in SPECIAL_COMPATIBILITIES
                    else "not_uploaded"
                ),
                reason=(
                    str(entry.get("compatibility_reason") or entry.get("error") or "")
                    if compatibility in SPECIAL_COMPATIBILITIES
                    else ""
                ),
            )
        )

    document_id = manifest.get("document_id")
    document_id = str(document_id) if document_id else None
    return document_id, images


def _normalize_compatibility(value, placeholder):
    text = str(value or "").strip().lower()
    if text in (
        COMPATIBILITY_SUPPORTED,
        COMPATIBILITY_CONVERTED,
        COMPATIBILITY_OVERSIZED,
        COMPATIBILITY_CONVERSION_FAILED,
        COMPATIBILITY_UNSUPPORTED,
        COMPATIBILITY_EMBEDDED,
    ):
        return text

    token = str(placeholder or "")
    if token.startswith(UNSUPPORTED_PREFIX):
        return COMPATIBILITY_UNSUPPORTED
    if token.startswith(OVERSIZED_PREFIX):
        return COMPATIBILITY_OVERSIZED
    if token.startswith(CONVERSION_FAILED_PREFIX):
        return COMPATIBILITY_CONVERSION_FAILED
    if token.startswith(EMBEDDED_PREFIX):
        return COMPATIBILITY_EMBEDDED

    # Legacy manifests (before compatibility categories) keep a normal
    # placeholder even for EMF/WMF/TIFF.  Treat them as supported so old
    # upload_result files can still be imported; new manifests always carry an
    # explicit compatibility value or a special placeholder.
    return COMPATIBILITY_SUPPORTED


def _format_from_path(path):
    if not path:
        return None
    suffix = Path(str(path).replace("\\", "/")).suffix
    return suffix.lstrip(".").lower() or None


def normalize_upload_result(upload_result):
    """Return ``(document_id, uploads, missing_entries)``."""

    if not isinstance(upload_result, dict):
        return None, [], []

    document_id = upload_result.get("manifest_document_id")
    document_id = str(document_id) if document_id else None

    uploads = []
    for index, entry in enumerate(_as_list(upload_result.get("uploads"))):
        uploads.append(_normalize_upload(entry, index))

    missing = [
        entry for entry in _as_list(upload_result.get("missing")) if isinstance(entry, dict)
    ]
    return document_id, uploads, missing


def _images_from_upload_result(upload_result):
    """Degraded mode: infer the expected image list from upload_result alone.

    Without a manifest we cannot know about images that were never uploaded,
    so this is only a fallback for the partial-success workflow.  The analysis
    keeps saying ``manifest_provided = false`` and warns about the limitation.
    """

    merged = {}
    order = []

    for source in _as_list(upload_result.get("uploads")) + _as_list(
        upload_result.get("missing")
    ):
        if not isinstance(source, dict):
            continue
        sequence = _first_int(
            source.get("sequence"), _digits(source.get("placeholder"))
        )
        if sequence is None:
            sequence = len(order) + 1
        placeholder = source.get("placeholder") or placeholder_for(sequence)
        occurrence_id = source.get("occurrence_id") or occurrence_id_for(sequence)
        key = occurrence_id or placeholder
        if key not in merged:
            merged[key] = {
                "sequence": sequence,
                "occurrence_id": occurrence_id,
                "placeholder": placeholder,
                "sha256": _hash(source.get("sha256")),
                "file_name": _clean(source.get("file_name")),
                "alt_text": source.get("alt_text") or "图片{0}".format(sequence),
                "section": source.get("section") or "",
                "context_before": source.get("context_before") or "",
                "context_after": source.get("context_after") or "",
            }
            order.append(key)
            continue

        entry = merged[key]
        for field in ("sha256", "file_name", "section", "context_before", "context_after"):
            if not entry.get(field) and source.get(field):
                entry[field] = (
                    _hash(source[field]) if field == "sha256" else str(source[field])
                )

    images = []
    for index, key in enumerate(order):
        entry = merged[key]
        compatibility = _normalize_compatibility(None, entry["placeholder"])
        images.append(
            ManifestImage(
                index=index,
                sequence=int(entry["sequence"]),
                occurrence_id=str(entry["occurrence_id"]),
                placeholder=str(entry["placeholder"]),
                source_sha256=entry["sha256"],
                upload_sha256=entry["sha256"],
                sha256=entry["sha256"],
                local_file=None,
                local_path=None,
                file_name=entry["file_name"],
                size=None,
                mime_type=None,
                compatibility=compatibility,
                alt_text=str(entry["alt_text"] or ""),
                section=str(entry["section"] or ""),
                context_before=str(entry["context_before"] or ""),
                context_after=str(entry["context_after"] or ""),
                extraction_status="upload_result_only",
                raw={},
                upload_status=(
                    compatibility
                    if compatibility in SPECIAL_COMPATIBILITIES
                    else "not_uploaded"
                ),
            )
        )
    return images


def _normalize_upload(entry, index):
    if not isinstance(entry, dict):
        entry = {}

    upload_id = str(entry.get("upload_id") or "UPLOAD_{0:03d}".format(index + 1))
    url = _clean(entry.get("url"))
    status = str(entry.get("status") or "").strip().lower()
    response_success = entry.get("response_success")
    if response_success is None and "success" in entry:
        response_success = entry.get("success")
    http_status = _int(entry.get("http_status"))
    error = str(entry.get("error") or "")

    if not status:
        status = "success" if url else "failed"

    reason = ""
    if status not in UPLOAD_STATUSES:
        reason = "未知上传状态：{0}".format(status)
        status = "unmatched"
    elif status == "success":
        if response_success is not None and not _is_success_flag(response_success):
            reason = "ShowDoc 返回 success={0}".format(response_success)
            status = "failed"
        elif not url:
            reason = "状态为 success，但 URL 为空"
            status = "failed"
        else:
            url_error = _url_error(url)
            if url_error:
                reason = url_error
                status = "failed"

    if status in ("pending", "interrupted"):
        reason = reason or "上传状态为 {0}，不能当作成功".format(status)
    elif status in (
        COMPATIBILITY_UNSUPPORTED,
        COMPATIBILITY_OVERSIZED,
        COMPATIBILITY_CONVERSION_FAILED,
    ):
        reason = reason or "图片兼容性为 {0}，不能当作成功".format(status)
    elif status == "failed" and not reason:
        reason = error or (
            "HTTP 状态 {0}".format(http_status) if http_status is not None else "上传失败"
        )

    return UploadRecord(
        index=index,
        upload_id=upload_id,
        sequence=_first_int(entry.get("sequence"), _digits(entry.get("placeholder"))),
        occurrence_id=_clean(entry.get("occurrence_id")),
        placeholder=_clean(entry.get("placeholder")),
        file_name=_clean(entry.get("file_name")),
        sha256=_hash(entry.get("sha256")),
        status=status,
        http_status=http_status,
        response_success=response_success,
        url=url if status == "success" else (url or None),
        error=error,
        raw=entry,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Analysis


def analyze_upload_result(
    markdown,
    upload_result,
    manifest=None,
    mode="partial",
    allow_mismatch=False,
):
    """Build an explicit occurrence -> URL mapping and validate it.

    ``mode`` is ``partial`` (default), ``strict`` or ``fill_remaining``.
    ``allow_mismatch`` is the explicit human confirmation required when the
    document id, placeholder or SHA-256 disagree; mismatching images are then
    left as placeholders instead of being replaced silently.
    """

    mode = normalize_mode(mode)
    markdown = markdown or ""
    document_id, images = normalize_manifest(manifest)
    upload_document_id, uploads, missing_entries = normalize_upload_result(upload_result)

    synthesized = False
    if not isinstance(manifest, dict) and isinstance(upload_result, dict):
        images = _images_from_upload_result(upload_result)
        synthesized = True

    analysis = ImportAnalysis(
        mode=mode,
        markdown=markdown,
        manifest=manifest if isinstance(manifest, dict) else None,
        upload_result=upload_result if isinstance(upload_result, dict) else None,
        manifest_provided=isinstance(manifest, dict),
        synthesized_manifest=synthesized,
        upload_result_provided=isinstance(upload_result, dict),
        document_id=document_id,
        upload_document_id=upload_document_id,
        images=images,
        uploads=uploads,
        missing_entries=missing_entries,
    )

    if not analysis.upload_result_provided:
        analysis.errors.append(
            "缺少 upload_result.json。请先导出浏览器扩展的上传结果；"
            "没有上传记录时不能显示“0 张失败”或生成最终 Markdown。"
        )
    if not analysis.manifest_provided:
        analysis.warnings.append(
            "未提供 manifest.json：无法交叉校验 document_id、原图 SHA-256 和未上传图片，"
            "缺失清单可能不完整。建议提供图片提取时生成的 manifest.json。"
        )

    _check_document_id(analysis, allow_mismatch)
    _index_manifest(analysis)
    _match_uploads(analysis)
    _reuse_by_sha(analysis)
    _apply_missing_entries(analysis)
    _scan_markdown(analysis)
    _select_targets(analysis)
    _compute_counts(analysis)
    _check_declared_counts(analysis)
    _decide(analysis, allow_mismatch)

    return analysis


def _check_document_id(analysis, allow_mismatch):
    if not analysis.document_id or not analysis.upload_document_id:
        if analysis.manifest_provided and not analysis.document_id:
            analysis.warnings.append(
                "manifest.json 缺少 document_id，无法确认上传结果属于同一文档。"
            )
        if analysis.upload_result_provided and not analysis.upload_document_id:
            analysis.warnings.append(
                "upload_result.json 缺少 manifest_document_id，无法确认上传结果属于同一文档。"
            )
        return

    if analysis.document_id == analysis.upload_document_id:
        return

    detail = (
        "document_id 不一致：manifest 为 {0}，upload_result 为 {1}。"
        "这可能来自其他文档或刷新后的旧上传记录。".format(
            analysis.document_id, analysis.upload_document_id
        )
    )
    if allow_mismatch:
        analysis.warnings.append(detail + "已按“允许不一致”继续，但请人工核对映射。")
    else:
        analysis.errors.append(
            detail + "已停止自动替换；如确认无误，请显式勾选“允许不一致后继续”。"
        )


def _index_manifest(analysis):
    analysis._by_occurrence = {}
    analysis._by_placeholder = {}
    analysis._by_sha = {}
    analysis._urls_by_sha = {}

    for image in analysis.images:
        if image.occurrence_id in analysis._by_occurrence:
            analysis.warnings.append(
                "manifest 中 occurrence_id {0} 重复，将使用第一条记录。".format(
                    image.occurrence_id
                )
            )
        else:
            analysis._by_occurrence[image.occurrence_id] = image
        if image.placeholder in analysis._by_placeholder:
            analysis.warnings.append(
                "manifest 中占位符 {0} 重复，将使用第一条记录。".format(image.placeholder)
            )
        else:
            analysis._by_placeholder[image.placeholder] = image
        if image.target_hash and not image.is_special:
            analysis._by_sha.setdefault(image.target_hash, []).append(image)


def _match_uploads(analysis):
    for record in analysis.uploads:
        if not analysis.images:
            record.status = "unexpected_upload"
            record.reason = "未提供 manifest，上传记录无法与正文图片匹配"
            analysis.unexpected_uploads.append(record.to_dict())
            continue

        target, match_kind = _resolve(analysis, record)
        if target is None:
            if record.sha256 and record.sha256 in analysis._by_sha:
                # Same bytes as several body positions; URL reuse is resolved
                # later from url_by_sha, not by guessing an occurrence.
                record.match_kind = "sha256"
                _collect_url(analysis, record)
                continue

            record.status = "unexpected_upload"
            record.reason = record.reason or "上传记录中的图片不在当前 manifest 内"
            analysis.unexpected_uploads.append(record.to_dict())
            continue

        record.matched_index = target.index
        record.match_kind = match_kind
        target.upload_ids.append(record.upload_id)

        if target.is_special:
            original_status = record.status
            record.status = "unmatched"
            record.reason = (
                "该图片为 {0}，使用特殊占位符，不参与自动替换".format(
                    target.compatibility
                )
            )
            analysis.ignored_special_uploads.append(
                {
                    **record.to_dict(),
                    "original_status": original_status,
                    "image_compatibility": target.compatibility,
                    "image_placeholder": target.placeholder,
                }
            )
            continue

        conflicts = _consistency_conflicts(record, target)
        if conflicts:
            target.needs_review = True
            if target.upload_status != "success":
                target.upload_status = "unmatched"
                target.reason = "上传记录与 manifest 不一致，需要人工确认：" + "；".join(
                    conflicts
                )
            analysis.warnings.append(
                "{0}（{1}）：{2}".format(
                    target.placeholder, target.occurrence_id, "；".join(conflicts)
                )
            )
            if record.status == "success":
                _collect_url(analysis, record)
            continue

        if record.status == "success":
            if not target.url:
                target.upload_status = "success"
                target.url = record.url
                target.reason = record.reason or "已取得成功 URL"
            elif target.url != record.url:
                analysis.warnings.append(
                    "{0} 有多个成功 URL，已使用第一个；其余 URL 保留在报告中。".format(
                        target.placeholder
                    )
                )
            _collect_url(analysis, record)
        elif record.status == "failed":
            if target.upload_status != "success":
                target.upload_status = "failed"
                target.reason = record.reason or record.error or "上传失败"
        elif record.status == "not_uploaded":
            if target.upload_status == "not_uploaded":
                target.reason = record.reason or "有原图但没有上传请求"
        elif record.status in ("pending", "interrupted"):
            if target.upload_status != "success":
                target.upload_status = record.status
                target.reason = record.reason or "上传状态为 {0}".format(record.status)
        elif record.status == "unmatched":
            if target.upload_status != "success":
                target.upload_status = "unmatched"
                target.reason = record.reason or "上传记录无法与原图哈希匹配"
        elif record.status == "unexpected_upload":
            record.reason = record.reason or "上传记录中的图片不在当前 manifest 内"
            analysis.unexpected_uploads.append(record.to_dict())


def _resolve(analysis, record):
    if record.occurrence_id and record.occurrence_id in analysis._by_occurrence:
        return analysis._by_occurrence[record.occurrence_id], "occurrence_id"
    if record.placeholder and record.placeholder in analysis._by_placeholder:
        return analysis._by_placeholder[record.placeholder], "placeholder"
    if record.sha256:
        candidates = analysis._by_sha.get(record.sha256, [])
        if len(candidates) == 1:
            return candidates[0], "sha256"
    return None, ""


def _consistency_conflicts(record, target):
    conflicts = []
    if (
        record.occurrence_id
        and target.occurrence_id
        and record.occurrence_id != target.occurrence_id
    ):
        conflicts.append(
            "occurrence_id 不一致（上传 {0} / manifest {1}）".format(
                record.occurrence_id, target.occurrence_id
            )
        )
    if record.placeholder and target.placeholder and record.placeholder != target.placeholder:
        conflicts.append(
            "占位符不一致（上传 {0} / manifest {1}）".format(
                record.placeholder, target.placeholder
            )
        )
    target_hash = target.target_hash
    if record.sha256 and target_hash and record.sha256 != target_hash:
        conflicts.append(
            "SHA-256 不一致（上传 {0}… / manifest 上传副本 {1}…）".format(
                record.sha256[:12], target_hash[:12]
            )
        )
    return conflicts


def _collect_url(analysis, record):
    if record.status != "success" or not record.url or not record.sha256:
        return
    analysis._urls_by_sha.setdefault(record.sha256, []).append(record.url)


def _reuse_by_sha(analysis):
    for image in analysis.images:
        if image.is_special:
            continue
        if image.upload_status == "success" and image.url:
            if image.target_hash:
                analysis._urls_by_sha.setdefault(image.target_hash, []).append(image.url)
            continue
        if not image.target_hash or image.needs_review:
            continue
        urls = _unique(analysis._urls_by_sha.get(image.target_hash, []))
        if not urls:
            continue
        if len(urls) > 1:
            analysis.warnings.append(
                "{0} 的 SHA-256 对应多个成功 URL，已使用第一个：{1}".format(
                    image.placeholder, urls[0]
                )
            )
        image.upload_status = "success"
        image.url = urls[0]
        image.reused_by_sha = True
        image.reason = "按 SHA-256 复用同一原图的成功 URL"

    # Normalize lists for deterministic reports.
    for sha, urls in list(analysis._urls_by_sha.items()):
        analysis._urls_by_sha[sha] = _unique(urls)


def _apply_missing_entries(analysis):
    for entry in analysis.missing_entries:
        record = _normalize_upload(entry, -1)
        if not analysis.images:
            analysis.warnings.append(
                "missing 记录 {0} 无法匹配：未提供 manifest".format(
                    record.placeholder or record.occurrence_id or record.file_name
                )
            )
            continue

        target, _ = _resolve(analysis, record)
        if target is None:
            analysis.warnings.append(
                "missing 记录无法匹配 manifest：{0} / {1} / {2}".format(
                    record.occurrence_id or "-",
                    record.placeholder or "-",
                    record.sha256 or "-",
                )
            )
            continue

        if target.is_special:
            continue

        if target.upload_status == "success":
            analysis.warnings.append(
                "{0} 同时出现在成功上传和缺失记录中，以成功记录为准。".format(
                    target.placeholder
                )
            )
            continue

        status = record.status if record.status in IMAGE_STATUSES else "failed"
        if status == "success":
            status = "failed"
        target.upload_status = status
        target.reason = (
            str(entry.get("reason") or "")
            or record.reason
            or "upload_result.json 标记为 {0}".format(status)
        )
        if record.sha256 and target.target_hash and record.sha256 != target.target_hash:
            target.needs_review = True
            target.reason = "SHA-256 与 manifest 上传副本不一致，需要人工确认"


NORMAL_PLACEHOLDER = re.compile(r"\{\{SHOWDOC_IMAGE_\d{6}\}\}")


def _scan_tokens(markdown):
    """Return normal and special placeholder occurrences with line numbers."""

    occurrences = []
    for line_number, (content, _ending, is_code) in enumerate(
        _scan_lines(markdown or ""), start=1
    ):
        masked = content if is_code else _mask_inline_code(content)
        for kind, pattern in (
            ("normal", NORMAL_PLACEHOLDER),
            ("special", SPECIAL_PLACEHOLDER),
        ):
            for match in pattern.finditer(content):
                token = content[match.start():match.end()]
                inside_inline = (
                    not is_code and not masked[match.start():match.end()].strip()
                )
                occurrences.append(
                    {
                        "placeholder": token,
                        "kind": kind,
                        "line": line_number,
                        "column": match.start() + 1,
                        "in_code": is_code or inside_inline,
                    }
                )
    return occurrences


def _scan_markdown(analysis):
    occurrences = _scan_tokens(analysis.markdown)
    outside = [item for item in occurrences if not item["in_code"]]
    normal_by_token = {}
    special_by_token = {}
    for item in outside:
        if item["kind"] == "special":
            special_by_token.setdefault(item["placeholder"], item)
        else:
            normal_by_token.setdefault(item["placeholder"], item)

    analysis.markdown_placeholders = occurrences
    analysis.special_placeholders = sorted(
        special_by_token.values(), key=lambda item: (item["placeholder"], item["line"])
    )

    manifest_normal = set(
        image.placeholder for image in analysis.images if not image.is_special
    )
    manifest_special = set(
        image.placeholder for image in analysis.images if image.is_special
    )
    analysis.unknown_placeholders = sorted(
        token for token in normal_by_token if token not in manifest_normal
    )
    analysis.unknown_special_placeholders = sorted(
        token for token in special_by_token if token not in manifest_special
    )

    for image in analysis.images:
        occurrence = (
            special_by_token.get(image.placeholder)
            if image.is_special
            else normal_by_token.get(image.placeholder)
        )
        image.in_markdown = occurrence is not None
        image.line = occurrence["line"] if occurrence else None
        image.in_code = any(
            item["placeholder"] == image.placeholder and item["in_code"]
            for item in occurrences
        )


def _select_targets(analysis):
    normal = [image for image in analysis.images if not image.is_special]
    if analysis.mode == "fill_remaining":
        analysis.targets = [image for image in normal if image.in_markdown]
    else:
        analysis.targets = normal
    for image in analysis.targets:
        image.in_target = True


def _compute_counts(analysis):
    targets = analysis.targets
    statuses = {status: 0 for status in IMAGE_STATUSES}
    for image in targets:
        statuses[image.upload_status] = statuses.get(image.upload_status, 0) + 1
    statuses["unexpected_upload"] = len(analysis.unexpected_uploads)

    success_urls = _unique(
        image.url for image in targets if image.upload_status == "success" and image.url
    )
    markdown_outside = [
        item for item in analysis.markdown_placeholders if not item["in_code"]
    ]
    normal_tokens = _unique(
        item["placeholder"] for item in markdown_outside if item["kind"] == "normal"
    )
    special_tokens = _unique(
        item["placeholder"] for item in markdown_outside if item["kind"] == "special"
    )
    code_tokens = _unique(
        item["placeholder"] for item in analysis.markdown_placeholders if item["in_code"]
    )

    normal_images = [image for image in analysis.images if not image.is_special]
    special_images = [image for image in analysis.images if image.is_special]
    compatibility_counts = {
        compatibility: sum(
            1 for image in analysis.images if image.compatibility == compatibility
        )
        for compatibility in (
            COMPATIBILITY_SUPPORTED,
            COMPATIBILITY_CONVERTED,
            COMPATIBILITY_OVERSIZED,
            COMPATIBILITY_CONVERSION_FAILED,
            COMPATIBILITY_UNSUPPORTED,
            COMPATIBILITY_EMBEDDED,
        )
    }

    analysis.counts = {
        "manifest_images": 0 if analysis.synthesized_manifest else len(analysis.images),
        "normal_images": len(normal_images),
        "special_images": len(special_images),
        "target_images": len(targets),
        "success": statuses.get("success", 0),
        "success_in_markdown": sum(
            1
            for image in targets
            if image.upload_status == "success" and image.in_markdown
        ),
        "failed": statuses.get("failed", 0),
        "not_uploaded": statuses.get("not_uploaded", 0),
        "unmatched": statuses.get("unmatched", 0),
        "pending": statuses.get("pending", 0),
        "interrupted": statuses.get("interrupted", 0),
        "unsupported": compatibility_counts[COMPATIBILITY_UNSUPPORTED],
        "oversized": compatibility_counts[COMPATIBILITY_OVERSIZED],
        "conversion_failed": compatibility_counts[COMPATIBILITY_CONVERSION_FAILED],
        "embedded": compatibility_counts[COMPATIBILITY_EMBEDDED],
        "converted": compatibility_counts[COMPATIBILITY_CONVERTED],
        "supported": compatibility_counts[COMPATIBILITY_SUPPORTED],
        "unexpected_upload": len(analysis.unexpected_uploads),
        "ignored_special_uploads": len(analysis.ignored_special_uploads),
        "needs_review": sum(1 for image in targets if image.needs_review),
        "reused_by_sha": sum(1 for image in targets if image.reused_by_sha),
        "success_unique_urls": len(success_urls),
        "markdown_placeholders": len(normal_tokens),
        "markdown_normal_placeholders": len(normal_tokens),
        "markdown_special_placeholders": len(special_tokens),
        "special_placeholders": len(analysis.special_placeholders),
        "markdown_occurrences": len(markdown_outside),
        "code_block_placeholders": len(code_tokens),
        "placeholders_not_in_manifest": len(analysis.unknown_placeholders),
        "special_placeholders_not_in_manifest": len(
            analysis.unknown_special_placeholders
        ),
        "manifest_not_in_markdown": (
            0
            if analysis.mode == "fill_remaining"
            else sum(1 for image in normal_images if not image.in_markdown)
        ),
        "special_not_in_markdown": sum(
            1
            for image in special_images
            if image.compatibility != COMPATIBILITY_EMBEDDED and not image.in_markdown
        ),
        "upload_records": len(analysis.uploads),
        "missing_entries": len(analysis.missing_entries),
        "fill_remaining_out_of_scope": (
            max(0, len(normal_images) - len(targets))
            if analysis.mode == "fill_remaining"
            else 0
        ),
    }


def _check_declared_counts(analysis):
    source = analysis.upload_result if isinstance(analysis.upload_result, dict) else {}
    declared = {
        "expected_count": _int(source.get("expected_count")),
        "detected_request_count": _int(source.get("detected_request_count")),
        "success_unique_count": _int(source.get("success_unique_count")),
        "failed_count": _int(source.get("failed_count")),
        "not_uploaded_count": _int(source.get("not_uploaded_count")),
        "unmatched_count": _int(source.get("unmatched_count")),
        "unexpected_upload_count": _int(source.get("unexpected_upload_count")),
    }
    analysis.declared = {key: value for key, value in declared.items() if value is not None}

    ignored_ids = {
        record.get("upload_id") for record in analysis.ignored_special_uploads
    }
    actual = {
        "detected_request_count": len(analysis.uploads),
        "success_unique_count": len(
            _unique(record.url for record in analysis.uploads if record.status == "success" and record.url)
        ),
        "failed_count": sum(
            1
            for record in analysis.uploads
            if record.status == "failed" and record.upload_id not in ignored_ids
        ),
        "unmatched_count": sum(
            1
            for record in analysis.uploads
            if record.status == "unmatched" and record.upload_id not in ignored_ids
        ),
        "unexpected_upload_count": len(analysis.unexpected_uploads),
    }

    for key, actual_value in actual.items():
        declared_value = declared.get(key)
        if declared_value is None:
            continue
        if declared_value != actual_value:
            analysis.declared_differences.append(
                "{0}: 文件声明 {1}，实际记录 {2}".format(key, declared_value, actual_value)
            )

    expected = declared.get("expected_count")
    if expected is not None and analysis.mode == "fill_remaining":
        if expected != len(analysis.targets):
            analysis.declared_differences.append(
                "expected_count: 文件声明 {0}，当前 Markdown 有 {1} 个遗留普通占位符".format(
                    expected, len(analysis.targets)
                )
            )
    elif expected is not None:
        normal_count = analysis.counts.get("normal_images", 0)
        if analysis.manifest_provided and expected != normal_count:
            analysis.declared_differences.append(
                "expected_count: 文件声明 {0}，manifest 有 {1} 张可上传图片（另有 {2} 张特殊图片）".format(
                    expected,
                    normal_count,
                    analysis.counts.get("special_images", 0),
                )
            )
        markdown_count = analysis.counts.get("markdown_normal_placeholders", 0)
        if markdown_count and expected != markdown_count:
            analysis.declared_differences.append(
                "expected_count: 文件声明 {0}，Markdown 正文有 {1} 个普通占位符".format(
                    expected, markdown_count
                )
            )

    special_images = analysis.counts.get("special_images", 0)
    special_markdown = analysis.counts.get("markdown_special_placeholders", 0)
    if analysis.manifest_provided and special_images != special_markdown:
        analysis.declared_differences.append(
            "特殊占位符数量不一致：manifest 有 {0} 张特殊图片，Markdown 有 {1} 个特殊占位符".format(
                special_images, special_markdown
            )
        )
    if analysis.unknown_special_placeholders:
        analysis.declared_differences.append(
            "Markdown 中有 {0} 个特殊占位符不在 manifest 内：{1}".format(
                len(analysis.unknown_special_placeholders),
                "、".join(analysis.unknown_special_placeholders[:5]),
            )
        )

    upload_keys = set()
    for record in analysis.uploads:
        upload_keys.add(record.occurrence_id or record.placeholder or record.sha256)
    missing_only = 0
    for entry in analysis.missing_entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("occurrence_id") or entry.get("placeholder") or entry.get("sha256")
        if key and key in upload_keys:
            continue
        missing_only += 1
    covered = len(analysis.uploads) + missing_only
    if expected is not None and covered < expected:
        analysis.declared_differences.append(
            "上传记录数量不足：expected_count={0}，uploads + missing 只覆盖 {1} 条。"
            "未覆盖的图片会标记为 not_uploaded。".format(expected, covered)
        )

    if not analysis.declared_differences:
        return

    detail = "upload_result.json 统计与实际记录存在差异：" + "；".join(
        analysis.declared_differences
    )
    if analysis.mode == "strict":
        analysis.errors.append(detail)
    else:
        analysis.warnings.append(detail + "（部分成功模式会按实际记录生成，并在报告中列出差异）")


def _decide(analysis, allow_mismatch):
    targets = analysis.targets
    review = [image for image in targets if image.needs_review]
    if review and not allow_mismatch:
        analysis.errors.append(
            "有 {0} 张图片的 occurrence_id / 占位符 / SHA-256 与上传记录不一致：{1}。"
            "已停止自动替换；请人工核对，或显式选择“允许不一致后继续”（这些图片仍会保留占位符）。".format(
                len(review),
                "、".join(image.placeholder for image in review[:5]),
            )
        )

    if not analysis.upload_result_provided:
        analysis.can_generate = False
        analysis.requires_confirmation = False
        return

    if analysis.mode == "strict" and not analysis.manifest_provided:
        analysis.errors.append("严格模式必须提供 manifest.json 用于数量与哈希校验。")

    if analysis.mode != "fill_remaining":
        missing_in_markdown = [
            image
            for image in analysis.images
            if not image.is_special and not image.in_markdown
        ]
        if missing_in_markdown:
            analysis.warnings.append(
                "Markdown 中缺少 {0} 个 manifest 普通占位符（不会自动补回）：{1}{2}".format(
                    len(missing_in_markdown),
                    "、".join(
                        image.placeholder for image in missing_in_markdown[:5]
                    ),
                    " 等" if len(missing_in_markdown) > 5 else "",
                )
            )

    missing_special = [
        image
        for image in analysis.images
        if image.is_special
        and image.compatibility != COMPATIBILITY_EMBEDDED
        and not image.in_markdown
    ]
    if missing_special:
        analysis.warnings.append(
            "Markdown 中缺少 {0} 个特殊占位符（不会自动补回）：{1}{2}".format(
                len(missing_special),
                "、".join(image.placeholder for image in missing_special[:5]),
                " 等" if len(missing_special) > 5 else "",
            )
        )

    embedded_images = [
        image
        for image in analysis.images
        if image.compatibility == COMPATIBILITY_EMBEDDED
    ]
    if embedded_images:
        analysis.warnings.append(
            "manifest 中有 {0} 个嵌入对象（Word / 视频 / HTML / OLE 等），"
            "本工具不转换、不替换，请在 ShowDoc 手动上传原文件：{1}{2}".format(
                len(embedded_images),
                "、".join(image.placeholder for image in embedded_images[:5]),
                " 等" if len(embedded_images) > 5 else "",
            )
        )

    if analysis.unknown_placeholders:
        analysis.warnings.append(
            "Markdown 中有 {0} 个普通占位符不在 manifest 内，已原样保留：{1}{2}".format(
                len(analysis.unknown_placeholders),
                "、".join(analysis.unknown_placeholders[:5]),
                " 等" if len(analysis.unknown_placeholders) > 5 else "",
            )
        )

    if analysis.unknown_special_placeholders:
        analysis.warnings.append(
            "Markdown 中有 {0} 个特殊占位符不在 manifest 内，已原样保留：{1}{2}".format(
                len(analysis.unknown_special_placeholders),
                "、".join(analysis.unknown_special_placeholders[:5]),
                " 等" if len(analysis.unknown_special_placeholders) > 5 else "",
            )
        )

    if analysis.unexpected_uploads:
        analysis.warnings.append(
            "upload_result.json 中有 {0} 条清单外的上传记录，已写入报告：{1}{2}".format(
                len(analysis.unexpected_uploads),
                "、".join(
                    str(record.get("upload_id") or record.get("file_name") or "?")
                    for record in analysis.unexpected_uploads[:5]
                ),
                " 等" if len(analysis.unexpected_uploads) > 5 else "",
            )
        )

    if analysis.ignored_special_uploads:
        analysis.warnings.append(
            "有 {0} 条上传记录对应特殊占位符图片；特殊占位符按规则保持不动，不自动替换。".format(
                len(analysis.ignored_special_uploads)
            )
        )

    if analysis.mode == "fill_remaining":
        if not analysis.counts.get("markdown_placeholders"):
            analysis.errors.append("当前 Markdown 中没有遗留普通占位符，无需补齐。")
    elif analysis.manifest_provided and not analysis.images:
        analysis.errors.append("manifest.json 中没有 images 记录。")

    if (
        analysis.mode != "fill_remaining"
        and analysis.counts.get("normal_images")
        and analysis.counts.get("markdown_normal_placeholders") == 0
    ):
        analysis.errors.append(
            "Markdown 正文中没有 {{SHOWDOC_IMAGE_...}} 普通占位符，无法生成替换结果。"
        )

    if not targets and analysis.mode != "fill_remaining" and not analysis.counts.get("special_images"):
        analysis.errors.append("没有可处理的图片记录。")

    success_count = sum(1 for image in targets if image.upload_status == "success" and image.url)
    if targets and success_count == 0:
        analysis.errors.append(
            "没有取得任何成功 URL：不能生成最终 Markdown，请检查上传结果或选择其他模式。"
        )

    if analysis.mode == "strict":
        incomplete = [image for image in targets if image.upload_status != "success"]
        if incomplete:
            analysis.errors.append(
                "严格模式要求全部图片都有成功 URL；当前有 {0} 张未成功（失败 {1}、未上传 {2}、无法匹配 {3}）。".format(
                    len(incomplete),
                    sum(1 for image in incomplete if image.upload_status == "failed"),
                    sum(1 for image in incomplete if image.upload_status == "not_uploaded"),
                    sum(1 for image in incomplete if image.upload_status == "unmatched"),
                )
            )
        if analysis.unknown_placeholders:
            analysis.errors.append(
                "Markdown 中有 {0} 个普通占位符不在 manifest 内：{1}".format(
                    len(analysis.unknown_placeholders),
                    "、".join(analysis.unknown_placeholders[:5]),
                )
            )
        if analysis.unknown_special_placeholders:
            analysis.errors.append(
                "Markdown 中有 {0} 个特殊占位符不在 manifest 内：{1}".format(
                    len(analysis.unknown_special_placeholders),
                    "、".join(analysis.unknown_special_placeholders[:5]),
                )
            )
        missing_in_markdown = [
            image
            for image in analysis.images
            if not image.is_special and not image.in_markdown
        ]
        if missing_in_markdown:
            analysis.errors.append(
                "严格模式要求 manifest 中每个普通占位符都出现在 Markdown 正文；当前缺少 {0} 个：{1}".format(
                    len(missing_in_markdown),
                    "、".join(image.placeholder for image in missing_in_markdown[:5]),
                )
            )
        if analysis.counts.get("special_images"):
            analysis.errors.append(
                "严格模式不允许存在特殊占位符图片；当前有 {0} 张（unsupported {1}、oversized {2}、conversion_failed {3}）。".format(
                    analysis.counts.get("special_images"),
                    analysis.counts.get("unsupported", 0),
                    analysis.counts.get("oversized", 0),
                    analysis.counts.get("conversion_failed", 0),
                )
            )
        if analysis.unexpected_uploads:
            analysis.errors.append(
                "upload_result.json 中有 {0} 条清单外的上传记录，严格模式不允许继续。".format(
                    len(analysis.unexpected_uploads)
                )
            )

    incomplete = [
        image
        for image in targets
        if image.upload_status != "success" and image.in_markdown
    ]
    analysis.requires_confirmation = bool(
        analysis.mode != "strict"
        and (
            incomplete
            or analysis.unknown_placeholders
            or analysis.unknown_special_placeholders
            or analysis.unexpected_uploads
            or analysis.counts.get("manifest_not_in_markdown")
            or analysis.counts.get("special_not_in_markdown")
            or analysis.declared_differences
        )
    )

    analysis.errors = _unique(analysis.errors)
    analysis.warnings = _unique(analysis.warnings)
    analysis.can_generate = not analysis.errors


# ---------------------------------------------------------------------------
# Replacement and post validation


def apply_analysis(markdown, analysis):
    """Replace successful placeholders using the explicit per-occurrence map."""

    mapping = {
        image.placeholder: image.url
        for image in analysis.targets
        if image.upload_status == "success" and image.url and image.in_markdown
    }
    alt = {image.placeholder: image.alt_text for image in analysis.targets if image.alt_text}

    result = replace_placeholders(
        markdown,
        mapping,
        alt,
        partial=True,
    )

    for image in analysis.targets:
        image.replaced = image.placeholder in mapping and image.in_markdown

    outcome = ImportOutcome(
        markdown=result.markdown,
        replaced_count=result.replaced_count,
        skipped_code_count=result.skipped_code_count,
        skipped_missing_count=result.skipped_missing_count,
        warnings=list(result.warnings),
    )

    if result.errors:
        outcome.post_errors.extend(result.errors)
        return outcome

    _validate_after_replacement(outcome, analysis, mapping)
    return outcome


def _validate_after_replacement(outcome, analysis, mapping):
    remaining = _scan_tokens(outcome.markdown)
    outside = [item for item in remaining if not item["in_code"]]
    outside_normal = set(
        item["placeholder"] for item in outside if item["kind"] == "normal"
    )
    outside_special = set(
        item["placeholder"] for item in outside if item["kind"] == "special"
    )

    expected_normal = set()
    for image in analysis.targets:
        if image.in_markdown and image.upload_status != "success":
            expected_normal.add(image.placeholder)
    expected_normal.update(analysis.unknown_placeholders)

    input_special = set(
        item["placeholder"] for item in analysis.special_placeholders
    )

    leftover_success = sorted(token for token in mapping if token in outside_normal)
    if leftover_success:
        outcome.post_errors.append(
            "替换后仍存在成功图片的普通占位符：{0}".format(
                "、".join(leftover_success[:10])
            )
        )

    unexpected = sorted(outside_normal - expected_normal - set(mapping))
    if unexpected:
        outcome.post_errors.append(
            "替换后出现未预期的普通占位符：{0}".format("、".join(unexpected[:10]))
        )

    missing = sorted(expected_normal - outside_normal)
    if missing:
        outcome.post_errors.append(
            "替换后缺少本应保留的普通占位符：{0}".format("、".join(missing[:10]))
        )

    missing_special = sorted(input_special - outside_special)
    if missing_special:
        outcome.post_errors.append(
            "特殊占位符不应被替换，但以下占位符消失了：{0}".format(
                "、".join(missing_special[:10])
            )
        )
    unexpected_special = sorted(outside_special - input_special)
    if unexpected_special:
        outcome.post_errors.append(
            "替换后出现未预期的特殊占位符：{0}".format(
                "、".join(unexpected_special[:10])
            )
        )

    if DATA_IMAGE.search(outcome.markdown):
        outcome.post_errors.append("最终 Markdown 仍包含 data:image Base64")

    outcome.remaining_placeholders = [
        {
            "placeholder": item["placeholder"],
            "kind": item["kind"],
            "line": item["line"],
            "column": item["column"],
            "in_code": item["in_code"],
        }
        for item in remaining
    ]

    by_sha = {}
    for image in analysis.targets:
        if (
            image.upload_status == "success"
            and image.target_hash
            and image.in_markdown
            and image.url
        ):
            by_sha.setdefault(image.target_hash, []).append(image)
    for sha, group in by_sha.items():
        if len(group) <= 1:
            continue
        urls = set(image.url for image in group)
        if len(urls) > 1:
            outcome.warnings.append(
                "同一上传副本 SHA-256 的 {0} 个正文位置使用了 {1} 个不同 URL；"
                "这仍按显式映射处理，请确认是否为预期。".format(len(group), len(urls))
            )


# ---------------------------------------------------------------------------
# Reports / exports


def build_missing_rows(analysis):
    rows = []
    for image in analysis.images:
        if image.is_special:
            rows.append(_image_row(image))
            continue
        if not image.in_target:
            continue
        if image.upload_status == "success":
            continue
        rows.append(_image_row(image))

    for record in analysis.unexpected_uploads:
        rows.append(
            {
                "序号": "",
                "occurrence_id": record.get("occurrence_id") or "",
                "占位符": record.get("placeholder") or "",
                "原始文件名": record.get("file_name") or "",
                "原始路径": "",
                "上传文件名": "",
                "上传路径": "",
                "大小": "",
                "SHA-256": record.get("sha256") or "",
                "原始SHA-256": record.get("sha256") or "",
                "上传SHA-256": record.get("sha256") or "",
                "章节": "",
                "上下文前置文字": "",
                "上下文后置文字": "",
                "状态": "unexpected_upload",
                "失败原因": record.get("reason")
                or record.get("error")
                or "清单外的上传记录",
                "是否在Markdown中": "",
                "行号": "",
            }
        )
    return rows


def _image_row(image):
    root_hash = image.upload_sha256 or image.source_sha256 or image.sha256 or ""
    return {
        "序号": image.sequence,
        "occurrence_id": image.occurrence_id,
        "占位符": image.placeholder,
        "原始文件名": image.source_file_name or "",
        "原始路径": image.source_path or "",
        "上传文件名": image.upload_file_name or "",
        "上传路径": image.upload_path or "",
        "大小": image.size if image.size is not None else "",
        "SHA-256": root_hash,
        "原始SHA-256": image.source_sha256 or image.sha256 or "",
        "上传SHA-256": image.upload_sha256 or "",
        "章节": image.section,
        "上下文前置文字": image.context_before,
        "上下文后置文字": image.context_after,
        "状态": image.upload_status,
        "失败原因": image.reason or image.compatibility_reason,
        "是否在Markdown中": "是" if image.in_markdown else "否",
        "行号": image.line if image.line is not None else "",
    }


MISSING_COLUMNS = [
    "序号",
    "occurrence_id",
    "占位符",
    "原始文件名",
    "原始路径",
    "上传文件名",
    "上传路径",
    "大小",
    "SHA-256",
    "原始SHA-256",
    "上传SHA-256",
    "章节",
    "上下文前置文字",
    "上下文后置文字",
    "状态",
    "失败原因",
    "是否在Markdown中",
    "行号",
]


def missing_images_csv(rows):
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.DictWriter(buffer, fieldnames=MISSING_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def replacement_report(analysis, outcome=None, inputs=None):
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": analysis.mode,
        "inputs": inputs or {},
        "manifest": {
            "provided": analysis.manifest_provided,
            "synthesized_from_upload_result": analysis.synthesized_manifest,
        },
        "document_consistency": {
            "manifest_document_id": analysis.document_id,
            "upload_result_document_id": analysis.upload_document_id,
            "match": (
                None
                if not analysis.document_id or not analysis.upload_document_id
                else analysis.document_id == analysis.upload_document_id
            ),
        },
        "counts": analysis.counts,
        "declared": analysis.declared,
        "declared_differences": analysis.declared_differences,
        "errors": analysis.errors,
        "warnings": analysis.warnings,
        "unknown_placeholders": analysis.unknown_placeholders,
        "unknown_special_placeholders": analysis.unknown_special_placeholders,
        "special_placeholders": analysis.special_placeholders,
        "unexpected_uploads": analysis.unexpected_uploads,
        "ignored_special_uploads": analysis.ignored_special_uploads,
        "compatibility_summary": {
            "supported": analysis.counts.get("supported", 0),
            "converted": analysis.counts.get("converted", 0),
            "oversized": analysis.counts.get("oversized", 0),
            "conversion_failed": analysis.counts.get("conversion_failed", 0),
            "unsupported": analysis.counts.get("unsupported", 0),
            "special": analysis.counts.get("special_images", 0),
        },
        "mapping": [image.to_dict() for image in analysis.images],
        "missing": build_missing_rows(analysis),
    }
    if outcome is not None:
        report["replacement"] = {
            "ok": outcome.ok,
            "replaced_count": outcome.replaced_count,
            "skipped_code_count": outcome.skipped_code_count,
            "skipped_missing_count": outcome.skipped_missing_count,
            "post_errors": outcome.post_errors,
            "warnings": outcome.warnings,
            "remaining_placeholders": outcome.remaining_placeholders,
        }
    return report


WEB_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".jfif": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def thumbnails_from_files(analysis, roots):
    """Build data-URL thumbnails from local image files for the HTML report.

    ``roots`` may contain the assets directory, the output directory, or any
    directory that contains the paths recorded in ``local_file``.  Non-web
    formats (EMF/WMF/TIFF) are skipped unless Pillow can render them.
    """

    roots = [Path(root) for root in roots if root]
    thumbnails = {}
    if not roots:
        return thumbnails

    for image in analysis.images:
        if not image.is_special and (
            not image.in_target or image.upload_status == "success"
        ):
            continue
        relative = image.local_file or image.local_path or image.source_path
        path = _resolve_asset(relative, roots)
        if path is None:
            continue
        data_url = _thumbnail_data_url(path)
        if not data_url:
            continue
        if image.placeholder:
            thumbnails[image.placeholder] = data_url
        if image.file_name:
            thumbnails[image.file_name] = data_url
    return thumbnails


def _resolve_asset(relative, roots):
    if not relative:
        return None
    rel = Path(str(relative).replace("\\", "/"))
    for root in roots:
        candidates = [root / rel, root / rel.name]
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
    return None


def _thumbnail_data_url(path):
    suffix = path.suffix.lower()
    data = None
    mime = "image/png"
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((320, 320))
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            data = buffer.getvalue()
    except Exception:
        data = None

    if data is None:
        if suffix not in WEB_IMAGE_TYPES:
            return ""
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        mime = WEB_IMAGE_TYPES[suffix]

    return "data:{0};base64,{1}".format(
        mime, base64.b64encode(data).decode("ascii")
    )


def missing_images_html(analysis, thumbnails=None, title="缺失图片清单"):
    """Small standalone HTML report; thumbnails are optional data URLs."""

    thumbnails = thumbnails or {}
    rows = []
    for image in analysis.images:
        if not image.is_special and (
            not image.in_target or image.upload_status == "success"
        ):
            continue
        thumb = _safe_thumbnail(
            thumbnails.get(image.placeholder)
            or thumbnails.get(image.file_name or "")
            or thumbnails.get(image.local_path or "")
        )
        rows.append((image, thumb))

    for record in analysis.unexpected_uploads:
        rows.append(
            (
                record,
                _safe_thumbnail(thumbnails.get(record.get("placeholder") or "")),
            )
        )

    parts = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>{0}</title>".format(html.escape(title)),
        "<style>",
        "body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;margin:24px;color:#1f2d28;background:#f6faf8}",
        "h1{font-size:20px}p.meta{color:#5b6b64}",
        "table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}",
        "th,td{border:1px solid #d9e4df;padding:8px;vertical-align:top;text-align:left}",
        "th{background:#eef6f2;position:sticky;top:0}",
        "img{max-width:180px;max-height:140px;border:1px solid #d9e4df;border-radius:4px;background:#fff}",
        ".status{font-weight:600;color:#b23a35}",
        ".placeholder{font-family:ui-monospace,Consolas,monospace;color:#1d6b4f}",
        "</style></head><body>",
        "<h1>{0}</h1>".format(html.escape(title)),
        '<p class="meta">模式：{0} · 缺失 {1} 张 · 生成时间：{2}</p>'.format(
            html.escape(analysis.mode),
            len(rows),
            html.escape(datetime.now().astimezone().isoformat(timespec="seconds")),
        ),
        "<table><thead><tr>",
        "<th>#</th><th>缩略图</th><th>占位符</th><th>文件</th><th>状态</th>",
        "<th>章节</th><th>上下文</th><th>原因</th>",
        "</tr></thead><tbody>",
    ]

    for index, (image, thumb) in enumerate(rows, start=1):
        if isinstance(image, dict):
            sequence = image.get("sequence") or ""
            placeholder = image.get("placeholder") or ""
            file_name = image.get("file_name") or ""
            status = image.get("status") or "unexpected_upload"
            section = ""
            context = ""
            reason = image.get("reason") or image.get("error") or ""
        else:
            sequence = image.sequence
            placeholder = image.placeholder
            file_name = (
                image.upload_file_name
                or image.source_file_name
                or image.file_name
                or image.local_file
                or ""
            )
            status = image.upload_status
            section = image.section
            context = image.context_before or ""
            reason = image.reason or image.compatibility_reason
        image_html = (
            '<img src="{0}" alt="{1}">'.format(html.escape(thumb), html.escape(file_name))
            if thumb
            else "<span>无缩略图</span>"
        )
        parts.append(
            "<tr><td>{0}</td><td>{1}</td><td class=\"placeholder\">{2}</td>"
            "<td>{3}</td><td class=\"status\">{4}</td><td>{5}</td>"
            "<td>{6}</td><td>{7}</td></tr>".format(
                html.escape(str(sequence)),
                image_html,
                html.escape(str(placeholder)),
                html.escape(str(file_name)),
                html.escape(str(status)),
                html.escape(str(section)),
                html.escape(str(context)),
                html.escape(str(reason)),
            )
        )

    parts.extend(["</tbody></table>", "</body></html>"])
    return "\n".join(parts)


def timestamp_suffix(moment=None):
    moment = moment or datetime.now()
    return moment.strftime("%Y%m%d_%H%M%S")


def output_names(moment=None):
    suffix = timestamp_suffix(moment)
    return {
        "markdown": "final_markdown_{0}.md".format(suffix),
        "csv": "missing_images.csv",
        "report": "replacement_report.json",
        "html": "missing_images.html",
        "suffix": suffix,
    }


def write_outputs(
    output_dir,
    markdown,
    analysis,
    outcome,
    *,
    inputs=None,
    thumbnails=None,
    include_html=True,
    moment=None,
):
    """Write the final Markdown and the three report files."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    names = output_names(moment)

    markdown_name = names["markdown"]
    markdown_path = output_dir / markdown_name
    counter = 1
    while markdown_path.exists():
        counter += 1
        markdown_name = "final_markdown_{0}_{1}.md".format(names["suffix"], counter)
        markdown_path = output_dir / markdown_name
    names["markdown"] = markdown_name

    # newline="" is required: it stops Windows text mode from rewriting the
    # line endings a second time (which would turn CRLF into CRCRLF).
    markdown_path.write_text(markdown, encoding="utf-8", newline="")

    csv_path = output_dir / names["csv"]
    csv_path.write_text(
        missing_images_csv(build_missing_rows(analysis)),
        encoding="utf-8",
        newline="",
    )

    report_path = output_dir / names["report"]
    report_path.write_text(
        json.dumps(
            replacement_report(analysis, outcome, inputs=inputs),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="",
    )

    html_path = None
    if include_html:
        html_path = output_dir / names["html"]
        html_path.write_text(
            missing_images_html(analysis, thumbnails=thumbnails),
            encoding="utf-8",
            newline="",
        )

    return {
        "markdown": markdown_path,
        "csv": csv_path,
        "report": report_path,
        "html": html_path,
        "names": names,
    }


# ---------------------------------------------------------------------------
# Small helpers


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _as_list(value):
    return value if isinstance(value, list) else []


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _hash(value):
    text = _clean(value)
    return text.lower() if text else None


def _int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(*values):
    for value in values:
        converted = _int(value)
        if converted is not None:
            return converted
    return None


def _digits(value):
    if not value:
        return None
    matches = _DIGITS.findall(str(value))
    return matches[-1] if matches else None


def _base_name(value):
    if not value:
        return None
    return Path(str(value).replace("\\", "/")).name or None


def _is_success_flag(value):
    return str(value).strip().lower() in ("1", "true", "yes", "ok")


def _url_error(url):
    if not url:
        return "URL 为空"
    if _DATA_URL.match(url):
        return "不允许使用 data:image Base64 URL"
    if not _HTTP_URL.match(url):
        return "URL 必须以 http:// 或 https:// 开头"
    if re.search(r"\s", url):
        return "URL 不能包含空白字符"
    return None


def _safe_thumbnail(value):
    if isinstance(value, str) and value.startswith("data:image/"):
        return value
    return ""


def _unique(items):
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
