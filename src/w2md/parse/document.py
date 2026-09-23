"""Word document.xml traversal: paragraphs and headings to IR blocks."""

from ..ir.nodes import Document, Heading, Paragraph
from ..opc.ns import W_NS
from . import inline
from .tables import parse_table


W = "{%s}" % W_NS


def parse_document(doc_root, styles, report, rels=None):
    body = doc_root.find(W + "body")
    if body is None:
        return Document()

    blocks = []
    for child in body:
        if child.tag == W + "p":
            blocks.extend(_parse_paragraph(child, styles, rels))
        elif child.tag == W + "tbl":
            blocks.append(parse_table(child))
    return Document(blocks=blocks)


def _parse_paragraph(p_el, styles, rels):
    style_id = None
    ppr = p_el.find(W + "pPr")
    if ppr is not None:
        style_el = ppr.find(W + "pStyle")
        if style_el is not None:
            style_id = style_el.get(W + "val")

    level = styles.heading_level(style_id) if styles is not None else None
    children = inline.parse_paragraph_runs(p_el, rels)

    if level is not None:
        if level > 6:
            return [Paragraph(children)]
        return [Heading(level=level, children=children)]
    return [Paragraph(children)]
