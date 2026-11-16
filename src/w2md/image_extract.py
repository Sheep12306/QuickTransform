"""Extract images from a .docx in document order and generate placeholders.

This module is deliberately independent from the Markdown IR.  It reads the
OPC package directly:

* ``word/document.xml`` for image references and their document order
* ``word/_rels/document.xml.rels`` for relationship id -> media part mapping
* ``word/media/*`` for the original bytes

The media bytes are copied verbatim (no decoding/re-encoding), then read back
and checked against the SHA-256 of the ZIP entry.  A manifest is written next
to the extracted files with the placeholder mapping and per-image status.

No upload is performed.  ``showdoc_url`` and the upload/replacement status are
left for a human to fill in later.
"""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import posixpath
import re
import struct
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from lxml import etree

from .opc.image_refs import iter_image_references
from .opc.ns import IMAGE_PLACEHOLDER_ATTR, PIC_NS, V_NS, W_NS, WP_NS
from .opc.package import DOCUMENT_PART, DOCUMENT_RELS_PART, STYLES_PART, OpcPackage
from .parse.styles import StyleTable


W = "{%s}" % W_NS
V = "{%s}" % V_NS
WP = "{%s}" % WP_NS
PIC = "{%s}" % PIC_NS

PLACEHOLDER_PREFIX = "{{SHOWDOC_IMAGE_"
PLACEHOLDER_MARKER = PLACEHOLDER_PREFIX
UNMATCHED_PREFIX = "{{SHOWDOC_IMAGE_UNMATCHED_"
OCCURRENCE_PREFIX = "IMG_OCC_"

UNSUPPORTED_PREFIX = "{{SHOWDOC_UNSUPPORTED_IMAGE_"
OVERSIZED_PREFIX = "{{SHOWDOC_OVERSIZED_IMAGE_"
CONVERSION_FAILED_PREFIX = "{{SHOWDOC_CONVERSION_FAILED_IMAGE_"

COMPATIBILITY_SUPPORTED = "supported"
COMPATIBILITY_CONVERTED = "converted"
COMPATIBILITY_OVERSIZED = "oversized"
COMPATIBILITY_CONVERSION_FAILED = "conversion_failed"
COMPATIBILITY_UNSUPPORTED = "unsupported"
COMPATIBILITY_CATEGORIES = (
    COMPATIBILITY_SUPPORTED,
    COMPATIBILITY_CONVERTED,
    COMPATIBILITY_OVERSIZED,
    COMPATIBILITY_CONVERSION_FAILED,
    COMPATIBILITY_UNSUPPORTED,
)
SPECIAL_COMPATIBILITIES = (
    COMPATIBILITY_OVERSIZED,
    COMPATIBILITY_CONVERSION_FAILED,
    COMPATIBILITY_UNSUPPORTED,
)

SAFE_UPLOAD_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
CONVERTIBLE_FORMATS = {".emf", ".wmf", ".tif", ".tiff"}

DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_IMAGE_DIMENSION = 4000
DEFAULT_PREVIEW_MAX_DIMENSION = 2000
DEFAULT_CONVERT_MAX_DIMENSION = 3000


def placeholder_for(order):
    return PLACEHOLDER_PREFIX + str(order).zfill(6) + "}}"


def unmatched_placeholder(order):
    return UNMATCHED_PREFIX + str(order).zfill(6) + "}}"


def unsupported_placeholder(order):
    return UNSUPPORTED_PREFIX + str(order).zfill(6) + "}}"


def oversized_placeholder(order):
    return OVERSIZED_PREFIX + str(order).zfill(6) + "}}"


def conversion_failed_placeholder(order):
    return CONVERSION_FAILED_PREFIX + str(order).zfill(6) + "}}"


def placeholder_for_compatibility(compatibility, order):
    """Return the Markdown placeholder for a classified image position."""

    if compatibility == COMPATIBILITY_UNSUPPORTED:
        return unsupported_placeholder(order)
    if compatibility == COMPATIBILITY_OVERSIZED:
        return oversized_placeholder(order)
    if compatibility == COMPATIBILITY_CONVERSION_FAILED:
        return conversion_failed_placeholder(order)
    return placeholder_for(order)


def special_placeholder_prefixes():
    return {
        COMPATIBILITY_UNSUPPORTED: UNSUPPORTED_PREFIX,
        COMPATIBILITY_OVERSIZED: OVERSIZED_PREFIX,
        COMPATIBILITY_CONVERSION_FAILED: CONVERSION_FAILED_PREFIX,
    }


def occurrence_id_for(sequence):
    """Stable identifier for one image position in the document body."""

    return OCCURRENCE_PREFIX + str(int(sequence)).zfill(6)


def document_id_for(package, root=None):
    """Content-derived document id shared with upload_result.json.

    The id is derived from the canonical document XML plus every media part
    hash, so it does not depend on ZIP timestamps and stays identical when the
    same DOCX is converted again.  It changes when the document content or any
    image byte changes, which is the signal the upload importer needs.
    """

    hasher = hashlib.sha256()
    hasher.update(b"quicktransform-manifest-v1\0")

    if root is not None:
        try:
            body = etree.tostring(root, method="c14n", with_comments=False)
        except Exception:
            body = etree.tostring(root)
        hasher.update(body)

    try:
        part_names = sorted(package.part_names())
    except Exception:
        part_names = []

    for part in part_names:
        if not part.startswith("word/media/") or part.endswith("/"):
            continue
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\0")
        try:
            hasher.update(hashlib.sha256(package.read_part(part)).digest())
        except Exception:
            hasher.update(b"\0missing\0")

    return "doc-" + hasher.hexdigest()[:32]

COMPATIBILITY_EXTENSIONS = set(CONVERTIBLE_FORMATS)

MIME_OVERRIDES = {
    ".emf": "image/emf",
    ".wmf": "image/wmf",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".jfif": "image/jpeg",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
}

