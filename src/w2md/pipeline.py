"""End-to-end conversion pipeline."""

import base64
import json
import mimetypes
from pathlib import Path

from .config import Config
from .image_extract import extract_images_from_package, unmatched_placeholder
from .ir.nodes import (
    Bold,
    Color,
    Heading,
    Highlight,
    Image,
    Italic,
    Paragraph,
    Table,
    Text,
    Underline,
)
from .opc.package import (
    DOCUMENT_PART,
    DOCUMENT_RELS_PART,
    NUMBERING_PART,
    STYLES_PART,
    OpcPackage,
)
from .parse.document import parse_document
from .parse.numbering import NumberingTable
from .parse.styles import StyleTable
from .render.markdown import render
from .report import Report


_UNSUPPORTED_IMAGE_EXTS = {".emf", ".wmf"}


def convert(source, output_dir, config=None, basename=None):
    config = config or Config()
    source = Path(source)
    output_dir = Path(output_dir)
    stem = _safe_stem(basename) if basename else source.stem
    report = Report(source=str(source.name))

    with OpcPackage(source) as package:
        styles = None
        if package.has_part(STYLES_PART):
            styles = StyleTable.from_xml(package.read_xml(STYLES_PART))
        else:
            report.add("missing_styles", STYLES_PART, "文档没有样式表，标题将按正文处理")

        if not package.has_part(DOCUMENT_PART):
            report.status = "error"
            report.add("missing_document", DOCUMENT_PART, "找不到文档主体", level="error")
            report.finalize()
            return report, None

        rels = package.read_document_relationships() if package.has_part(DOCUMENT_RELS_PART) else {}
        doc_root = package.read_xml(DOCUMENT_PART)
        numbering = None
        if package.has_part(NUMBERING_PART):
            numbering = NumberingTable.from_xml(package.read_xml(NUMBERING_PART))

        extraction = None
        if config.assets_mode == "placeholder":
            try:
                extraction = extract_images_from_package(
                    package,
                    output_dir,
                    doc_root=doc_root,
                    stem=stem,
                    report=report,
                    generate_previews=config.image_previews,
                )
            except Exception as exc:
                report.add(
                    "image_extract_failed",
                    "图片",
                    "图片提取失败，Markdown 将写入 UNMATCHED 占位符：{0}".format(exc),
                    level="error",
                )

        document = parse_document(doc_root, styles, report, rels=rels, numbering=numbering)

        if config.assets_mode == "placeholder":
            replaced_count = _replace_images_with_placeholders(document, extraction, report)
            image_count = len(extraction.occurrences) if extraction is not None else replaced_count
            image_bytes = 0
            if extraction is not None:
                report.stats.update(
                    {
                        "image_occurrences": extraction.summary.get("occurrences", image_count),
                        "image_unique_media": extraction.summary.get("unique_media", 0),
                        "image_duplicates": extraction.summary.get("duplicates", 0),
                        "image_failed": extraction.summary.get("failed", 0),
                        "image_compatibility": extraction.summary.get("compatibility", 0),
                        "image_placeholders": replaced_count,
                        "image_manifest": "assets/manifest.json",
                    }
                )
            if image_count:
                report.add(
                    "image_placeholder",
                    "图片",
                    "已按正文顺序生成 {0} 个 ShowDoc 图片占位符：{1}".format(
                        image_count, _example_placeholders(extraction)
                    ),
                )
        else:
            image_count, image_bytes = _extract_images(document, package, stem, output_dir, report, config.assets_mode)
        markdown = render(
            document,
            heading_offset=config.heading_offset,
            inline_style=config.inline_style,
        )

        if config.heading_offset:
            shifted = [
                block
                for block in document.blocks
                if isinstance(block, Heading)
                and block.level <= 6
                and block.level + config.heading_offset > 6
            ]
            if shifted:
                report.add(
                    "heading_downgraded",
                    "标题",
                    "heading-offset 使 {0} 个标题超过 Markdown 六级，已降级为 H6".format(
                        len(shifted)
                    ),
                )
            for heading in report.headings:
                heading["level"] = max(
                    1, min(6, heading["original_level"] + config.heading_offset)
                )

        if config.inline_style == "drop":
            dropped = _count_dropped_styles(document)
            if any(dropped.values()):
                report.add(
                    "style_dropped",
                    "正文",
                    "为兼容多平台，未保留 {0} 处颜色、{1} 处高亮、{2} 处下划线样式".format(
                        dropped["colors"],
                        dropped["highlights"],
                        dropped["underlines"],
                    ),
                )

        report.stats.update(
            {
                "lines": len(markdown.splitlines()),
                "chars": _text_char_count(document),
                "headings": sum(1 for b in document.blocks if isinstance(b, Heading)),
                "paragraphs": sum(1 for b in document.blocks if isinstance(b, Paragraph)),
                "tables": sum(1 for b in document.blocks if isinstance(b, Table)),
                "images": image_count,
            }
        )
        if image_bytes:
            report.stats["image_bytes"] = image_bytes
        report.finalize()

    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / (stem + ".md")
    md_path.write_text(markdown, encoding="utf-8")

    report_path = output_dir / (stem + ".report.json")
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    return report, md_path


