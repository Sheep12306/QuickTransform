"""Word document.xml traversal: paragraphs and headings to IR blocks."""

import re

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
from ..opc.ns import IMAGE_PLACEHOLDER_ATTR, W_NS
from . import inline
from .headings import HeadingResolver
from .numbering import NumberingState
from .tables import parse_table


W = "{%s}" % W_NS

# Text that already carries a typed number / bullet must not get a second
# automatic prefix.
_EXISTING_PREFIX = re.compile(
    r"^\s*(?:"
    r"\d+(?:[.．]\d+)*[.．、)）]"
    r"|[（(]\d+[)）]"
    r"|[一二三四五六七八九十百]+[、.．]"
    r"|[\-•●○■□◆◇▪➢✓]"
    r")\s*"
)


def parse_document(doc_root, styles, report, rels=None, numbering=None):
    body = doc_root.find(W + "body")
    if body is None:
        return Document()

    resolver = HeadingResolver(doc_root, styles, numbering)
    state = NumberingState(numbering)
    blocks = []
    for child in body:
        if child.tag == W + "p":
            blocks.extend(_parse_paragraph(child, rels, resolver, report, state))
        elif child.tag == W + "tbl":
            blocks.append(parse_table(child, rels))
        elif child.tag == W + "altChunk" and child.get(IMAGE_PLACEHOLDER_ATTR):
            blocks.append(Paragraph([Text(child.get(IMAGE_PLACEHOLDER_ATTR))]))
    return Document(blocks=blocks)


def _parse_paragraph(p_el, rels, resolver, report, state):
    match = resolver.resolve(p_el)
    children = inline.parse_paragraph_runs(p_el, rels)
    is_heading = match is not None and match.level > 0

    prefix = _numbering_prefix(p_el, resolver, state, children, is_heading)
    if prefix:
        children = [Text(prefix)] + children

    if not is_heading:
        if match is not None:
            _report_conflicts(match, _inline_text(children), report)
        return [Paragraph(children)]

    text = _inline_text(children)
    _report_heading(match, text, report)
    return [Heading(level=match.level, children=children)]


def _numbering_prefix(p_el, resolver, state, children, is_heading):
    if state is None or state.table is None:
        return ""
    text = _inline_text(children)
    if not text or _EXISTING_PREFIX.match(text):
        return ""

    num_id, ilvl = resolver.numbering_ids(p_el)
    label = state.label(num_id, ilvl)
    if not label:
        return ""

    if is_heading:
        return label + " "
    # Full-width indent keeps nested list levels visible without turning the
    # line into a Markdown code block.  NBSP after the label prevents Markdown
    # from renumbering ordered lists, so the number Word showed is preserved.
    indent = "　" * min(max(ilvl, 0), 4)
    return indent + label + " "


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