VML_SHAPE_TAGS = {
    V + "shape",
    V + "rect",
    V + "roundrect",
    V + "oval",
    V + "image",
}

_CAPTION_PATTERN = re.compile(
    r"^(?:图|图片|圖|Figure|Fig\.?)\s*[0-9０-９一二三四五六七八九十百]+"
    r"(?:[\s\-－—_.．:：]*[0-9０-９一二三四五六七八九十百]+)?",
    re.IGNORECASE,
)


@dataclass
class ImageOccurrence:
    """One appearance of an image in the document body."""

    placeholder: str
    order: int
    relationship_id: str | None = None
    source_part: str | None = None
    source_path: str | None = None
    upload_path: str | None = None
    local_path: str | None = None
    source_extension: str | None = None
    upload_extension: str | None = None
    extension: str | None = None
    source_mime_type: str | None = None
    mime_type: str | None = None
    source_size: int | None = None
    size: int | None = None
    source_sha256: str | None = None
    upload_sha256: str | None = None
    sha256: str | None = None
    sha256_verified: bool | None = None
    source_width: int | None = None
    source_height: int | None = None
    upload_width: int | None = None
    upload_height: int | None = None
    compatibility: str = COMPATIBILITY_SUPPORTED
    compatibility_reason: str = ""
    requires_conversion: bool = False
    is_duplicate: bool = False
    duplicate_of: str | None = None
    alt_text: str = ""
    alt_source: str = "fallback"
    section: str = ""
    context_before: str = ""
    context_after: str = ""
    is_compatibility_format: bool = False
    preview_path: str | None = None
    preview_status: str = "not_needed"
    preview_error: str | None = None
    showdoc_url: str | None = None
    upload_status: str = "not_uploaded"
    replacement_status: str = "pending"
    status: str = "extracted"
    error: str | None = None

    @property
    def occurrence_id(self):
        return occurrence_id_for(self.order)

    @property
    def file_name(self):
        return Path(self.local_path).name if self.local_path else None

    @property
    def source_file_name(self):
        return Path(self.source_path).name if self.source_path else None

    @property
    def upload_file_name(self):
        return Path(self.upload_path).name if self.upload_path else None

    @property
    def is_special(self):
        return self.compatibility in SPECIAL_COMPATIBILITIES

    def to_dict(self):
        return {
            # New protocol fields.
            "sequence": self.order,
            "occurrence_id": self.occurrence_id,
            "placeholder": self.placeholder,
            "source_file": self.source_path,
            "source_format": _format_name(self.source_extension),
            "source_sha256": self.source_sha256,
            "upload_file": self.upload_path,
            "upload_format": _format_name(self.upload_extension),
            "upload_sha256": self.upload_sha256,
            "size": self.size,
            "mime_type": self.mime_type,
            "compatibility": self.compatibility,
            "requires_conversion": self.requires_conversion,
            "source_size": self.source_size,
            "source_mime_type": self.source_mime_type,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "upload_width": self.upload_width,
            "upload_height": self.upload_height,
            "compatibility_reason": self.compatibility_reason,
            # Legacy aliases.
            "order": self.order,
            "relationship_id": self.relationship_id,
            "source_part": self.source_part,
            "local_file": self.local_path,
            "file_name": self.file_name,
            "local_path": self.local_path,
            "extension": self.extension,
            "sha256": self.sha256,
            "sha256_verified": self.sha256_verified,
            "is_duplicate": self.is_duplicate,
            "duplicate_of": self.duplicate_of,
            "alt_text": self.alt_text,
            "alt_source": self.alt_source,
            "section": self.section,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "is_compatibility_format": self.is_compatibility_format,
            "preview_path": self.preview_path,
            "preview_status": self.preview_status,
            "preview_error": self.preview_error,
            "showdoc_url": self.showdoc_url,
            "upload_status": self.upload_status,
            "replacement_status": self.replacement_status,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class ExtractionResult:
    document: str
    assets_dir: Path
    manifest_path: Path
    occurrences: list[ImageOccurrence] = field(default_factory=list)
    unreferenced_media: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)

    @property
    def placeholders(self):
        return [occurrence.placeholder for occurrence in self.occurrences]

    @property
    def failed(self):
        return [occurrence for occurrence in self.occurrences if occurrence.status == "failed"]


def extract_docx_images(
    docx_path,
    output_dir,
    *,
    stem=None,
    report=None,
    generate_previews=True,
    manifest_name="manifest.json",
    source_file=None,
    markdown_file=None,
    max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES,
    max_image_dimension=DEFAULT_MAX_IMAGE_DIMENSION,
    preview_max_dimension=DEFAULT_PREVIEW_MAX_DIMENSION,
):
    """Extract every body image from ``docx_path`` into ``output_dir/assets``."""

    docx_path = Path(docx_path)
    with OpcPackage(docx_path) as package:
        return extract_images_from_package(
            package,
            output_dir,
            stem=stem or docx_path.stem,
            report=report,
            generate_previews=generate_previews,
            manifest_name=manifest_name,
            source_file=source_file or docx_path.name,
            markdown_file=markdown_file or (Path(stem or docx_path.stem).name + ".md"),
            max_upload_bytes=max_upload_bytes,
            max_image_dimension=max_image_dimension,
            preview_max_dimension=preview_max_dimension,
        )