def _extract_images(document, package, stem, output_dir, report, assets_mode):
    assets_dir = output_dir / (stem + ".assets")
    assigned = {}
    counter = 0
    total_bytes = 0

    for image in _iter_images(document):
        part = _media_part(image.source)
        if part in assigned:
            image.src = assigned[part]
            continue
        if not package.has_part(part):
            report.add("image_missing", "图片", "找不到图片文件 {0}".format(part))
            continue
        ext = Path(part).suffix.lower()
        if ext in _UNSUPPORTED_IMAGE_EXTS:
            report.add("image_format", "图片", "图片格式 {0} 在浏览器中通常无法显示".format(ext))
        data = package.read_part(part)

        if assets_mode == "base64":
            mime = mimetypes.guess_type(part)[0] or "application/octet-stream"
            src = "data:{0};base64,{1}".format(mime, base64.b64encode(data).decode("ascii"))
        else:
            counter += 1
            name = "img-{0:03d}{1}".format(counter, ext)
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / name).write_bytes(data)
            src = stem + ".assets/" + name

        assigned[part] = src
        image.src = src
        total_bytes += len(data)

    return len(assigned), total_bytes


def _iter_images(document):
    for block in document.blocks:
        if isinstance(block, (Heading, Paragraph)):
            yield from _iter_images_in(block.children)
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row:
                    yield from _iter_images_in(cell)


def _iter_images_in(nodes):
    for node in nodes:
        if isinstance(node, Image):
            yield node
        elif isinstance(node, (Bold, Italic, Color, Highlight, Underline)):
            yield from _iter_images_in(node.children)


def _replace_images_with_placeholders(document, extraction, report):
    placeholders = extraction.placeholders if extraction is not None else []
    used = set()
    next_unused = [0]
    unmatched = [0]

    def take_placeholder(image):
        candidate = getattr(image, "placeholder", "") or ""
        if candidate and candidate not in used:
            used.add(candidate)
            return candidate

        while next_unused[0] < len(placeholders):
            candidate = placeholders[next_unused[0]]
            next_unused[0] += 1
            if candidate not in used:
                used.add(candidate)
                return candidate

        unmatched[0] += 1
        return unmatched_placeholder(unmatched[0])

    def is_placeholder(node):
        return isinstance(node, Text) and node.text.startswith("{{SHOWDOC_IMAGE_")

    def transform(nodes):
        result = []
        for node in nodes:
            if isinstance(node, Image):
                result.append(Text(take_placeholder(node)))
            elif isinstance(node, (Bold, Italic, Color, Highlight, Underline)):
                node.children = transform(node.children)
                if node.children and all(is_placeholder(child) for child in node.children):
                    result.extend(node.children)
                else:
                    result.append(node)
            else:
                result.append(node)
        return result

    for block in document.blocks:
        if isinstance(block, (Heading, Paragraph)):
            block.children = transform(block.children)
        elif isinstance(block, Table):
            for index, row in enumerate(block.rows):
                block.rows[index] = [transform(cell) for cell in row]

    unplaced = [placeholder for placeholder in placeholders if placeholder not in used]
    if unmatched[0]:
        report.add(
            "image_placeholder_missing",
            "图片",
            "{0} 张图片没有对应的占位符，已写入 UNMATCHED 占位符".format(unmatched[0]),
            level="error",
        )
    if unplaced:
        preview = "、".join(unplaced[:10])
        more = " 等 {0} 个".format(len(unplaced)) if len(unplaced) > 10 else ""
        report.add(
            "image_placeholder_unplaced",
            "图片",
            "以下已提取图片的占位符未出现在 Markdown 中（可能位于文本框等未解析结构）：{0}{1}".format(
                preview, more
            ),
        )

    return len(used)


def _example_placeholders(extraction):
    if extraction is None or not extraction.occurrences:
        return ""
    examples = extraction.placeholders[:3]
    if len(extraction.occurrences) > len(examples):
        examples.append("…")
    return "、".join(examples)


def _media_part(target):
    target = target.replace("\\", "/").lstrip("/")
    if target.startswith("word/"):
        return target
    return "word/" + target


def _safe_stem(name):
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    return cleaned.strip("._") or "document"


def _count_dropped_styles(document):
    counts = {"colors": 0, "highlights": 0, "underlines": 0}

    def walk(nodes):
        for node in nodes:
            if isinstance(node, Color):
                counts["colors"] += 1
                walk(node.children)
            elif isinstance(node, Highlight):
                counts["highlights"] += 1
                walk(node.children)
            elif isinstance(node, Underline):
                counts["underlines"] += 1
                walk(node.children)
            elif isinstance(node, (Bold, Italic)):
                walk(node.children)

    for block in document.blocks:
        if isinstance(block, (Heading, Paragraph)):
            walk(block.children)
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row:
                    walk(cell)
    return counts


def _text_char_count(document):
    total = 0

    def walk(nodes):
        nonlocal total
        for node in nodes:
            if isinstance(node, Text):
                total += sum(1 for ch in node.text if not ch.isspace())
            elif isinstance(node, (Bold, Italic, Color, Highlight, Underline)):
                walk(node.children)

    for block in document.blocks:
        if isinstance(block, (Heading, Paragraph)):
            walk(block.children)
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row:
                    walk(cell)
    return total
