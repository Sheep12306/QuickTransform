"""Word document.xml traversal: paragraphs and headings to IR blocks."""

from ..ir.nodes import (
    Bold,
    Color,
    Document,
    Heading,
    Highlight,
    Italic,
    LineBreak,
    Paragraph,
    Text,
    Underline,
)
from ..opc.ns import W_NS
from . import inline
from .headings import HeadingResolver
from .tables import parse_table


W = "{%s}" % W_NS


def parse_document(doc_root, styles, report, rels=None, numbering=None):
    body = doc_root.find(W + "body")
    if body is None:
        return Document()

    resolver = HeadingResolver(doc_root, styles, numbering)
    blocks = []
    for child in body:
        if child.tag == W + "p":
            blocks.extend(_parse_paragraph(child, rels, resolver, report))
        elif child.tag == W + "tbl":
            blocks.append(parse_table(child, rels))
    return Document(blocks=blocks)


def _parse_paragraph(p_el, rels, resolver, report):
    match = resolver.resolve(p_el)
    children = inline.parse_paragraph_runs(p_el, rels)

    if match is None or match.level <= 0:
        if match is not None:
            _report_conflicts(match, _inline_text(children), report)
        return [Paragraph(children)]

    text = _inline_text(children)
    _report_heading(match, text, report)
    return [Heading(level=match.level, children=children)]


def _report_heading(match, text, report):
    if report is None:
        return
    downgraded = match.level > 6
    report.add_heading(
        level=min(match.level, 6),
        original_level=match.level,
        text=text,
        source=match.source,
        detail=match.detail,
        downgraded=downgraded,
    )
    _report_conflicts(match, text, report)
    if match.source == "font":
        report.add(
            "heading_font_fallback",
            "标题",
            "「{0}」没有大纲级别、标题样式或编号，按字号+加粗识别为 H{1}".format(
                text, match.level
            ),
        )
    if downgraded:
        report.add(
            "heading_downgraded",
            "标题",
            "「{0}」原始级别 H{1} 超过 Markdown 六级，降级为 H6 并保留〔H{1}〕标记".format(
                text, match.level
            ),
        )


def _report_conflicts(match, text, report):
    if report is None:
        return
    for conflict in match.conflicts:
        report.add("heading_conflict", "标题", "「{0}」{1}".format(text, conflict))


def _inline_text(nodes):
    parts = []
    for node in nodes:
        if isinstance(node, Text):
            parts.append(node.text)
        elif isinstance(node, (Bold, Italic, Underline, Color, Highlight)):
            parts.append(_inline_text(node.children))
        elif isinstance(node, LineBreak):
            parts.append(" ")
    return "".join(parts).strip()