def extract_images_from_package(
    package,
    output_dir,
    *,
    doc_root=None,
    stem=None,
    report=None,
    generate_previews=True,
    manifest_name="manifest.json",
    annotate=True,
    styles=None,
    source_file=None,
    markdown_file=None,
    max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES,
    max_image_dimension=DEFAULT_MAX_IMAGE_DIMENSION,
    preview_max_dimension=DEFAULT_PREVIEW_MAX_DIMENSION,
):
    """Extract images using an already-open package.

    ``doc_root`` may be the same tree the converter is about to parse.  When
    supplied, each image reference element is annotated with its placeholder so
    the parser can attach the exact placeholder to the IR image node.
    """

    output_dir = Path(output_dir)
    assets_dir = output_dir / "assets"
    original_dir = assets_dir / "original"
    upload_dir = assets_dir / "upload"
    original_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    root = doc_root if doc_root is not None else package.read_xml(DOCUMENT_PART)
    rels = _read_relationships(package)
    part_names = package.part_names()

    document_name = getattr(getattr(package, "path", None), "name", None) or "document.docx"
    safe_stem = _safe_stem(stem or Path(document_name).stem)

    if styles is None and package.has_part(STYLES_PART):
        try:
            styles = StyleTable.from_xml(package.read_xml(STYLES_PART))
        except Exception:
            styles = None

    context = _DocumentContext(root, styles)
    document_id = document_id_for(package, root)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    source_file = source_file or document_name
    markdown_file = markdown_file or (safe_stem + ".md")

    occurrences = []
    used_parts = set()
    first_by_part = {}
    global_errors = []
    notes = [
        "未执行任何上传；showdoc_url 与 upload_status 由人工处理。",
        "原始图片保存在 assets/original，上传副本保存在 assets/upload。",
        "占位符按 document.xml 正文出现顺序生成；特殊图片保留原序号并使用特殊占位符。",
    ]

    for order, (element, relationship_id, kind) in enumerate(iter_image_references(root), start=1):
        alt_text, alt_source = _alt_for(element, order, kind)
        located = context.describe(element)
        occurrence = ImageOccurrence(
            placeholder=placeholder_for(order),
            order=order,
            relationship_id=relationship_id,
            alt_text=alt_text,
            alt_source=alt_source,
            section=located["section"],
            context_before=located["context_before"],
            context_after=located["context_after"],
        )
        occurrences.append(occurrence)

        if not relationship_id:
            _mark_special(
                occurrence,
                element,
                COMPATIBILITY_CONVERSION_FAILED,
                "图片引用缺少 r:embed / r:id",
                annotate,
            )
            continue

        relationship = rels.get(relationship_id)
        if relationship is None:
            _mark_special(
                occurrence,
                element,
                COMPATIBILITY_CONVERSION_FAILED,
                "找不到 relationship {0}".format(relationship_id),
                annotate,
            )
            continue

        target = relationship.get("target") or ""
        if relationship.get("mode") == "External":
            _mark_special(
                occurrence,
                element,
                COMPATIBILITY_UNSUPPORTED,
                "图片为外部链接，未下载：{0}".format(target),
                annotate,
            )
            continue

        part = _resolve_target(DOCUMENT_PART, target)
        occurrence.source_part = part
        used_parts.add(part)

        if part not in part_names:
            _mark_special(
                occurrence,
                element,
                COMPATIBILITY_CONVERSION_FAILED,
                "DOCX 内找不到图片文件 {0}".format(part),
                annotate,
            )
            continue

        if part in first_by_part:
            _copy_media_fields(occurrence, first_by_part[part])
            occurrence.is_duplicate = True
            occurrence.duplicate_of = first_by_part[part].placeholder
            occurrence.placeholder = placeholder_for_compatibility(
                occurrence.compatibility, order
            )
            if annotate:
                element.set(IMAGE_PLACEHOLDER_ATTR, occurrence.placeholder)
            continue

        try:
            data = package.read_part(part)
        except Exception as exc:  # zipfile.BadZipFile / KeyError / OSError
            _mark_special(
                occurrence,
                element,
                COMPATIBILITY_CONVERSION_FAILED,
                "读取图片失败：{0}".format(exc),
                annotate,
            )
            continue

        source_sha256 = hashlib.sha256(data).hexdigest()
        source_extension = _extension(part, data)
        base_name = "{0}-image-{1:06d}".format(safe_stem, order)
        source_name = base_name + source_extension
        source_output = original_dir / source_name

        try:
            source_output.write_bytes(data)
            written = source_output.read_bytes()
        except OSError as exc:
            _mark_special(
                occurrence,
                element,
                COMPATIBILITY_CONVERSION_FAILED,
                "写入原始图片失败：{0}".format(exc),
                annotate,
            )
            continue

        written_sha256 = hashlib.sha256(written).hexdigest()
        source_verified = written_sha256 == source_sha256 and len(written) == len(data)
        occurrence.source_path = _relative_path(output_dir, source_output)
        occurrence.source_extension = source_extension
        occurrence.source_mime_type = _mime_type(source_extension)
        occurrence.source_size = len(data)
        occurrence.source_sha256 = source_sha256
        occurrence.sha256 = source_sha256
        occurrence.sha256_verified = source_verified
        occurrence.is_compatibility_format = source_extension in COMPATIBILITY_EXTENSIONS
        occurrence.source_width, occurrence.source_height = _image_dimensions(
            data, source_extension
        )

        if not source_verified:
            _mark_special(
                occurrence,
                element,
                COMPATIBILITY_CONVERSION_FAILED,
                "原始图片 SHA-256 校验失败：写入文件与 DOCX 内字节不一致",
                annotate,
            )
            continue

        prepared = _prepare_image(
            data,
            source_extension,
            max_upload_bytes=max_upload_bytes,
            max_image_dimension=max_image_dimension,
            preview_max_dimension=preview_max_dimension,
            generate_previews=generate_previews,
        )
        occurrence.compatibility = prepared["compatibility"]
        occurrence.compatibility_reason = prepared["reason"]
        occurrence.requires_conversion = prepared["requires_conversion"]
        occurrence.upload_extension = prepared["upload_extension"]
        occurrence.upload_width = prepared["upload_width"]
        occurrence.upload_height = prepared["upload_height"]
        occurrence.status = prepared["status"]
        occurrence.error = prepared["reason"] if prepared["compatibility"] in SPECIAL_COMPATIBILITIES else None

        if prepared["upload_bytes"] is not None:
            upload_name = base_name + (prepared["upload_extension"] or source_extension)
            upload_output = upload_dir / upload_name
            try:
                upload_output.write_bytes(prepared["upload_bytes"])
                upload_written = upload_output.read_bytes()
            except OSError as exc:
                _mark_special(
                    occurrence,
                    element,
                    COMPATIBILITY_CONVERSION_FAILED,
                    "写入上传副本失败：{0}".format(exc),
                    annotate,
                )
                first_by_part[part] = occurrence
                continue

            upload_sha256 = hashlib.sha256(upload_written).hexdigest()
            if upload_sha256 != prepared["upload_sha256"]:
                _mark_special(
                    occurrence,
                    element,
                    COMPATIBILITY_CONVERSION_FAILED,
                    "上传副本 SHA-256 校验失败：写入文件与生成的副本不一致",
                    annotate,
                )
                first_by_part[part] = occurrence
                continue

            occurrence.upload_path = _relative_path(output_dir, upload_output)
            occurrence.upload_sha256 = upload_sha256
            occurrence.upload_extension = prepared["upload_extension"]
            occurrence.mime_type = _mime_type(occurrence.upload_extension)
            occurrence.size = len(upload_written)
            occurrence.extension = occurrence.upload_extension
            occurrence.preview_path = occurrence.upload_path
            occurrence.preview_status = prepared["preview_status"]
            occurrence.preview_error = prepared["reason"] if prepared["preview_status"] == "failed" else None
        else:
            occurrence.upload_path = None
            occurrence.upload_sha256 = None
            occurrence.mime_type = occurrence.source_mime_type
            occurrence.size = occurrence.source_size
            occurrence.extension = source_extension
            occurrence.preview_status = prepared["preview_status"]
            occurrence.preview_error = prepared["reason"] if prepared["compatibility"] in SPECIAL_COMPATIBILITIES else None

        occurrence.local_path = occurrence.upload_path or occurrence.source_path
        occurrence.placeholder = placeholder_for_compatibility(
            occurrence.compatibility, order
        )
        if annotate:
            element.set(IMAGE_PLACEHOLDER_ATTR, occurrence.placeholder)

        if occurrence.compatibility in SPECIAL_COMPATIBILITIES:
            _report_special(report, occurrence)
        elif occurrence.compatibility == COMPATIBILITY_CONVERTED:
            _report(
                report,
                "image_converted",
                "图片",
                "{0}（{1}）已转换为 {2} 上传副本；原始文件保留在 {3}".format(
                    occurrence.placeholder,
                    source_extension,
                    occurrence.upload_extension,
                    occurrence.source_path,
                ),
            )

        first_by_part[part] = occurrence

    unreferenced_media = _collect_unreferenced_media(package, used_parts)
    if unreferenced_media:
        _report(
            report,
            "image_unreferenced",
            "图片",
            "有 {0} 个 media 文件未被正文引用，已列入 manifest 的 unreferenced_media".format(
                len(unreferenced_media)
            ),
        )

    collisions = _placeholder_collisions(root)
    if collisions:
        detail = "文档正文已包含占位符样式文本，可能与生成结果冲突：{0}".format(
            "、".join(collisions[:5])
        )
        _report(report, "image_placeholder_collision", "图片", detail)
        global_errors.append(
            {
                "kind": "placeholder_collision",
                "detail": detail,
                "samples": collisions[:20],
            }
        )

    errors = []
    for occurrence in occurrences:
        if occurrence.compatibility not in SPECIAL_COMPATIBILITIES:
            continue
        errors.append(
            {
                "kind": (
                    "image_failed"
                    if occurrence.compatibility == COMPATIBILITY_CONVERSION_FAILED
                    else "image_{0}".format(occurrence.compatibility)
                ),
                "category": occurrence.compatibility,
                "placeholder": occurrence.placeholder,
                "order": occurrence.order,
                "relationship_id": occurrence.relationship_id,
                "source_part": occurrence.source_part,
                "source_file": occurrence.source_path,
                "detail": occurrence.compatibility_reason or occurrence.error,
            }
        )
    errors.extend(global_errors)

    category_counts = {
        category: sum(
            1 for occurrence in occurrences if occurrence.compatibility == category
        )
        for category in COMPATIBILITY_CATEGORIES
    }
    special_count = sum(
        1 for occurrence in occurrences if occurrence.compatibility in SPECIAL_COMPATIBILITIES
    )
    summary = {
        "occurrences": len(occurrences),
        "unique_media": len(first_by_part),
        "duplicates": sum(1 for occurrence in occurrences if occurrence.is_duplicate),
        **category_counts,
        "special": special_count,
        "failed": sum(1 for occurrence in occurrences if occurrence.status == "failed"),
        # Legacy alias: old callers treated EMF/WMF/TIFF as "compatibility".
        "compatibility": category_counts[COMPATIBILITY_CONVERTED],
        "unreferenced_media": len(unreferenced_media),
    }

    manifest = {
        "schema_version": 1,
        "document_id": document_id,
        "source_file": source_file,
        "markdown_file": markdown_file,
        "created_at": created_at,
        "compatibility_thresholds": {
            "max_upload_bytes": max_upload_bytes,
            "max_image_dimension": max_image_dimension,
            "preview_max_dimension": preview_max_dimension,
        },
        "placeholder_prefixes": {
            "normal": PLACEHOLDER_PREFIX,
            "unsupported": UNSUPPORTED_PREFIX,
            "oversized": OVERSIZED_PREFIX,
            "conversion_failed": CONVERSION_FAILED_PREFIX,
        },
        # Legacy aliases kept so older tooling and tests keep working.
        "document": document_name,
        "generated_at": created_at,
        "placeholder_format": "{{SHOWDOC_IMAGE_%06d}}",
        "occurrence_format": "IMG_OCC_%06d",
        "assets_dir": "assets",
        "original_dir": "assets/original",
        "upload_dir": "assets/upload",
        "summary": summary,
        "images": [occurrence.to_dict() for occurrence in occurrences],
        "unreferenced_media": unreferenced_media,
        "errors": errors,
        "notes": notes,
    }

    manifest_name = Path(manifest_name).name or "manifest.json"
    manifest_path = assets_dir / manifest_name
    _write_json(manifest_path, manifest)

    return ExtractionResult(
        document=document_name,
        assets_dir=assets_dir,
        manifest_path=manifest_path,
        occurrences=occurrences,
        unreferenced_media=unreferenced_media,
        errors=errors,
        notes=notes,
        summary=summary,
        manifest=manifest,
    )


