"""Resolve Word paragraph heading levels.

Priority (highest first):

1. paragraph ``w:pPr/w:outlineLvl``
2. paragraph style (``w:pStyle``): style outline level, then style name
3. numbering level / explicit ``1.``, ``1.1``, ``1.1.1`` text
4. font size + bold (last-resort visual heuristic)

Font size is never allowed to override an explicit outline level or a heading
style.  Levels above 6 are kept in the IR and downgraded explicitly by the
renderer, while the report keeps the original level.
"""

import re
from dataclasses import dataclass, field

from ..opc.ns import W_NS


W = "{%s}" % W_NS

_MULTI_NUMBER = re.compile(r"^\s*(\d+(?:[.．]\d+)+)[.．、]?\s*")
_SINGLE_NUMBER = re.compile(r"^\s*(\d+)[.．、]\s+")
_BULLET_START = re.compile(r"^[\-•●○■□]\s*")


@dataclass
class HeadingMatch:
    level: int
    source: str
    detail: str
    conflicts: list = field(default_factory=list)
    font_size: int | None = None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_on(element):
    value = element.get(W + "val")
    return value is None or value not in ("0", "false", "off", "none")


def _paragraph_outline(p_el):
    ppr = p_el.find(W + "pPr")
    if ppr is None:
        return None
    outline = ppr.find(W + "outlineLvl")
    if outline is None:
        return None
    return _int(outline.get(W + "val"))


def _paragraph_style_id(p_el):
    ppr = p_el.find(W + "pPr")
    if ppr is None:
        return None
    style = ppr.find(W + "pStyle")
    return style.get(W + "val") if style is not None else None


def _paragraph_text(p_el):
    parts = []
    for element in p_el.iter():
        if element.tag == W + "t":
            parts.append(element.text or "")
        elif element.tag == W + "tab":
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _text_number_level(text):
    if not text:
        return None
    match = _MULTI_NUMBER.match(text)
    if match:
        normalized = match.group(1).replace("．", ".")
        first = _int(normalized.split(".")[0])
        if first is not None and first > 100:
            return None
        return normalized.count(".") + 1
    match = _SINGLE_NUMBER.match(text)
    if match:
        first = _int(match.group(1))
        if first is not None and first > 100:
            return None
        return 1
    return None


def _looks_like_heading_text(text):
    text = (text or "").strip()
    if not text or len(text) > 100:
        return False
    if _BULLET_START.match(text):
        return False
    if re.search(r"[。！？!?；;]\s*$", text):
        return False
    return True


def _num_from_ppr(ppr):
    if ppr is None:
        return None, None
    num_pr = ppr.find(W + "numPr")
    if num_pr is None:
        return None, None
    num_id = None
    ilvl = None
    num_id_el = num_pr.find(W + "numId")
    if num_id_el is not None:
        num_id = num_id_el.get(W + "val")
    ilvl_el = num_pr.find(W + "ilvl")
    if ilvl_el is not None:
        ilvl = ilvl_el.get(W + "val")
    return num_id, ilvl


def _run_effective_size(run, style_id, styles, default_size):
    rpr = run.find(W + "rPr")
    if rpr is not None:
        size = rpr.find(W + "sz")
        if size is None:
            size = rpr.find(W + "szCs")
        if size is not None:
            value = _int(size.get(W + "val"))
            if value:
                return value
    if styles is not None:
        style_size = styles.font_size(style_id)
        if style_size:
            return style_size
    return default_size


def _run_effective_bold(run, style_id, styles, default_bold):
    rpr = run.find(W + "rPr")
    if rpr is not None:
        bold = rpr.find(W + "b")
        if bold is not None:
            return _is_on(bold)
    if styles is not None:
        style_bold = styles.bold(style_id)
        if style_bold is not None:
            return style_bold
    return default_bold


def _paragraph_font_size(p_el, style_id, styles):
    default_size = styles.default_font_size() if styles is not None else 21
    sizes = [
        _run_effective_size(run, style_id, styles, default_size)
        for run in p_el.iter(W + "r")
    ]
    if sizes:
        return max(sizes)

    ppr = p_el.find(W + "pPr")
    if ppr is not None:
        rpr = ppr.find(W + "rPr")
        if rpr is not None:
            size = rpr.find(W + "sz")
            if size is not None:
                value = _int(size.get(W + "val"))
                if value:
                    return value
    if styles is not None:
        style_size = styles.font_size(style_id)
        if style_size:
            return style_size
    return default_size


def _paragraph_bold(p_el, style_id, styles):
    default_bold = styles.default_bold() if styles is not None else False
    values = [
        _run_effective_bold(run, style_id, styles, default_bold)
        for run in p_el.iter(W + "r")
    ]
    if values:
        return all(values)

    ppr = p_el.find(W + "pPr")
    if ppr is not None:
        rpr = ppr.find(W + "rPr")
        if rpr is not None:
            bold = rpr.find(W + "b")
            if bold is not None:
                return _is_on(bold)
    if styles is not None:
        style_bold = styles.bold(style_id)
        if style_bold is not None:
            return style_bold
    return default_bold


