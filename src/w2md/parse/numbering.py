"""Read ``word/numbering.xml`` and render paragraph / heading numbers.

Word stores automatic chapter, list and bullet numbering in ``numbering.xml``
instead of the paragraph text.  This module keeps the level definitions and a
per-``numId`` counter state so the converter can prepend the same labels Word
shows on screen:

* ``numFmt`` / ``lvlText`` / ``start`` / ``lvlOverride`` are honoured
* multi-level labels such as ``%1.%2`` are expanded per level
* bullet glyphs (including Wingdings/Symbol private-use characters) are mapped
  back to visible Unicode bullets
"""

from __future__ import annotations

import re

from ..opc.ns import W_NS


W = "{%s}" % W_NS

DEFAULT_START = 1
NON_HEADING_FORMATS = {"bullet", "none", "picture"}

_PERCENT = re.compile(r"%([1-9])")
_CHINESE_DIGITS = "零一二三四五六七八九"

# Wingdings / Symbol private-use bullets commonly written by Word.  Escapes
# are used for the keys because several private-use code points are invisible.
_BULLET_GLYPHS = {
    "": "●",  # ●
    "": "■",  # ■
    "": "◆",  # ◆
    "": "❖",  # ❖
    "": "◇",  # ◇
    "": "○",  # ○
    "": "○",  # ○
    "": "○",  # ○
    "": "▪",  # ▪
    "": "□",  # □
    "": "•",  # •
    "": "•",  # •
    "": "•",  # •
    "": "➢",  # ➢
    "": "➢",  # ➢
    "": "➢",  # ➢
    "": "✓",  # ✓
    "": "◆",  # ◆
    "·": "•",  # ·
}

_ROMAN_VALUES = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _level_from_xml(level):
    ilvl = level.get(W + "ilvl")
    if ilvl is None:
        return None

    num_format = ""
    format_el = level.find(W + "numFmt")
    if format_el is not None:
        num_format = format_el.get(W + "val") or ""

    level_text = ""
    text_el = level.find(W + "lvlText")
    if text_el is not None:
        level_text = text_el.get(W + "val") or ""

    start = DEFAULT_START
    start_el = level.find(W + "start")
    if start_el is not None:
        start = _int(start_el.get(W + "val"), DEFAULT_START)

    restart = None
    restart_el = level.find(W + "lvlRestart")
    if restart_el is not None:
        restart = _int(restart_el.get(W + "val"))

    suff = "tab"
    suff_el = level.find(W + "suff")
    if suff_el is not None:
        suff = suff_el.get(W + "val") or "tab"

    pstyle = None
    pstyle_el = level.find(W + "pStyle")
    if pstyle_el is not None:
        pstyle = pstyle_el.get(W + "val")

    # A numbering level often carries its own left indent; paragraphs that
    # rely on it have no ``w:ind`` of their own, so keep it for layout.
    left = None
    ppr_el = level.find(W + "pPr")
    if ppr_el is not None:
        ind_el = ppr_el.find(W + "ind")
        if ind_el is not None:
            left = _int(ind_el.get(W + "left") or ind_el.get(W + "start"))

    return {
        "ilvl": _int(ilvl, 0),
        "format": num_format,
        "text": level_text,
        "start": start,
        "restart": restart,
        "suff": suff,
        "pstyle": pstyle,
        "left": left,
    }