class _DocumentContext:
    """Best-effort section and surrounding text for each image position.

    Word does not store "which chapter does this image belong to", so this
    walks the paragraph stream once: the nearest preceding heading paragraph is
    the section, the text before/after the image in its own paragraph (or the
    neighbouring paragraph) is the context.  Everything is truncated because it
    is only used to help a human locate an image that failed to upload.
    """

    def __init__(self, root, styles):
        self.paragraphs = [paragraph for paragraph in root.iter(W + "p")]
        self.index_by_id = {
            id(paragraph): index for index, paragraph in enumerate(self.paragraphs)
        }
        self.texts = [_paragraph_text(paragraph) for paragraph in self.paragraphs]
        self.headings = [
            _paragraph_heading_level(paragraph, styles)
            for paragraph in self.paragraphs
        ]

    def describe(self, element):
        paragraph = _nearest_ancestor(element, W + "p")
        index = self.index_by_id.get(id(paragraph)) if paragraph is not None else None
        if index is None:
            return {"section": "", "context_before": "", "context_after": ""}

        before, after = _text_around(element, paragraph)
        if not before:
            before = self._neighbour_text(index, -1)
        if not after:
            after = self._neighbour_text(index, 1)

        section = ""
        for position in range(index, -1, -1):
            if self.headings[position]:
                section = self.texts[position]
                break

        return {
            "section": _truncate(section, 120),
            "context_before": _truncate_tail(before, 160),
            "context_after": _truncate_head(after, 160),
        }

    def _neighbour_text(self, index, step):
        position = index + step
        while 0 <= position < len(self.paragraphs):
            text = self.texts[position]
            if text:
                return text
            position += step
        return ""


