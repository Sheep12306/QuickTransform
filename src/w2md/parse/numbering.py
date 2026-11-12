"""Minimal ``word/numbering.xml`` reader.

Only the information needed for heading-level fallback is kept: which abstract
numbering a ``w:num`` points at, and the number format / level text for each
``w:ilvl``.
"""

from ..opc.ns import W_NS


W = "{%s}" % W_NS

NON_HEADING_FORMATS = {"bullet", "none", "picture"}


class NumberingTable:
    def __init__(self, num_to_abstract=None, levels=None):
        self._num_to_abstract = num_to_abstract or {}
        self._levels = levels or {}

    @classmethod
    def from_xml(cls, root):
        levels = {}
        for abstract in root.findall(W + "abstractNum"):
            abstract_id = abstract.get(W + "abstractNumId")
            if abstract_id is None:
                continue
            level_map = {}
            for level in abstract.findall(W + "lvl"):
                ilvl = level.get(W + "ilvl")
                if ilvl is None:
                    continue
                num_format = ""
                format_el = level.find(W + "numFmt")
                if format_el is not None:
                    num_format = format_el.get(W + "val") or ""
                level_text = ""
                text_el = level.find(W + "lvlText")
                if text_el is not None:
                    level_text = text_el.get(W + "val") or ""
                level_map[str(ilvl)] = {
                    "format": num_format,
                    "text": level_text,
                }
            levels[str(abstract_id)] = level_map

        num_to_abstract = {}
        for num in root.findall(W + "num"):
            num_id = num.get(W + "numId")
            abstract = num.find(W + "abstractNumId")
            if num_id is None or abstract is None:
                continue
            num_to_abstract[str(num_id)] = str(abstract.get(W + "val") or "")

        return cls(num_to_abstract, levels)

    def level(self, num_id, ilvl):
        abstract_id = self._num_to_abstract.get(str(num_id))
        if abstract_id is None:
            return None
        return self._levels.get(abstract_id, {}).get(str(ilvl))

    def is_heading_numbering(self, num_id, ilvl):
        level = self.level(num_id, ilvl)
        if level is None:
            return False
        return (level.get("format") or "").lower() not in NON_HEADING_FORMATS
