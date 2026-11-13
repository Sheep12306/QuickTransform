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
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from .opc.image_refs import iter_image_references
from .opc.ns import IMAGE_PLACEHOLDER_ATTR, PIC_NS, V_NS, W_NS, WP_NS
from .opc.package import DOCUMENT_PART, DOCUMENT_RELS_PART, OpcPackage


W = "{%s}" % W_NS
V = "{%s}" % V_NS
WP = "{%s}" % WP_NS
PIC = "{%s}" % PIC_NS

PLACEHOLDER_PREFIX = "{{SHOWDOC_IMAGE_"
PLACEHOLDER_MARKER = PLACEHOLDER_PREFIX
UNMATCHED_PREFIX = "{{SHOWDOC_IMAGE_UNMATCHED_"


def placeholder_for(order):
    return PLACEHOLDER_PREFIX + str(order).zfill(6) + "}}"


def unmatched_placeholder(order):
    return UNMATCHED_PREFIX + str(order).zfill(6) + "}}"

COMPATIBILITY_EXTENSIONS = {".emf", ".wmf", ".tif", ".tiff"}

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
    local_path: str | None = None
    extension: str | None = None
    mime_type: str | None = None
    size: int | None = None
    sha256: str | None = None
    sha256_verified: bool | None = None
    is_duplicate: bool = False
    duplicate_of: str | None = None
    alt_text: str = ""
    alt_source: str = "fallback"
    is_compatibility_format: bool = False
    preview_path: str | None = None
    preview_status: str = "not_needed"
    preview_error: str | None = None
    showdoc_url: str | None = None
    upload_status: str = "not_uploaded"
    replacement_status: str = "pending"
    status: str = "extracted"
    error: str | None = None

    def to_dict(self):
        return {
            "placeholder": self.placeholder,
            "order": self.order,
            "relationship_id": self.relationship_id,
            "source_part": self.source_part,
            "local_path": self.local_path,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "size": self.size,
            "sha256": self.sha256,
            "sha256_verified": self.sha256_verified,
            "is_duplicate": self.is_duplicate,
            "duplicate_of": self.duplicate_of,
            "alt_text": self.alt_text,
            "alt_source": self.alt_source,
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
):
    """Extract every body image from ``docx_path`` into ``output_dir/assets``."""

    with OpcPackage(docx_path) as package:
        return extract_images_from_package(
            package,
            output_dir,
            stem=stem or Path(docx_path).stem,
            report=report,
            generate_previews=generate_previews,
            manifest_name=manifest_name,
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
):
    """Extract images using an already-open package.

    ``doc_root`` may be the same tree the converter is about to parse.  When
    supplied, each image reference element is annotated with its placeholder so
    the parser can attach the exact placeholder to the IR image node.
    """

    output_dir = Path(output_dir)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    root = doc_root if doc_root is not None else package.read_xml(DOCUMENT_PART)
    rels = _read_relationships(package)
    part_names = package.part_names()

    document_name = getattr(getattr(package, "path", None), "name", None) or "document.docx"
    safe_stem = _safe_stem(stem or Path(document_name).stem)

    occurrences = []
    used_parts = set()
    first_by_part = {}
    global_errors = []
    notes = [
        "未执行任何上传；showdoc_url 与 upload_status 由人工处理。",
        "占位符按 document.xml 正文出现顺序生成，同一媒体文件只保存一次。",
    ]
    unique_counter = 0

    for order, (element, relationship_id, kind) in enumerate(iter_image_references(root), start=1):
        placeholder = placeholder_for(order)
        if annotate:
            element.set(IMAGE_PLACEHOLDER_ATTR, placeholder)

        alt_text, alt_source = _alt_for(element, order, kind)
        occurrence = ImageOccurrence(
            placeholder=placeholder,
            order=order,
            relationship_id=relationship_id,
            alt_text=alt_text,
            alt_source=alt_source,
        )
        occurrences.append(occurrence)

        if not relationship_id:
            _mark_failed(occurrence, "图片引用缺少 r:embed / r:id")
            continue

        relationship = rels.get(relationship_id)
        if relationship is None:
            _mark_failed(occurrence, "找不到 relationship {0}".format(relationship_id))
            continue

        target = relationship.get("target") or ""
        if relationship.get("mode") == "External":
            _mark_failed(occurrence, "图片为外部链接，未下载：{0}".format(target))
            continue

        part = _resolve_target(DOCUMENT_PART, target)
        occurrence.source_part = part
        used_parts.add(part)

        if part not in part_names:
            _mark_failed(occurrence, "DOCX 内找不到图片文件 {0}".format(part))
            continue

        if part in first_by_part:
            _copy_media_fields(occurrence, first_by_part[part])
            occurrence.is_duplicate = True
            occurrence.duplicate_of = first_by_part[part].placeholder
            continue

        try:
            data = package.read_part(part)
        except Exception as exc:  # zipfile.BadZipFile / KeyError / OSError
            _mark_failed(occurrence, "读取图片失败：{0}".format(exc))
            continue

        sha256 = hashlib.sha256(data).hexdigest()
        extension = _extension(part, data)
        occurrence.size = len(data)
        occurrence.sha256 = sha256
        occurrence.extension = extension
        occurrence.mime_type = _mime_type(extension)
        occurrence.is_compatibility_format = extension in COMPATIBILITY_EXTENSIONS

        unique_counter += 1
        file_name = "{0}-image-{1:06d}{2}".format(safe_stem, unique_counter, extension)
        output_path = assets_dir / file_name

        try:
            output_path.write_bytes(data)
            written = output_path.read_bytes()
        except OSError as exc:
            _mark_failed(occurrence, "写入图片失败：{0}".format(exc))
            continue

        written_sha256 = hashlib.sha256(written).hexdigest()
        occurrence.local_path = _relative_path(output_dir, output_path)
        occurrence.sha256_verified = written_sha256 == sha256 and len(written) == len(data)
        if not occurrence.sha256_verified:
            _mark_failed(occurrence, "SHA-256 校验失败：写入文件与 DOCX 内原始图片不一致")
            continue

        if occurrence.is_compatibility_format:
            occurrence.status = "compatibility"
            _report(
                report,
                "image_compatibility",
                "图片",
                "{0} 为兼容格式（{1}），已保留原始文件；Markdown/ShowDoc 可能无法直接显示，"
                "兼容预览不等于字节级显示保证。".format(occurrence.placeholder, extension),
            )
            if generate_previews:
                preview_path, preview_error, preview_status = _make_preview(
                    data, assets_dir, file_name
                )
                occurrence.preview_status = preview_status
                occurrence.preview_error = preview_error
                if preview_path is not None:
                    occurrence.preview_path = _relative_path(output_dir, preview_path)
            else:
                occurrence.preview_status = "disabled"
        else:
            occurrence.status = "extracted"

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

    errors = [
        {
            "kind": "image_failed",
            "placeholder": occurrence.placeholder,
            "order": occurrence.order,
            "relationship_id": occurrence.relationship_id,
            "source_part": occurrence.source_part,
            "detail": occurrence.error,
        }
        for occurrence in occurrences
        if occurrence.status == "failed"
    ]
    errors.extend(global_errors)

    summary = {
        "occurrences": len(occurrences),
        "unique_media": len(first_by_part),
        "duplicates": sum(1 for occurrence in occurrences if occurrence.is_duplicate),
        "failed": sum(1 for occurrence in occurrences if occurrence.status == "failed"),
        "compatibility": sum(1 for occurrence in occurrences if occurrence.is_compatibility_format),
        "unreferenced_media": len(unreferenced_media),
    }

    manifest = {
        "schema_version": 1,
        "document": document_name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "placeholder_format": "{{SHOWDOC_IMAGE_%06d}}",
        "assets_dir": "assets",
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


def _mark_failed(occurrence, detail):
    occurrence.status = "failed"
    occurrence.error = detail


def _copy_media_fields(target, source):
    target.local_path = source.local_path
    target.extension = source.extension
    target.mime_type = source.mime_type
    target.size = source.size
    target.sha256 = source.sha256
    target.sha256_verified = source.sha256_verified
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
    samples = []
    for text_element in root.iter(W + "t"):
        text = text_element.text or ""
        if PLACEHOLDER_MARKER in text:
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
    return (
        MIME_OVERRIDES.get(extension)
        or mimetypes.guess_type("image" + extension)[0]
        or "application/octet-stream"
    )


def _make_preview(data, assets_dir, base_name):
    """Best-effort PNG preview for formats ShowDoc may not display.

    Pillow is optional; PyMuPDF is already a project dependency and can render
    some EMF/TIFF variants.  The original media bytes are never modified.
    """

    preview_name = base_name.rsplit(".", 1)[0] + "-preview.png"
    preview_path = assets_dir / preview_name
    errors = []
    unavailable = []

    try:
        from PIL import Image as PILImage
    except Exception:
        PILImage = None
        unavailable.append("Pillow")

    if PILImage is not None:
        try:
            with PILImage.open(io.BytesIO(data)) as image:
                if getattr(image, "n_frames", 1) > 1:
                    image.seek(0)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA")
                image.save(preview_path, "PNG")
            return preview_path, None, "generated"
        except Exception as exc:
            preview_path.unlink(missing_ok=True)
            errors.append("Pillow: {0}".format(exc))

    try:
        import fitz
    except Exception:
        fitz = None
        unavailable.append("PyMuPDF")

    if fitz is not None:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=Path(base_name).suffix,
                dir=str(assets_dir),
                delete=False,
            ) as temp:
                temp.write(data)
                temp_path = Path(temp.name)
            document = fitz.open(str(temp_path))
            try:
                if document.page_count <= 0:
                    raise ValueError("没有可渲染页面")
                pixmap = document[0].get_pixmap()
                pixmap.save(str(preview_path))
            finally:
                document.close()
            return preview_path, None, "generated"
        except Exception as exc:
            preview_path.unlink(missing_ok=True)
            errors.append("PyMuPDF: {0}".format(exc))
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    if errors:
        return None, "；".join(errors), "failed"
    return None, "{0} 未安装，未生成 PNG 预览".format("/".join(unavailable)), "unavailable"


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