def _paragraph_heading_level(paragraph, styles):
    ppr = paragraph.find(W + "pPr")
    if ppr is None:
        return None

    outline = ppr.find(W + "outlineLvl")
    if outline is not None:
        value = _to_int(outline.get(W + "val"))
        if value is not None and value < 9:
            return value + 1

    style_element = ppr.find(W + "pStyle")
    if style_element is None:
        return None
    style_id = style_element.get(W + "val")
    if not style_id:
        return None

    if styles is not None:
        level = styles.heading_level(style_id)
        if level:
            return level

    match = re.match(r"^(?:heading|标题|h)\s*([1-9])$", style_id, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _text_around(element, paragraph):
    """Return text before and after ``element`` inside its paragraph."""

    before = []
    after = []
    seen = False
    for node in paragraph.iter():
        if node is element:
            seen = True
            continue
        if not isinstance(node.tag, str):
            continue
        if node.tag == W + "t":
            (after if seen else before).append(node.text or "")
        elif node.tag == W + "tab":
            (after if seen else before).append(" ")
        elif node.tag in (W + "br", W + "cr"):
            (after if seen else before).append(" ")

    return (
        re.sub(r"\s+", " ", "".join(before)).strip(),
        re.sub(r"\s+", " ", "".join(after)).strip(),
    )


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truncate(text, limit):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _truncate_tail(text, limit):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else "…" + text[-(limit - 1):]


def _truncate_head(text, limit):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _read_relationships(package):
    if not package.has_part(DOCUMENT_RELS_PART):
        return {}
    root = package.read_xml(DOCUMENT_RELS_PART)
    relationships = {}
    for rel in root:
        relationship_id = rel.get("Id")
        if not relationship_id:
            continue
        relationships[relationship_id] = {
            "target": rel.get("Target") or "",
            "mode": rel.get("TargetMode") or "Internal",
            "type": rel.get("Type") or "",
        }
    return relationships


def _resolve_target(source_part, target):
    target = (target or "").replace("\\", "/").strip()
    if not target:
        return ""
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    base_dir = posixpath.dirname(source_part)
    return posixpath.normpath(posixpath.join(base_dir, target))


def _mark_special(occurrence, element, compatibility, detail, annotate):
    occurrence.compatibility = compatibility
    occurrence.compatibility_reason = detail
    occurrence.requires_conversion = True
    occurrence.placeholder = placeholder_for_compatibility(compatibility, occurrence.order)
    occurrence.status = (
        "failed"
        if compatibility == COMPATIBILITY_CONVERSION_FAILED
        else compatibility
    )
    occurrence.error = detail
    occurrence.local_path = occurrence.source_path
    if occurrence.source_path:
        occurrence.size = occurrence.size or occurrence.source_size
        occurrence.mime_type = occurrence.mime_type or occurrence.source_mime_type
        occurrence.extension = occurrence.extension or occurrence.source_extension
    if annotate:
        element.set(IMAGE_PLACEHOLDER_ATTR, occurrence.placeholder)


def _copy_media_fields(target, source):
    target.source_path = source.source_path
    target.upload_path = source.upload_path
    target.local_path = source.local_path
    target.source_extension = source.source_extension
    target.upload_extension = source.upload_extension
    target.extension = source.extension
    target.source_mime_type = source.source_mime_type
    target.mime_type = source.mime_type
    target.source_size = source.source_size
    target.size = source.size
    target.source_sha256 = source.source_sha256
    target.upload_sha256 = source.upload_sha256
    target.sha256 = source.sha256
    target.sha256_verified = source.sha256_verified
    target.source_width = source.source_width
    target.source_height = source.source_height
    target.upload_width = source.upload_width
    target.upload_height = source.upload_height
    target.compatibility = source.compatibility
    target.compatibility_reason = source.compatibility_reason
    target.requires_conversion = source.requires_conversion
    target.is_compatibility_format = source.is_compatibility_format
    target.preview_path = source.preview_path
    target.preview_status = source.preview_status
    target.preview_error = source.preview_error
    target.status = source.status
    target.error = source.error


def _collect_unreferenced_media(package, used_parts):
    items = []
    for part in sorted(package.part_names()):
        if not part.startswith("word/media/") or part.endswith("/"):
            continue
        if part in used_parts:
            continue
        try:
            data = package.read_part(part)
        except Exception as exc:
            items.append({"part": part, "error": str(exc)})
            continue
        items.append(
            {
                "part": part,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "reason": "未被 document.xml 正文引用（可能属于页眉页脚或未被使用）",
            }
        )
    return items


def _placeholder_collisions(root):
    markers = (
        PLACEHOLDER_PREFIX,
        UNSUPPORTED_PREFIX,
        OVERSIZED_PREFIX,
        CONVERSION_FAILED_PREFIX,
    )
    samples = []
    for text_element in root.iter(W + "t"):
        text = text_element.text or ""
        if any(marker in text for marker in markers):
            cleaned = re.sub(r"\s+", " ", text).strip()
            if cleaned:
                samples.append(cleaned[:120])
            if len(samples) >= 20:
                break
    return samples


def _alt_for(element, order, kind):
    alt, source = _drawing_alt(element)
    if alt:
        return alt, source

    alt, source = _vml_alt(element)
    if alt:
        return alt, source

    caption = _caption_for(element)
    if caption:
        return caption, "caption"

    return "图片{0}".format(order), "fallback"


def _drawing_alt(element):
    parent = element.getparent()
    while parent is not None:
        if parent.tag in (WP + "inline", WP + "anchor"):
            doc_pr = parent.find(WP + "docPr")
            if doc_pr is None:
                doc_pr = parent.find(".//" + WP + "docPr")
            if doc_pr is not None:
                for attribute in ("descr", "title"):
                    value = _clean_text(doc_pr.get(attribute))
                    if value:
                        return value, "docPr:" + attribute
        parent = parent.getparent()

    parent = element.getparent()
    while parent is not None:
        if parent.tag == PIC + "pic":
            c_nv_pr = parent.find(".//" + PIC + "cNvPr")
            if c_nv_pr is not None:
                for attribute in ("descr", "title"):
                    value = _clean_text(c_nv_pr.get(attribute))
                    if value:
                        return value, "cNvPr:" + attribute
        parent = parent.getparent()
    return "", "fallback"


def _vml_alt(element):
    parent = element.getparent()
    while parent is not None:
        if parent.tag in VML_SHAPE_TAGS:
            for attribute in ("alt", "title"):
                value = _clean_text(parent.get(attribute))
                if value:
                    return value, "vml:" + attribute
            for name, raw_value in parent.attrib.items():
                try:
                    local_name = etree.QName(name).localname
                except ValueError:
                    continue
                if local_name in ("alt", "title"):
                    value = _clean_text(raw_value)
                    if value:
                        return value, "vml:" + local_name
        parent = parent.getparent()
    return "", "fallback"


def _caption_for(element):
    paragraph = _nearest_ancestor(element, W + "p")
    if paragraph is None:
        return ""
    for sibling in (paragraph.getnext(), paragraph.getprevious()):
        if sibling is None or sibling.tag != W + "p":
            continue
        text = _paragraph_text(sibling)
        if _looks_like_caption(text):
            return text
    return ""


def _nearest_ancestor(element, tag):
    parent = element.getparent()
    while parent is not None:
        if parent.tag == tag:
            return parent
        parent = parent.getparent()
    return None


def _paragraph_text(paragraph):
    parts = []
    for child in paragraph.iter():
        if child.tag == W + "t":
            parts.append(child.text or "")
        elif child.tag == W + "tab":
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _looks_like_caption(text):
    if not text or len(text) > 200:
        return False
    return _CAPTION_PATTERN.match(text) is not None


def _clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _extension(part, data):
    extension = Path(part).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", extension or ""):
        return extension
    return _sniff_extension(data)


def _sniff_extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"BM"):
        return ".bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return ".tif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.lstrip().startswith(b"<svg") or b"<svg" in data[:512]:
        return ".svg"
    if data.startswith(b"\x01\x00\x00\x00") and b" EMF" in data[40:80]:
        return ".emf"
    if data.startswith((b"\xd7\xcd\xc6\x9a", b"\x9a\xc6\xcd\xd7")):
        return ".wmf"
    return ".bin"


