"""IR to Markdown rendering."""

import html as html_module

from ..ir.nodes import (
    Bold,
    Color,
    Heading,
    Highlight,
    Image,
    Italic,
    LineBreak,
    Paragraph,
    Table,
    Text,
    Underline,
)
from .escape import escape_text


def render(document, heading_offset=0, inline_style="drop"):
    normalized = [_normalize_block(block) for block in document.blocks]
    parts = [_render_block(block, heading_offset, inline_style) for block in normalized]
    return "\n\n".join(part for part in parts if part) + "\n"


def _normalize_block(block):
    if isinstance(block, (Heading, Paragraph)):
        block.children = merge_inlines(block.children)
    elif isinstance(block, Table):
        for row in block.rows:
            for index, cell in enumerate(row):
                row[index] = merge_inlines(cell)
    return block


def merge_inlines(nodes):
    result = []
    for node in nodes:
        if isinstance(node, Text):
            if result and isinstance(result[-1], Text):
                result[-1].text += node.text
                continue
            result.append(node)
            continue
        if isinstance(node, (Bold, Italic, Underline, Color, Highlight)):
            node.children = merge_inlines(node.children)
            key = _style_key(node)
            previous = result[-1] if result else None
            if key is not None and previous is not None and _style_key(previous) == key:
                previous.children = merge_inlines(previous.children + node.children)
                continue
        result.append(node)
    return result


def _style_key(node):
    if isinstance(node, Bold):
        return ("bold",)
    if isinstance(node, Italic):
        return ("italic",)
    if isinstance(node, Underline):
        return ("underline",)
    if isinstance(node, Color):
        return ("color", node.color)
    if isinstance(node, Highlight):
        return ("highlight", node.color)
    return None


def _render_block(block, heading_offset, inline_style):
    if isinstance(block, Heading):
        level = max(1, min(6, block.level + heading_offset))
        return "#" * level + " " + _render_inlines(block.children, inline_style)
    if isinstance(block, Paragraph):
        return _render_inlines(block.children, inline_style)
    if isinstance(block, Table):
        return _render_table(block, inline_style)
    return ""


def _render_inlines(children, inline_style):
    return "".join(_render_inline(child, inline_style) for child in children)


def _render_table(table, inline_style):
    lines = []
    for row_index, row in enumerate(table.rows):
        cells = [_render_cell(cell, inline_style) for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
        if row_index == 0:
            lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return "\n".join(lines)


def _render_cell(cell, inline_style):
    text = "".join(_render_inline(child, inline_style) for child in cell)
    return text.replace("|", "\\|")


def _render_inline(node, inline_style):
    if isinstance(node, Image):
        if not node.src:
            return ""
        return "![{0}]({1})".format(_escape_alt(node.alt), node.src)
    if inline_style == "html" and _needs_html(node):
        return _render_html(node)
    return _render_md(node)


def _render_md(node):
    if isinstance(node, Text):
        return escape_text(node.text)
    if isinstance(node, Bold):
        return "**" + "".join(_render_md(child) for child in node.children) + "**"
    if isinstance(node, Italic):
        return "*" + "".join(_render_md(child) for child in node.children) + "*"
    if isinstance(node, (Color, Highlight, Underline)):
        return "".join(_render_md(child) for child in node.children)
    if isinstance(node, LineBreak):
        return "<br>"
    return ""


def _needs_html(node):
    if isinstance(node, (Color, Highlight, Underline, LineBreak)):
        return True
    if isinstance(node, (Bold, Italic)):
        return any(_needs_html(child) for child in node.children)
    return False


def _render_html(node):
    if isinstance(node, Text):
        return html_module.escape(node.text)
    if isinstance(node, Bold):
        return "<strong>" + _render_html_children(node.children) + "</strong>"
    if isinstance(node, Italic):
        return "<em>" + _render_html_children(node.children) + "</em>"
    if isinstance(node, Underline):
        return "<u>" + _render_html_children(node.children) + "</u>"
    if isinstance(node, Color):
        return '<span style="color:{0}">'.format(node.color) + _render_html_children(node.children) + "</span>"
    if isinstance(node, Highlight):
        return '<mark style="background-color:{0}">'.format(node.color) + _render_html_children(node.children) + "</mark>"
    if isinstance(node, LineBreak):
        return "<br>"
    return ""


def _render_html_children(children):
    return "".join(_render_html(child) for child in children)


def _escape_alt(alt):
    return alt.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
