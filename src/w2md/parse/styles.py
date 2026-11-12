"""Style table parsing: map paragraph style ids to heading levels.

Resolution follows Word's own semantics:

* ``w:outlineLvl`` is inherited through ``w:basedOn``
* a style name such as ``heading 2`` / ``标题 2`` / ``二级标题`` is a fallback
* font size and bold are inherited through ``w:basedOn`` and
  ``w:docDefaults`` for the last-resort visual heuristic
"""

import re

from ..opc.ns import W_NS


W = "{%s}" % W_NS

_CHINESE_NUMBERS = "一二三四五六七八九"


def _name_heading_level(name):
    if not name:
        return None
    name = name.strip()

    match = re.match(r"^(?:heading|标题|h)\s*([1-9])$", name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    match = re.match(r"^(?:heading|标题|h)\s*([一二三四五六七八九])$", name, re.IGNORECASE)
    if match:
        return _CHINESE_NUMBERS.index(match.group(1)) + 1

    match = re.match(r"^([一二三四五六七八九1-9])\s*级\s*标题$", name)
    if match:
        digit = match.group(1)
        return _CHINESE_NUMBERS.index(digit) + 1 if digit in _CHINESE_NUMBERS else int(digit)

    return None


def _int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_on(element):
    value = element.get(W + "val")
    return value is None or value not in ("0", "false", "off", "none")


def _based_on(style):
    if style is None:
        return None
    based_on = style.find(W + "basedOn")
    return based_on.get(W + "val") if based_on is not None else None


class StyleTable:
    def __init__(self):
        self._by_id = {}
        self._name = {}
        self._doc_default_size = None
        self._doc_default_bold = None

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

        defaults = root.find(W + "docDefaults")
        if defaults is not None:
            rpr_default = defaults.find(W + "rPrDefault")
            if rpr_default is not None:
                rpr = rpr_default.find(W + "rPr")
                if rpr is not None:
                    size = rpr.find(W + "sz")
                    if size is not None:
                        table._doc_default_size = _int(size.get(W + "val"))
                    bold = rpr.find(W + "b")
                    if bold is not None:
                        table._doc_default_bold = _is_on(bold)
        return table

    def style_name(self, style_id):
        return self._name.get(style_id, "")

    def outline_level(self, style_id):
        """Return the raw ``w:outlineLvl`` value (0-9) inherited from basedOn."""

        seen = set()
        current = style_id
        while current and current not in seen:
            seen.add(current)
            style = self._by_id.get(current)
            if style is None:
                return None
            ppr = style.find(W + "pPr")
            if ppr is not None:
                outline = ppr.find(W + "outlineLvl")
                if outline is not None:
                    value = _int(outline.get(W + "val"))
                    if value is not None:
                        return value
            current = _based_on(style)
        return None

    def name_heading_level(self, style_id):
        """Return a 1-based heading level implied by the style name chain."""

        seen = set()
        current = style_id
        while current and current not in seen:
            seen.add(current)
            level = _name_heading_level(self._name.get(current, ""))
            if level is not None:
                return level
            style = self._by_id.get(current)
            current = _based_on(style)
        return None

    def font_size(self, style_id):
        """Return the style's font size in half-points, inherited via basedOn."""

        seen = set()
        current = style_id
        while current and current not in seen:
            seen.add(current)
            style = self._by_id.get(current)
            if style is None:
                break
            rpr = style.find(W + "rPr")
            if rpr is not None:
                size = rpr.find(W + "sz")
                if size is None:
                    size = rpr.find(W + "szCs")
                if size is not None:
                    value = _int(size.get(W + "val"))
                    if value is not None:
                        return value
            current = _based_on(style)
        return self._doc_default_size

    def bold(self, style_id):
        """Return the style's bold setting, inherited via basedOn."""

        seen = set()
        current = style_id
        while current and current not in seen:
            seen.add(current)
            style = self._by_id.get(current)
            if style is None:
                break
            rpr = style.find(W + "rPr")
            if rpr is not None:
                bold = rpr.find(W + "b")
                if bold is not None:
                    return _is_on(bold)
            current = _based_on(style)
        return self._doc_default_bold

    def num_pr(self, style_id):
        """Return ``(numId, ilvl)`` from the style's numPr, inherited via basedOn."""

        seen = set()
        current = style_id
        while current and current not in seen:
            seen.add(current)
            style = self._by_id.get(current)
            if style is None:
                break
            ppr = style.find(W + "pPr")
            if ppr is not None:
                num_pr = ppr.find(W + "numPr")
                if num_pr is not None:
                    num_id = None
                    ilvl = None
                    num_id_el = num_pr.find(W + "numId")
                    if num_id_el is not None:
                        num_id = num_id_el.get(W + "val")
                    ilvl_el = num_pr.find(W + "ilvl")
                    if ilvl_el is not None:
                        ilvl = ilvl_el.get(W + "val")
                    if num_id is not None or ilvl is not None:
                        return num_id, ilvl
            current = _based_on(style)
        return None, None

    def default_font_size(self):
        return self._doc_default_size or self.font_size("Normal") or 21

    def default_bold(self):
        value = self._doc_default_bold
        if value is None:
            value = self.bold("Normal")
        return bool(value)

    def heading_level(self, style_id):
        """Backward-compatible resolver: outline first, then style name."""

        if not style_id:
            return None
        outline = self.outline_level(style_id)
        if outline is not None:
            if outline >= 9:
                return None
            return outline + 1
        return self.name_heading_level(style_id)
