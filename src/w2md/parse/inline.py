"""Inline (run-level) content parsing."""

from ..ir.nodes import Bold, Color, Highlight, Image, Italic, Text, Underline
from ..opc.ns import A_NS, PIC_NS, R_NS, V_NS, W_NS, WP_NS


W = "{%s}" % W_NS
A = "{%s}" % A_NS
PIC = "{%s}" % PIC_NS
V = "{%s}" % V_NS
WP = "{%s}" % WP_NS
R = "{%s}" % R_NS


HIGHLIGHT_COLORS = {
    "black": "#000000",
    "blue": "#0000FF",
    "cyan": "#00FFFF",
    "darkBlue": "#000080",
    "darkCyan": "#008080",
    "darkGray": "#808080",
    "darkGreen": "#008000",
    "darkMagenta": "#800080",
    "darkRed": "#800000",
    "darkYellow": "#808000",
    "green": "#00FF00",
    "lightGray": "#C0C0C0",
    "magenta": "#FF00FF",
    "red": "#FF0000",
    "white": "#FFFFFF",
    "yellow": "#FFFF00",
}


def _is_on(el):
    val = el.get(W + "val")
    return val is None or val not in ("0", "false", "off", "none")


def parse_paragraph_runs(p_el, rels=None):
    children = []
    for node in p_el:
        if node.tag == W + "r":
            children.extend(_parse_run(node, rels))
        elif node.tag == W + "hyperlink":
            for sub in node.findall(W + "r"):
                children.extend(_parse_run(sub, rels))
    return children or [Text("")]


def _parse_run(r_el, rels):
    rpr = r_el.find(W + "rPr")
    bold = False
    italic = False
    underline = False
    color = None
    highlight = None
    if rpr is not None:
        b = rpr.find(W + "b")
        bold = b is not None and _is_on(b)
        i = rpr.find(W + "i")
        italic = i is not None and _is_on(i)
        u = rpr.find(W + "u")
        underline = u is not None and _is_on(u)
        c = rpr.find(W + "color")
        if c is not None:
            value = c.get(W + "val")
            if value and value != "auto":
                color = value if value.startswith("#") else "#" + value
        h = rpr.find(W + "highlight")
        if h is not None:
            value = h.get(W + "val")
            if value and value != "none":
                highlight = HIGHLIGHT_COLORS.get(value, "#FFFF00")

    texts = []
    for node in r_el:
        if node.tag == W + "t":
            texts.append(node.text or "")
        elif node.tag == W + "tab":
            texts.append("\t")
        elif node.tag == W + "br":
            texts.append(" ")

    text = "".join(texts)
    nodes = []
    if text:
        node = Text(text)
        if underline:
            node = Underline([node])
        if color:
            node = Color(color, [node])
        if highlight:
            node = Highlight(highlight, [node])
        if italic:
            node = Italic([node])
        if bold:
            node = Bold([node])
        nodes.append(node)

    for image in _run_images(r_el, rels):
        nodes.append(image)
    return nodes


def _run_images(r_el, rels):
    images = []
    alt = _image_alt(r_el)
    for blip in r_el.iter(A + "blip"):
        rid = blip.get(R + "embed")
        if rid and rels and rid in rels:
            images.append(Image(source=rels[rid], alt=alt))
    for imagedata in r_el.iter(V + "imagedata"):
        rid = imagedata.get(R + "id")
        if rid and rels and rid in rels:
            images.append(Image(source=rels[rid], alt=alt))
    return images


def _image_alt(r_el):
    for tag in (WP + "docPr", PIC + "cNvPr"):
        for el in r_el.iter(tag):
            descr = el.get("descr") or el.get("title")
            if descr:
                return descr
    return ""