class HeadingResolver:
    def __init__(self, root, styles=None, numbering=None):
        self.styles = styles
        self.numbering = numbering
        self.body_size = styles.default_font_size() if styles is not None else 21
        self.font_levels = self._build_font_levels(root)

    def resolve(self, p_el):
        style_id = _paragraph_style_id(p_el)
        text = _paragraph_text(p_el)
        font_size = _paragraph_font_size(p_el, style_id, self.styles)
        bold = _paragraph_bold(p_el, style_id, self.styles)

        paragraph_outline = _paragraph_outline(p_el)
        style_outline = self.styles.outline_level(style_id) if self.styles is not None else None
        style_name_level = (
            self.styles.name_heading_level(style_id) if self.styles is not None else None
        )

        if paragraph_outline is not None:
            # 9 means "body text" in OOXML; it must suppress font fallback too.
            if paragraph_outline >= 9:
                style_level = self._style_level(style_outline, style_name_level)
                if style_level is not None:
                    return HeadingMatch(
                        level=0,
                        source="outlineLvl",
                        detail="paragraph outlineLvl={0} (body)".format(paragraph_outline),
                        conflicts=[
                            "段落 outlineLvl={0} 表示正文，但样式 {1} 暗示 H{2}，按正文输出".format(
                                paragraph_outline, style_id, style_level
                            )
                        ],
                        font_size=font_size,
                    )
                return None
            if paragraph_outline < 0:
                return None
            level = paragraph_outline + 1
            conflicts = []
            style_level = self._style_level(style_outline, style_name_level)
            if style_level is not None and style_level != level:
                conflicts.append(
                    "段落 outlineLvl={0} 与样式 {1} 的级别 H{2} 冲突，按 outlineLvl 输出 H{3}".format(
                        paragraph_outline, style_id, style_level, level
                    )
                )
            return self._finish(
                HeadingMatch(
                    level=level,
                    source="outlineLvl",
                    detail="paragraph outlineLvl={0}".format(paragraph_outline),
                    conflicts=conflicts,
                    font_size=font_size,
                ),
                text,
            )

        if style_outline is not None:
            if style_outline >= 9:
                if style_name_level is not None:
                    return HeadingMatch(
                        level=0,
                        source="style",
                        detail="style {0} outlineLvl={1} (body)".format(style_id, style_outline),
                        conflicts=[
                            "样式 {0} 的 outlineLvl={1} 表示正文，但名称级别为 H{2}，按正文输出".format(
                                style_id, style_outline, style_name_level
                            )
                        ],
                        font_size=font_size,
                    )
                return None
            level = style_outline + 1
            conflicts = []
            if style_name_level is not None and style_name_level != level:
                conflicts.append(
                    "样式 {0} 的 outlineLvl={1} 与名称级别 H{2} 冲突，按 outlineLvl 输出 H{3}".format(
                        style_id, style_outline, style_name_level, level
                    )
                )
            return self._finish(
                HeadingMatch(
                    level=level,
                    source="style",
                    detail="style {0} outlineLvl={1}".format(style_id, style_outline),
                    conflicts=conflicts,
                    font_size=font_size,
                ),
                text,
            )

        if style_name_level is not None:
            return self._finish(
                HeadingMatch(
                    level=style_name_level,
                    source="style",
                    detail="style {0} name={1}".format(
                        style_id, self.styles.style_name(style_id)
                    ),
                    font_size=font_size,
                ),
                text,
            )

        numbering_match = self._numbering_match(p_el, style_id, text, bold, font_size)
        if numbering_match is not None:
            return self._finish(numbering_match, text)

        # A bullet/numbered paragraph that did not look like a heading must not
        # be promoted by the font-size heuristic.
        if self._has_numbering(p_el, style_id):
            return None

        font_match = self._font_match(text, bold, font_size)
        if font_match is not None:
            return self._finish(font_match, text)

        return None

    def _finish(self, match, text):
        text_level = _text_number_level(text)
        if text_level is not None and text_level != match.level:
            match.conflicts.append(
                "正文编号层级 {0} 与识别级别 H{1} 不一致，保留 H{1}".format(
                    text_level, match.level
                )
            )
        return match

    def _style_level(self, style_outline, style_name_level):
        if style_outline is not None:
            if style_outline >= 9:
                return None
            return style_outline + 1
        return style_name_level

    def _numbering_ids(self, p_el, style_id):
        num_id, ilvl = _num_from_ppr(p_el.find(W + "pPr"))
        style_num_id, style_ilvl = (
            self.styles.num_pr(style_id) if self.styles is not None else (None, None)
        )
        if num_id is None:
            num_id = style_num_id
        if ilvl is None:
            ilvl = style_ilvl
        if num_id in (None, "", "0") and self.numbering is not None and style_id:
            linked_num_id, linked_ilvl = self.numbering.num_for_style(style_id)
            if linked_num_id:
                num_id = linked_num_id
                if ilvl is None:
                    ilvl = linked_ilvl
        if num_id in (None, "", "0"):
            num_id = None
        return num_id, str(ilvl if ilvl is not None else 0)

    def numbering_ids(self, p_el):
        """Return ``(numId, ilvl)`` for numbering display, or ``(None, 0)``."""

        style_id = _paragraph_style_id(p_el)
        num_id, ilvl = self._numbering_ids(p_el, style_id)
        try:
            level = int(ilvl)
        except (TypeError, ValueError):
            level = 0
        return num_id, level

    def _has_numbering(self, p_el, style_id):
        num_id, _ = self._numbering_ids(p_el, style_id)
        return num_id is not None

    def _numbering_match(self, p_el, style_id, text, bold, font_size):
        num_id, ilvl = self._numbering_ids(p_el, style_id)

        text_level = _text_number_level(text)

        if num_id is None:
            if text_level is not None and _looks_like_heading_text(text):
                if text_level >= 2 or bold or font_size >= self.body_size * 1.2:
                    return HeadingMatch(
                        level=text_level,
                        source="numbering",
                        detail="正文编号前缀 {0}".format(text_level),
                        font_size=font_size,
                    )
            return None

        level_info = (
            self.numbering.level(num_id, ilvl) if self.numbering is not None else None
        )
        num_format = (level_info or {}).get("format", "").lower()
        if num_format in ("bullet", "none", "picture"):
            return None

        if text_level is not None:
            if text_level >= 2 or bold or font_size >= self.body_size * 1.2:
                return HeadingMatch(
                    level=text_level,
                    source="numbering",
                    detail="numId={0} ilvl={1} 正文编号前缀 {2}".format(
                        num_id, ilvl, text_level
                    ),
                    font_size=font_size,
                )
            return None

        try:
            numeric_ilvl = int(ilvl)
        except ValueError:
            numeric_ilvl = 0
        if numeric_ilvl > 0:
            # Nested numbering is used by both chapter headings and ordinary
            # multi-level lists.  Only promote it when the text also looks and
            # reads like a heading; otherwise it stays a list item and keeps
            # its number prefix.
            if _looks_like_heading_text(text) and (
                bold or font_size >= self.body_size * 1.2
            ):
                return HeadingMatch(
                    level=numeric_ilvl + 1,
                    source="numbering",
                    detail="numId={0} ilvl={1} format={2}".format(
                        num_id, ilvl, num_format or "unknown"
                    ),
                    font_size=font_size,
                )
            return None

        if _looks_like_heading_text(text) and (
            bold or font_size >= self.body_size * 1.2
        ):
            return HeadingMatch(
                level=1,
                source="numbering",
                detail="numId={0} ilvl=0 format={1}".format(
                    num_id, num_format or "unknown"
                ),
                font_size=font_size,
            )
        return None

    def _font_match(self, text, bold, font_size):
        if font_size not in self.font_levels:
            return None
        if not bold:
            return None
        if font_size < max(self.body_size * 1.3, 24):
            return None
        if not _looks_like_heading_text(text):
            return None
        return HeadingMatch(
            level=self.font_levels[font_size],
            source="font",
            detail="字号 {0} 半磅（正文 {1} 半磅）+ 加粗".format(
                font_size, self.body_size
            ),
            font_size=font_size,
        )

    def _build_font_levels(self, root):
        sizes = set()
        for paragraph in root.iter(W + "p"):
            style_id = _paragraph_style_id(paragraph)
            text = _paragraph_text(paragraph)
            paragraph_outline = _paragraph_outline(paragraph)
            style_outline = (
                self.styles.outline_level(style_id) if self.styles is not None else None
            )
            style_name_level = (
                self.styles.name_heading_level(style_id)
                if self.styles is not None
                else None
            )
            if paragraph_outline is not None or style_outline is not None or style_name_level is not None:
                continue

            font_size = _paragraph_font_size(paragraph, style_id, self.styles)
            bold = _paragraph_bold(paragraph, style_id, self.styles)
            if self._numbering_match(paragraph, style_id, text, bold, font_size) is not None:
                continue
            if self._has_numbering(paragraph, style_id):
                continue
            if not bold or font_size < max(self.body_size * 1.3, 24):
                continue
            if not _looks_like_heading_text(text):
                continue
            sizes.add(font_size)

        levels = {}
        for rank, size in enumerate(sorted(sizes, reverse=True), start=1):
            levels[size] = min(rank, 6)
        return levels
