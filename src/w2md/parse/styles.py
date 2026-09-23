"""Style table parsing: map paragraph style ids to heading levels."""

import re

from ..opc.ns import W_NS


W = "{%s}" % W_NS


def _name_heading_level(name):
    if not name:
        return None
    match = re.match(r"^(?:heading|标题)\s*([1-9])$", name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.match(r"^([一二三四五六七八九1-9])\s*级\s*标题$", name)
    if match:
        digit = match.group(1)
        chinese = "一二三四五六七八九"
        return chinese.index(digit) + 1 if digit in chinese else int(digit)
    return None


class StyleTable:
    def __init__(self):
        self._by_id = {}
        self._name = {}

    @classmethod
    def from_xml(cls, root):
        table = cls()
        for style in root.findall(W + "style"):
            style_id = style.get(W + "styleId")
            if not style_id:
                continue
            table._by_id[style_id] = style
            name_el = style.find(W + "name")
            table._name[style_id] = name_el.get(W + "val") if name_el is not None else ""
        return table

    def style_name(self, style_id):
        return self._name.get(style_id, "")

    def heading_level(self, style_id):
        """Resolve a 1-based heading level for a style id, or None."""
        if not style_id:
            return None
        outline = self._outline_level(style_id, set())
        if outline is not None:
            return outline + 1
        return _name_heading_level(self.style_name(style_id))

    def _outline_level(self, style_id, seen):
        if style_id in seen:
            return None
        seen.add(style_id)
        style = self._by_id.get(style_id)
        if style is None:
            return None
        ppr = style.find(W + "pPr")
        if ppr is not None:
            outline = ppr.find(W + "outlineLvl")
            if outline is not None:
                val = outline.get(W + "val")
                if val is not None:
                    try:
                        return int(val)
                    except ValueError:
                        return None
        based_on = style.find(W + "basedOn")
        if based_on is not None:
            parent = based_on.get(W + "val")
            if parent:
                return self._outline_level(parent, seen)
        return None