class NumberingTable:
    def __init__(self, num_to_abstract=None, levels=None, overrides=None):
        self._num_to_abstract = num_to_abstract or {}
        self._levels = levels or {}
        self._overrides = overrides or {}
        self._style_numbers = {}

    @classmethod
    def from_xml(cls, root, styles=None):
        levels = {}
        style_links = {}
        for abstract in root.findall(W + "abstractNum"):
            abstract_id = abstract.get(W + "abstractNumId")
            if abstract_id is None:
                continue
            level_map = {}
            for level in abstract.findall(W + "lvl"):
                parsed = _level_from_xml(level)
                if parsed is not None:
                    level_map[str(parsed["ilvl"])] = parsed
            levels[str(abstract_id)] = level_map
            link = abstract.find(W + "numStyleLink")
            if link is not None and link.get(W + "val"):
                style_links[str(abstract_id)] = link.get(W + "val")

        num_to_abstract = {}
        overrides = {}
        for num in root.findall(W + "num"):
            num_id = num.get(W + "numId")
            abstract = num.find(W + "abstractNumId")
            if num_id is None or abstract is None:
                continue
            num_id = str(num_id)
            num_to_abstract[num_id] = str(abstract.get(W + "val") or "")

            level_overrides = {}
            for override in num.findall(W + "lvlOverride"):
                ilvl = _int(override.get(W + "ilvl"))
                if ilvl is None:
                    continue
                entry = {}
                start_override = override.find(W + "startOverride")
                if start_override is not None:
                    start = _int(start_override.get(W + "val"))
                    if start is not None:
                        entry["start"] = start
                level_el = override.find(W + "lvl")
                if level_el is not None:
                    parsed = _level_from_xml(level_el)
                    if parsed is not None:
                        entry.update(parsed)
                if entry:
                    level_overrides[str(ilvl)] = entry
            if level_overrides:
                overrides[num_id] = level_overrides

        # ``numStyleLink`` points at a numbering style whose numPr names the
        # concrete numbering definition to reuse.
        if styles is not None:
            for abstract_id, style_id in style_links.items():
                linked_num_id, _ilvl = styles.num_pr(style_id)
                if not linked_num_id:
                    continue
                target = num_to_abstract.get(str(linked_num_id))
                if target in levels:
                    levels[abstract_id] = levels[target]

        table = cls(num_to_abstract, levels, overrides)
        # A numbering level can be linked to a paragraph style via ``w:pStyle``;
        # applying that style then activates the number even when the paragraph
        # and style carry no numPr of their own.
        for num_id, abstract_id in num_to_abstract.items():
            for ilvl, info in levels.get(abstract_id, {}).items():
                style_id = info.get("pstyle")
                if style_id and style_id not in table._style_numbers:
                    table._style_numbers[style_id] = (num_id, _int(ilvl, 0))
        return table

    def num_for_style(self, style_id):
        """Return ``(numId, ilvl)`` linked to a paragraph style, if any."""

        return self._style_numbers.get(style_id, (None, None))

    def abstract_id(self, num_id):
        return self._num_to_abstract.get(str(num_id))

    def level(self, num_id, ilvl):
        """Return the resolved level definition for ``num_id`` / ``ilvl``."""

        abstract_id = self._num_to_abstract.get(str(num_id))
        if abstract_id is None:
            return None
        base = self._levels.get(abstract_id, {}).get(str(ilvl))
        override = self._overrides.get(str(num_id), {}).get(str(ilvl))
        if base is None and override is None:
            return None
        if base is None:
            base = {}
        if override:
            merged = dict(base)
            merged.update(override)
            return merged
        return base

    def levels(self, num_id):
        """Return every resolved level of one concrete numbering instance."""

        abstract_id = self._num_to_abstract.get(str(num_id))
        if abstract_id is None:
            return {}
        base_levels = self._levels.get(abstract_id, {})
        overrides = self._overrides.get(str(num_id), {})
        result = {}
        for ilvl in set(base_levels) | set(overrides):
            level = self.level(num_id, ilvl)
            if level is not None:
                result[ilvl] = level
        return result

    def is_heading_numbering(self, num_id, ilvl):
        level = self.level(num_id, ilvl)
        if level is None:
            return False
        return (level.get("format") or "").lower() not in NON_HEADING_FORMATS

    def render_label(self, num_id, ilvl, counters):
        """Expand ``lvlText`` for the current counter values."""

        info = self.level(num_id, ilvl)
        if info is None:
            return ""
        text = info.get("text") or ""
        if not text:
            text = "%{0}.".format(int(ilvl) + 1)

        def replace(match):
            level_index = int(match.group(1)) - 1
            level_info = self.level(num_id, level_index) or {}
            start = level_info.get("start", DEFAULT_START)
            value = _display_value(counters, level_index, start)
            return _format_number(
                value, level_info.get("format") or "decimal"
            )

        return _PERCENT.sub(replace, text).strip()


