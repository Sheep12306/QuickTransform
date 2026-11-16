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

NBSP = "\u00a0"
INDENT = "\u3000"
MAX_INDENT = 6
# Two Word indents closer than this belong to the same visual list level.
INDENT_CLUSTER_TWIPS = 100

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


class _IndentLayout:
    """Translate Word left indents (twips) into Markdown indent depth.

    Chinese Word documents often keep every list level at ``ilvl=0`` and
    express nesting purely through ``w:ind`` (425, 630, 840, ... twips).
    Ranking the indents that actually occur in the document recovers the
    visual hierarchy that ``ilvl`` alone cannot provide.
    """

    def __init__(self, body, resolver):
        self._resolver = resolver
        values = set()
        for p_el in body:
            if p_el.tag != W + "p":
                continue
            text = _paragraph_text(p_el)
            num_id, ilvl = resolver.numbering_ids(p_el)
            numbered = num_id not in (None, "", "0")
            if not numbered and not _EXISTING_PREFIX.match(text):
                continue
            left = _effective_left(p_el, resolver, num_id, ilvl)
            if left:
                values.add(left)
        self._ranges = _cluster_indents(sorted(values))

    def depth(self, p_el, num_id, ilvl):
        left = _effective_left(p_el, self._resolver, num_id, ilvl)
        if left:
            for depth, (low, high) in enumerate(self._ranges):
                if low <= left <= high:
                    return min(depth, MAX_INDENT)
            return min(len(self._ranges), MAX_INDENT)
        try:
            level = int(ilvl)
        except (TypeError, ValueError):
            level = 0
        return min(max(level, 0), MAX_INDENT)


def _cluster_indents(values):
    ranges = []
    for value in values:
        if not ranges or value - ranges[-1][1] > INDENT_CLUSTER_TWIPS:
            ranges.append((value, value))
        else:
            ranges[-1] = (ranges[-1][0], value)
    return ranges


def _paragraph_text(p_el):
    parts = []
    for element in p_el.iter():
        if element.tag == W + "t":
            parts.append(element.text or "")
        elif element.tag == W + "tab":
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _paragraph_left(p_el):
    ppr = p_el.find(W + "pPr")
    if ppr is None:
        return None
    ind = ppr.find(W + "ind")
    if ind is None:
        return None
    return _to_int(ind.get(W + "left") or ind.get(W + "start"))


def _effective_left(p_el, resolver, num_id, ilvl):
    left = _paragraph_left(p_el)
    if left is None and num_id not in (None, "", "0"):
        numbering = getattr(resolver, "numbering", None)
        if numbering is not None:
            level = numbering.level(num_id, ilvl) or {}
            left = level.get("left")
    return left


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_document(doc_root, styles, report, rels=None, numbering=None):
    body = doc_root.find(W + "body")
    if body is None:
        return Document()

    resolver = HeadingResolver(doc_root, styles, numbering)
    state = NumberingState(numbering)
    layout = _IndentLayout(body, resolver)
    blocks = []
    for child in body:
        if child.tag == W + "p":
            blocks.extend(_parse_paragraph(child, rels, resolver, report, state, layout))
        elif child.tag == W + "tbl":
            blocks.append(parse_table(child, rels))
        elif child.tag == W + "altChunk" and child.get(IMAGE_PLACEHOLDER_ATTR):
            blocks.append(Paragraph([Text(child.get(IMAGE_PLACEHOLDER_ATTR))]))
    return Document(blocks=blocks)


def _parse_paragraph(p_el, rels, resolver, report, state, layout):
    match = resolver.resolve(p_el)
    children = inline.parse_paragraph_runs(p_el, rels)
    is_heading = match is not None and match.level > 0

    text = _inline_text(children)
    if text and _EXISTING_PREFIX.match(text):
        # Typed list markers often come with literal leading spaces; drop them
        # so the line cannot turn into a Markdown code block.
        _strip_leading_space(children)

    prefix = _numbering_prefix(p_el, resolver, state, children, is_heading, layout)
    if prefix:
        _strip_leading_space(children)
        children = [Text(prefix)] + children

    if not is_heading:
        if match is not None:
            _report_conflicts(match, _inline_text(children), report)
        return [Paragraph(children)]

    text = _inline_text(children)
    _report_heading(match, text, report)
    return [Heading(level=match.level, children=children)]


def _strip_leading_space(nodes):
    for node in nodes:
        if isinstance(node, Text):
            node.text = node.text.lstrip()
            return True
        if isinstance(node, (Bold, Italic, Color, Highlight, Underline)):
            if _strip_leading_space(node.children):
                return True
            continue
        return False
    return False


def _numbering_prefix(p_el, resolver, state, children, is_heading, layout):
    text = _inline_text(children)
    num_id, ilvl = resolver.numbering_ids(p_el)
    has_prefix = bool(text) and _EXISTING_PREFIX.match(text) is not None

    label = None
    if state is not None and state.table is not None and num_id not in (None, ""):
        # Ask for the label even when it is not printed: Word advances the
        # counter for every numbered paragraph, including empty ones, so this
        # keeps later labels aligned with what Word displays.
        label = state.label(num_id, ilvl)

    if is_heading:
        return label + " " if label and not has_prefix else ""
    if not text:
        return ""

    depth = layout.depth(p_el, num_id, ilvl) if layout is not None else 0
    indent = INDENT * depth

    if label and not has_prefix:
        # NBSP after the label prevents Markdown from renumbering ordered
        # lists, so the number Word showed is preserved.
        return indent + label + NBSP
    if label or has_prefix:
        return indent
    return ""


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