def _mime_type(extension):
    if not extension:
        return "application/octet-stream"
    return (
        MIME_OVERRIDES.get(extension)
        or mimetypes.guess_type("image" + extension)[0]
        or "application/octet-stream"
    )


def _format_name(extension):
    return extension.lstrip(".").lower() if extension else None


def _report_special(report, occurrence):
    kind = (
        "image_failed"
        if occurrence.compatibility == COMPATIBILITY_CONVERSION_FAILED
        else "image_{0}".format(occurrence.compatibility)
    )
    _report(
        report,
        kind,
        "图片",
        "{0}（{1}）：{2}{3}".format(
            occurrence.placeholder,
            occurrence.compatibility,
            occurrence.compatibility_reason,
            "；原始文件保留在 {0}".format(occurrence.source_path)
            if occurrence.source_path
            else "",
        ),
    )


# ---------------------------------------------------------------------------
# Compatibility pre-check and upload copies


def _prepare_image(
    data,
    extension,
    *,
    max_upload_bytes,
    max_image_dimension,
    preview_max_dimension,
    generate_previews,
):
    """Classify one source image and build an upload copy when needed."""

    max_upload_bytes = max_upload_bytes or DEFAULT_MAX_UPLOAD_BYTES
    max_image_dimension = max_image_dimension or DEFAULT_MAX_IMAGE_DIMENSION
    preview_max_dimension = preview_max_dimension or DEFAULT_PREVIEW_MAX_DIMENSION
    source_width, source_height = _image_dimensions(data, extension)

    if extension in CONVERTIBLE_FORMATS:
        if not generate_previews:
            return _prepared_special(
                COMPATIBILITY_CONVERSION_FAILED,
                "已禁用转换/预览生成，无法生成 {0} 上传副本".format(extension),
            )
        upload, upload_ext, width, height, error = _convert_to_upload(
            data,
            extension,
            max_dimension=DEFAULT_CONVERT_MAX_DIMENSION,
            max_bytes=max_upload_bytes,
        )
        if error:
            return _prepared_special(
                COMPATIBILITY_CONVERSION_FAILED,
                "转换 {0} 失败：{1}".format(extension, error),
            )
        return _prepared_upload(
            COMPATIBILITY_CONVERTED,
            upload,
            upload_ext,
            width,
            height,
            reason="已转换为上传副本，原始文件保持不动",
            preview_status="generated",
            status="compatibility",
        )

    if extension in SAFE_UPLOAD_FORMATS:
        oversized, oversize_reason = _is_oversized(
            len(data),
            source_width,
            source_height,
            max_upload_bytes=max_upload_bytes,
            max_image_dimension=max_image_dimension,
        )
        if not oversized:
            return {
                "compatibility": COMPATIBILITY_SUPPORTED,
                "requires_conversion": False,
                "status": "extracted",
                "reason": "",
                "upload_bytes": data,
                "upload_extension": extension,
                "upload_sha256": hashlib.sha256(data).hexdigest(),
                "upload_width": source_width,
                "upload_height": source_height,
                "preview_status": "not_needed",
            }

        if not generate_previews:
            return _prepared_special(
                COMPATIBILITY_OVERSIZED,
                "图片超过上传阈值（{0}），且已禁用预览生成".format(oversize_reason),
            )

        upload, upload_ext, width, height, error = _make_document_preview(
            data,
            extension,
            max_dimension=preview_max_dimension,
            max_bytes=max_upload_bytes,
        )
        if error:
            return _prepared_special(
                COMPATIBILITY_OVERSIZED,
                "图片超过上传阈值（{0}），生成预览失败：{1}".format(
                    oversize_reason, error
                ),
            )
        return _prepared_upload(
            COMPATIBILITY_OVERSIZED,
            upload,
            upload_ext,
            width,
            height,
            reason=(
                "图片超过上传阈值（{0}），已生成预览上传副本；"
                "按策略保留特殊占位符，不自动替换".format(oversize_reason)
            ),
            preview_status="generated",
            status="oversized",
        )

    return _prepared_special(
        COMPATIBILITY_UNSUPPORTED,
        "不支持的图片格式：{0}；未生成上传副本".format(extension or "unknown"),
    )