class NumberingState:
    """Per-document counter state; call :meth:`label` once per paragraph."""

    def __init__(self, table):
        self.table = table
        self._counters = {}

    def label(self, num_id, ilvl):
        if self.table is None or num_id in (None, "", "0"):
            return None
        try:
            level_index = int(ilvl)
        except (TypeError, ValueError):
            level_index = 0
        info = self.table.level(num_id, level_index)
        if info is None:
            return None

        num_format = (info.get("format") or "").lower()
        if num_format in ("none", "picture"):
            return None
        if num_format == "bullet":
            return _bullet_text(info.get("text") or "")

        counters = self._counters.setdefault(str(num_id), {})
        start = info.get("start", DEFAULT_START)
        counters[level_index] = counters.get(level_index, start - 1) + 1

        for deeper_id, deeper_info in self.table.levels(num_id).items():
            deeper = _int(deeper_id)
            if deeper is None or deeper <= level_index:
                continue
            if deeper_info.get("restart") == 0:
                continue
            deeper_start = deeper_info.get("start", DEFAULT_START)
            counters[deeper] = deeper_start - 1

        return self.table.render_label(num_id, level_index, counters) or None


def _display_value(counters, level, start):
    value = counters.get(level)
    if value is None or value < start:
        return start
    return value


def _bullet_text(text):
    text = (text or "").strip()
    if not text:
        return "•"
    chars = []
    for char in text:
        code = ord(char)
        if 0xF000 <= code <= 0xF0FF:
            # Unknown private-use glyphs would otherwise turn into stray
            # ASCII letters ("n", "s", ...); fall back to a plain bullet.
            chars.append(_BULLET_GLYPHS.get(char, "•"))
        else:
            chars.append(char)
    result = "".join(chars).strip()
    return result or "•"


def _format_number(value, num_format):
    num_format = (num_format or "decimal").lower()
    value = int(value)

    if num_format in ("decimal", "ordinal", "cardinaltext"):
        return str(value)
    if num_format == "decimalzero":
        return str(value).zfill(2)
    if num_format == "lowerletter":
        return _letters(value).lower()
    if num_format == "upperletter":
        return _letters(value).upper()
    if num_format == "lowerroman":
        return _roman(value).lower()
    if num_format == "upperroman":
        return _roman(value).upper()
    if num_format in (
        "chinesecounting",
        "chinesecountingthousand",
        "chineselegalsimplified",
        "ideographdigital",
        "ideographtraditional",
        "japanesecounting",
        "taiwanesecounting",
        "taiwanesecountingthousand",
        "koreancounting",
        "koreandigital",
        "koreanlegal",
    ):
        return _chinese_number(value)
    if num_format == "decimalenclosedcircle":
        return _circled(value)
    if num_format == "decimalenclosedcirclechinese":
        return _circled(value)
    if num_format == "decimalenclosedparen":
        return "({0})".format(value)
    if num_format == "decimalenclosedfullstop":
        return "{0}.".format(value)
    if num_format == "decimalfullwidth":
        return "".join(chr(0xFF10 + int(digit)) for digit in str(value))
    if num_format == "decimalhalfwidth":
        return str(value)
    return str(value)


def _letters(value):
    if value <= 0:
        return str(value)
    result = ""
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _roman(value):
    if value <= 0 or value >= 4000:
        return str(value)
    result = []
    remaining = value
    for number, numeral in _ROMAN_VALUES:
        while remaining >= number:
            result.append(numeral)
            remaining -= number
    return "".join(result)


def _chinese_number(value):
    if value <= 0:
        return str(value)
    if value < 10:
        return _CHINESE_DIGITS[value]
    if value < 20:
        return "十" + (_CHINESE_DIGITS[value % 10] if value % 10 else "")
    if value < 100:
        return (
            _CHINESE_DIGITS[value // 10]
            + "十"
            + (_CHINESE_DIGITS[value % 10] if value % 10 else "")
        )
    if value < 1000:
        hundreds, remainder = divmod(value, 100)
        text = _CHINESE_DIGITS[hundreds] + "百"
        if remainder == 0:
            return text
        if remainder < 10:
            text += "零"
        return text + _chinese_number(remainder)
    return "".join(_CHINESE_DIGITS[int(digit)] for digit in str(value))


def _circled(value):
    if 1 <= value <= 20:
        return chr(0x2460 + value - 1)
    if 21 <= value <= 35:
        return chr(0x3251 + value - 21)
    return "({0})".format(value)
