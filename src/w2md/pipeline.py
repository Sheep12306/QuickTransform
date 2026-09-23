"""End-to-end conversion pipeline."""

import base64
import json
import mimetypes
from pathlib import Path

from .config import Config
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
from .opc.package import DOCUMENT_PART, DOCUMENT_RELS_PART, STYLES_PART, OpcPackage
from .parse.document import parse_document
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
        document = parse_document(doc_root, styles, report, rels=rels)

        if config.assets_mode == "placeholder":
            image_count = _replace_images_with_placeholders(document)
            image_bytes = 0
            if image_count:
                report.add("image_placeholder", "图片", "已用占位符替换 {0} 张图片，请按位置手动插入".format(image_count))
        else:
            image_count, image_bytes = _extract_images(document, package, stem, output_dir, report, config.assets_mode)
        markdown = render(
            document,
            heading_offset=config.heading_offset,
            inline_style=config.inline_style,
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


def _replace_images_with_placeholders(document):
    counter = [0]

    def transform(nodes):
        result = []
        for node in nodes:
            if isinstance(node, Image):
                counter[0] += 1
                label = node.alt or "图片"
                result.append(Bold([Text("图片占位 {0}：{1}".format(counter[0], label))]))
            elif isinstance(node, (Bold, Italic, Color, Highlight, Underline)):
                node.children = transform(node.children)
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
    return counter[0]


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