def _prepared_upload(
    compatibility,
    data,
    extension,
    width,
    height,
    *,
    reason,
    preview_status,
    status,
):
    return {
        "compatibility": compatibility,
        "requires_conversion": True,
        "status": status,
        "reason": reason,
        "upload_bytes": data,
        "upload_extension": extension,
        "upload_sha256": hashlib.sha256(data).hexdigest(),
        "upload_width": width,
        "upload_height": height,
        "preview_status": preview_status,
    }


def _prepared_special(compatibility, reason):
    return {
        "compatibility": compatibility,
        "requires_conversion": True,
        "status": (
            "failed"
            if compatibility == COMPATIBILITY_CONVERSION_FAILED
            else compatibility
        ),
        "reason": reason,
        "upload_bytes": None,
        "upload_extension": None,
        "upload_sha256": None,
        "upload_width": None,
        "upload_height": None,
        "preview_status": "failed",
    }


def _is_oversized(size, width, height, *, max_upload_bytes, max_image_dimension):
    reasons = []
    if max_upload_bytes and size > max_upload_bytes:
        reasons.append(
            "文件 {0} 字节 > 上限 {1} 字节".format(size, max_upload_bytes)
        )
    if max_image_dimension and width and height:
        if width > max_image_dimension or height > max_image_dimension:
            reasons.append(
                "像素 {0}×{1} > 上限 {2}".format(
                    width, height, max_image_dimension
                )
            )
    return bool(reasons), "；".join(reasons)


def _image_dimensions(data, extension):
    """Best-effort pixel dimensions without decoding the whole image."""

    if extension in CONVERTIBLE_FORMATS:
        return None, None

    try:
        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:
        pass

    return _dimensions_from_header(data)


def _dimensions_from_header(data):
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
            width, height = struct.unpack(">II", data[16:24])
            return int(width), int(height)
        if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
            if len(data) >= 10:
                width, height = struct.unpack("<HH", data[6:10])
                return int(width), int(height)
        if data.startswith(b"BM") and len(data) >= 26:
            width, height = struct.unpack("<ii", data[18:26])
            return abs(int(width)), abs(int(height))
        if data.startswith(b"\xff\xd8\xff"):
            return _jpeg_dimensions(data)
    except Exception:
        return None, None
    return None, None


def _jpeg_dimensions(data):
    index = 2
    length = len(data)
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > length:
            break
        segment_length = struct.unpack(">H", data[index:index + 2])[0]
        if segment_length < 2:
            break
        if marker in (
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        ):
            if index + 7 <= length:
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                return int(width), int(height)
        index += segment_length
    return None, None


def _convert_to_upload(data, extension, *, max_dimension, max_bytes):
    """Convert EMF/WMF/TIFF (or other formats) into a PNG upload copy.

    Returns ``(bytes, extension, width, height, error)``.
    """

    errors = []
    unavailable = []

    try:
        from PIL import Image as PILImage
    except Exception:
        PILImage = None
        unavailable.append("Pillow")

    try:
        import fitz as fitz_module
    except Exception:
        fitz_module = None
        unavailable.append("PyMuPDF")

    # Vector formats benefit from PyMuPDF's page rendering at a higher zoom.
    attempts = ["pymupdf", "pillow"]
    if extension not in (".emf", ".wmf"):
        attempts = ["pillow", "pymupdf"]

    for attempt in attempts:
        if attempt == "pillow" and PILImage is not None:
            result = _encode_with_pillow(
                data,
                max_dimension=max_dimension,
                max_bytes=max_bytes,
                image_module=PILImage,
            )
            if result[4] is None:
                return result
            errors.append("Pillow: {0}".format(result[4]))
        elif attempt == "pymupdf" and fitz_module is not None:
            result = _encode_with_pymupdf(
                data,
                extension,
                max_dimension=max_dimension,
                max_bytes=max_bytes,
            )
            if result[4] is None:
                return result
            errors.append("PyMuPDF: {0}".format(result[4]))

    if errors:
        return None, None, None, None, "；".join(errors)
    return (
        None,
        None,
        None,
        None,
        "{0} 未安装，无法转换".format("/".join(unavailable)),
    )


def _make_document_preview(data, extension, *, max_dimension, max_bytes):
    return _convert_to_upload(
        data,
        extension,
        max_dimension=max_dimension,
        max_bytes=max_bytes,
    )


def _encode_with_pillow(data, *, max_dimension, max_bytes, image_module):
    try:
        with image_module.open(io.BytesIO(data)) as image:
            if getattr(image, "n_frames", 1) > 1:
                image.seek(0)
            image.load()
            width, height = image.size
            limit = max_dimension or max(width, height)
            if max(width, height) > limit:
                scale = float(limit) / float(max(width, height))
                size = (
                    max(1, int(round(width * scale))),
                    max(1, int(round(height * scale))),
                )
                image = image.resize(size, image_module.LANCZOS)
            rgba = image.convert("RGBA")
            rgb = _flatten_to_rgb(rgba)
            width, height = rgb.size

            png = _encode_pillow_image(rgb, image_module, "PNG")
            if len(png) <= max_bytes:
                return png, ".png", width, height, None

            jpeg = _encode_pillow_image(rgb, image_module, "JPEG")
            if len(jpeg) <= max_bytes:
                return jpeg, ".jpg", width, height, None

            # Still too large: progressively shrink, preferring PNG.
            current = rgb
            current_size = (width, height)
            for _ in range(8):
                next_width = max(320, int(current_size[0] * 0.75))
                next_height = max(240, int(current_size[1] * 0.75))
                if next_width == current_size[0] and next_height == current_size[1]:
                    break
                current = current.resize(
                    (next_width, next_height), image_module.LANCZOS
                )
                current_size = (next_width, next_height)
                png = _encode_pillow_image(current, image_module, "PNG")
                if len(png) <= max_bytes:
                    return png, ".png", next_width, next_height, None
                jpeg = _encode_pillow_image(current, image_module, "JPEG")
                if len(jpeg) <= max_bytes:
                    return jpeg, ".jpg", next_width, next_height, None

            return (
                None,
                None,
                None,
                None,
                "生成的 PNG/JPEG 仍超过 {0} 字节上限".format(max_bytes),
            )
    except Exception as exc:
        return None, None, None, None, str(exc)


def _flatten_to_rgb(image):
    if image.mode == "RGB":
        return image
    background = image.convert("RGBA")
    canvas = _new_rgb_canvas(background.size)
    canvas.paste(background, mask=background.split()[-1])
    return canvas


def _new_rgb_canvas(size):
    from PIL import Image as PILImage

    return PILImage.new("RGB", size, (255, 255, 255))


def _encode_pillow_image(image, image_module, format_name):
    buffer = io.BytesIO()
    if format_name == "PNG":
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        image.save(buffer, "PNG", optimize=True)
    else:
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(buffer, "JPEG", quality=85, optimize=True)
    return buffer.getvalue()


def _encode_with_pymupdf(data, extension, *, max_dimension, max_bytes):
    fitz = None
    try:
        import fitz as fitz_module

        fitz = fitz_module
    except Exception as exc:
        return None, None, None, None, "PyMuPDF 不可用：{0}".format(exc)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=extension or ".bin", delete=False
        ) as temp:
            temp.write(data)
            temp_path = Path(temp.name)

        document = fitz.open(str(temp_path))
        try:
            if document.page_count <= 0:
                raise ValueError("没有可渲染页面")
            page = document[0]
            rect = page.rect
            long_side = max(1.0, float(rect.width), float(rect.height))
            target = max_dimension or DEFAULT_CONVERT_MAX_DIMENSION
            zoom = max(0.05, min(6.0, float(target) / long_side))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            png = pixmap.tobytes("png")
            width, height = pixmap.width, pixmap.height
        finally:
            document.close()

        if len(png) <= max_bytes:
            return png, ".png", width, height, None

        try:
            from PIL import Image as PILImage

            return _encode_with_pillow(
                png,
                max_dimension=min(target, max(width, height)),
                max_bytes=max_bytes,
                image_module=PILImage,
            )
        except Exception:
            return (
                None,
                None,
                None,
                None,
                "渲染得到的 PNG 超过 {0} 字节上限".format(max_bytes),
            )
    except Exception as exc:
        return None, None, None, None, str(exc)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _relative_path(output_dir, path):
    try:
        return Path(path).relative_to(Path(output_dir)).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _safe_stem(name):
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(name))
    return cleaned.strip("._") or "document"


def _report(report, kind, where, detail, level="warn"):
    if report is not None:
        report.add(kind, where, detail, level=level)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
