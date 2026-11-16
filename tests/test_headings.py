"""Heading hierarchy tests for Word -> Markdown conversion."""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from w2md.config import Config
from w2md.pipeline import convert


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""

DOC_DEFAULTS = """
  <w:docDefaults>
    <w:rPrDefault><w:rPr><w:sz w:val="21"/></w:rPr></w:rPrDefault>
  </w:docDefaults>
"""


STYLES = """
  <w:style w:type="paragraph" w:styleId="Normal">
    <w:name w:val="Normal"/><w:rPr><w:sz w:val="21"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:sz w:val="40"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:sz w:val="40"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3">
    <w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="2"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading4">
    <w:name w:val="heading 4"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="3"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading5">
    <w:name w:val="heading 5"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="4"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading6">
    <w:name w:val="heading 6"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="5"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading7">
    <w:name w:val="heading 7"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="6"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="ChineseH1">
    <w:name w:val="标题 1"/><w:basedOn w:val="Normal"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="ChineseH2">
    <w:name w:val="标题 2"/><w:basedOn w:val="Normal"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="CustomLevel1">
    <w:name w:val="一级标题"/><w:basedOn w:val="Normal"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="BasedHeading">
    <w:name w:val="自定义章节"/><w:basedOn w:val="Heading2"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="NameParent">
    <w:name w:val="标题 3"/><w:basedOn w:val="Normal"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="NameChild">
    <w:name w:val="基于名称的子样式"/><w:basedOn w:val="NameParent"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="OutlineCustom">
    <w:name w:val="章节标题"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="1"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="ConflictName">
    <w:name w:val="标题 1"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="1"/></w:pPr>
  </w:style>
"""

NUMBERING = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="0">
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
    <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/></w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="1">
    <w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
  <w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>"""


def paragraph(
    text, style=None, outline=None, runs=None, num_id=None, ilvl=None, indent=None
):
    ppr = ""
    if style or outline is not None or num_id is not None or indent is not None:
        ppr = "<w:pPr>"
        if style:
            ppr += '<w:pStyle w:val="{0}"/>'.format(style)
        if num_id is not None:
            ppr += '<w:numPr><w:ilvl w:val="{0}"/><w:numId w:val="{1}"/></w:numPr>'.format(
                ilvl or 0, num_id
            )
        if outline is not None:
            ppr += '<w:outlineLvl w:val="{0}"/>'.format(outline)
        if indent is not None:
            ppr += '<w:ind w:left="{0}"/>'.format(indent)
        ppr += "</w:pPr>"
    if runs is None:
        runs = "<w:r><w:t>{0}</w:t></w:r>".format(text)
    return "<w:p>{0}{1}</w:p>".format(ppr, runs)


def build_docx(path, body, styles=STYLES, numbering=NUMBERING):
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{0}<w:sectPr/></w:body>
</w:document>""".format(body)
    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{0}{1}</w:styles>""".format(
        DOC_DEFAULTS, styles
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        archive.writestr("word/styles.xml", styles_xml)
        if numbering:
            archive.writestr("word/numbering.xml", numbering)


class HeadingTest(unittest.TestCase):
    def convert_markdown(self, body, styles=STYLES, numbering=NUMBERING, config=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        docx = root / "headings.docx"
        build_docx(docx, body, styles=styles, numbering=numbering)
        report, md_path = convert(
            docx,
            root,
            config=config if config is not None else Config(heading_offset=0),
        )
        markdown = md_path.read_text(encoding="utf-8")
        report_data = json.loads((root / "headings.report.json").read_text(encoding="utf-8"))
        return markdown, report, report_data

    def test_default_heading_offset_starts_at_h2(self):
        body = "".join(
            [
                paragraph("H1 标题", style="Heading1"),
                paragraph("H2 标题", style="Heading2"),
                paragraph("H6 标题", style="Heading6"),
                paragraph("H7 标题", style="Heading7"),
            ]
        )
        markdown, _, report_data = self.convert_markdown(body, config=Config())

        self.assertIn("## H1 标题", markdown)
        self.assertIn("### H2 标题", markdown)
        self.assertIn("###### H6 标题", markdown)
        self.assertIn("###### 〔H7〕 H7 标题", markdown)
        self.assertNotIn("\n# H1 标题", markdown)
        self.assertEqual([item["level"] for item in report_data["headings"]], [2, 3, 6, 6])
        self.assertEqual(
            [item["original_level"] for item in report_data["headings"]],
            [1, 2, 6, 7],
        )

    def test_outline_levels_and_deep_heading_downgrade(self):
        body = "".join(
            paragraph("H{0} 标题".format(level), style="Heading{0}".format(level))
            for level in range(1, 8)
        )
        markdown, report, report_data = self.convert_markdown(body)

        self.assertIn("# H1 标题", markdown)
        self.assertIn("## H2 标题", markdown)
        self.assertIn("### H3 标题", markdown)
        self.assertIn("#### H4 标题", markdown)
        self.assertIn("##### H5 标题", markdown)
        self.assertIn("###### H6 标题", markdown)
        self.assertIn("###### 〔H7〕 H7 标题", markdown)
        self.assertTrue(any(w.kind == "heading_downgraded" for w in report.warnings))

        headings = report_data["headings"]
        self.assertEqual([item["source"] for item in headings], ["style"] * 7)
        self.assertEqual(headings[-1]["original_level"], 7)
        self.assertEqual(headings[-1]["level"], 6)
        self.assertTrue(headings[-1]["downgraded"])

    def test_same_font_size_h1_h2_still_have_different_levels(self):
        # Heading1 and Heading2 both use 40 half-points in STYLES.
        body = paragraph("一级", style="Heading1") + paragraph("二级", style="Heading2")
        markdown, _, report_data = self.convert_markdown(body)

        self.assertIn("# 一级", markdown)
        self.assertIn("## 二级", markdown)
        self.assertEqual([item["level"] for item in report_data["headings"]], [1, 2])
        self.assertTrue(all("outlineLvl" in item["detail"] for item in report_data["headings"]))

    def test_chinese_styles_and_based_on_inheritance(self):
        body = "".join(
            [
                paragraph("中文一", style="ChineseH1"),
                paragraph("中文二", style="ChineseH2"),
                paragraph("自定义一级", style="CustomLevel1"),
                paragraph("继承二级", style="BasedHeading"),
                paragraph("名称继承三级", style="NameChild"),
                paragraph("自定义大纲二级", style="OutlineCustom"),
            ]
        )
        markdown, _, report_data = self.convert_markdown(body)

        self.assertIn("# 中文一", markdown)
        self.assertIn("## 中文二", markdown)
        self.assertIn("# 自定义一级", markdown)
        self.assertIn("## 继承二级", markdown)
        self.assertIn("### 名称继承三级", markdown)
        self.assertIn("## 自定义大纲二级", markdown)
        self.assertTrue(all(item["source"] == "style" for item in report_data["headings"]))

    def test_paragraph_outline_overrides_style_and_warns(self):
        body = paragraph("2.1 冲突标题", style="Heading1", outline=2)
        markdown, report, report_data = self.convert_markdown(body)

        self.assertIn("### 2.1 冲突标题", markdown)
        self.assertEqual(report_data["headings"][0]["source"], "outlineLvl")
        self.assertTrue(any(w.kind == "heading_conflict" for w in report.warnings))

    def test_style_outline_overrides_style_name_and_warns(self):
        body = paragraph("名称冲突", style="ConflictName")
        markdown, report, _ = self.convert_markdown(body)

        self.assertIn("## 名称冲突", markdown)
        self.assertTrue(any(w.kind == "heading_conflict" for w in report.warnings))

    def test_numbering_fallback_and_bullet_exclusion(self):
        body = "".join(
            [
                paragraph("编号二级", num_id=1, ilvl=1),
                paragraph("1.1 纯文本编号"),
                paragraph(
                    "",
                    runs='<w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t>1. 单级编号标题</w:t></w:r>',
                    num_id=1,
                    ilvl=0,
                ),
                paragraph("项目符号项", num_id=2, ilvl=0),
                paragraph(
                    "",
                    runs='<w:r><w:rPr><w:b/><w:sz w:val="40"/></w:rPr><w:t>大号项目符号</w:t></w:r>',
                    num_id=2,
                    ilvl=0,
                ),
            ]
        )
        markdown, _, report_data = self.convert_markdown(body)

        self.assertIn("1.1 编号二级", markdown)
        self.assertNotIn("## 1.1 编号二级", markdown)
        self.assertIn("## 1.1 纯文本编号", markdown)
        self.assertIn("# **1. 单级编号标题**", markdown)
        self.assertIn("• 项目符号项", markdown)
        self.assertIn("• **大号项目符号**", markdown)
        self.assertNotIn("# 项目符号项", markdown)
        self.assertNotIn("## 项目符号项", markdown)
        self.assertNotIn("# 大号项目符号", markdown)
        self.assertNotIn("1.1.1 编号二级", markdown)
        sources = [item["source"] for item in report_data["headings"]]
        self.assertEqual(sources, ["numbering", "numbering"])

    def test_chapter_numbers_and_list_bullets_are_preserved(self):
        styles = """
<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="NumHeading1">
  <w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:outlineLvl w:val="0"/></w:pPr>
</w:style>
<w:style w:type="paragraph" w:styleId="NumHeading2">
  <w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:outlineLvl w:val="1"/></w:pPr>
</w:style>
"""
        numbering = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="10">
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:pStyle w:val="NumHeading1"/><w:lvlText w:val="%1"/></w:lvl>
    <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:pStyle w:val="NumHeading2"/><w:lvlText w:val="%1.%2"/></w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="11">
    <w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="○"/></w:lvl>
    <w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/><w:lvlText w:val="■"/></w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="12">
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
    <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2."/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="10"><w:abstractNumId w:val="10"/></w:num>
  <w:num w:numId="11"><w:abstractNumId w:val="11"/></w:num>
  <w:num w:numId="12"><w:abstractNumId w:val="12"/></w:num>
</w:numbering>"""
        body = "".join(
            [
                paragraph("需求背景", style="NumHeading1"),
                paragraph("流程", style="NumHeading2"),
                paragraph("范围", style="NumHeading1"),
                paragraph("边界", style="NumHeading2"),
                paragraph("圆形项目", num_id=11, ilvl=0),
                paragraph("方形项目", num_id=11, ilvl=1),
                paragraph("列表一", num_id=12, ilvl=0),
                paragraph("列表二", num_id=12, ilvl=0),
                paragraph("列表子项", num_id=12, ilvl=1),
            ]
        )
        markdown, _, _ = self.convert_markdown(
            body, styles=styles, numbering=numbering
        )

        self.assertIn("# 1 需求背景", markdown)
        self.assertIn("## 1.1 流程", markdown)
        self.assertIn("# 2 范围", markdown)
        self.assertIn("## 2.1 边界", markdown)
        self.assertIn("○ 圆形项目", markdown)
        self.assertIn("　■ 方形项目", markdown)
        self.assertIn("1. 列表一", markdown)
        self.assertIn("2. 列表二", markdown)
        self.assertIn("　2.1. 列表子项", markdown)

    def test_heading_level_jump_is_preserved(self):
        body = paragraph("一级", style="Heading1") + paragraph("三级", style="Heading3")
        markdown, _, _ = self.convert_markdown(body)

        self.assertIn("# 一级", markdown)
        self.assertIn("### 三级", markdown)
        self.assertNotIn("## 三级", markdown.splitlines())

    def test_large_font_normal_text_stays_paragraph(self):
        body = paragraph(
            "",
            runs='<w:r><w:rPr><w:sz w:val="48"/></w:rPr><w:t>这是一段字号很大的普通正文，不是标题。</w:t></w:r>',
        )
        markdown, _, report_data = self.convert_markdown(body)

        self.assertNotIn("#", markdown)
        self.assertEqual(report_data["headings"], [])

    def test_font_size_fallback_only_for_bold_short_text(self):
        body = "".join(
            [
                paragraph(
                    "",
                    runs='<w:r><w:rPr><w:b/><w:sz w:val="40"/></w:rPr><w:t>字号兜底标题</w:t></w:r>',
                ),
                paragraph(
                    "",
                    runs='<w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t>字号兜底二级</w:t></w:r>',
                ),
                paragraph(
                    "",
                    runs='<w:r><w:rPr><w:sz w:val="40"/></w:rPr><w:t>大字号普通正文</w:t></w:r>',
                ),
            ]
        )
        markdown, report, report_data = self.convert_markdown(body)

        self.assertIn("# **字号兜底标题**", markdown)
        self.assertIn("## **字号兜底二级**", markdown)
        self.assertNotIn("# 大字号普通正文", markdown)
        self.assertEqual(
            [item["source"] for item in report_data["headings"]],
            ["font", "font"],
        )
        self.assertTrue(any(w.kind == "heading_font_fallback" for w in report.warnings))

    def test_typed_ordered_numbers_are_not_reparsed(self):
        # Raw "1. " at the start of a paragraph makes Markdown emit an ordered
        # list, which renumbers the item.  The typed number must stay literal;
        # NBSP after the marker prevents list parsing.
        body = "".join(
            [
                paragraph("1. 第一项"),
                paragraph("2. 第二项"),
                paragraph("3）第三项"),
            ]
        )
        markdown, _, _ = self.convert_markdown(body)

        self.assertIn("1.\u00a0第一项", markdown)
        self.assertIn("2.\u00a0第二项", markdown)
        self.assertIn("3）第三项", markdown)

    def test_left_indent_recovers_nested_bullet_with_ilvl_zero(self):
        # Word documents produced by Chinese WPS/Office often keep every level
        # at ilvl=0 and encode nesting only through w:ind.
        body = "".join(
            [
                paragraph("根项目", num_id=2, ilvl=0, indent=425),
                paragraph("子项目", num_id=2, ilvl=0, indent=1050),
                paragraph("孙项目", num_id=2, ilvl=0, indent=1260),
            ]
        )
        markdown, _, _ = self.convert_markdown(body)

        self.assertIn("• 根项目", markdown)
        self.assertIn("　• 子项目", markdown)
        self.assertIn("　　• 孙项目", markdown)

    def test_typed_number_and_bullet_keep_their_indent(self):
        body = "".join(
            [
                paragraph("1. 主项", indent=425),
                paragraph("                   • 子项", indent=1050),
            ]
        )
        markdown, _, _ = self.convert_markdown(body)

        self.assertIn("1.\u00a0主项", markdown)
        self.assertIn("　• 子项", markdown)
        self.assertNotIn("                   • 子项", markdown)

    def test_circle_and_square_bullet_glyphs(self):
        numbering = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="20">
    <w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val=""/></w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="21">
    <w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val=""/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="20"><w:abstractNumId w:val="20"/></w:num>
  <w:num w:numId="21"><w:abstractNumId w:val="21"/></w:num>
</w:numbering>"""
        body = paragraph("圆形项目", num_id=20) + paragraph("方形项目", num_id=21)
        markdown, _, _ = self.convert_markdown(body, numbering=numbering)

        self.assertIn("○ 圆形项目", markdown)
        self.assertIn("□ 方形项目", markdown)

    def test_number_counter_advances_for_empty_numbered_paragraph(self):
        # An empty numbered paragraph still consumes a Word number; skipping
        # it would shift every following label by one.
        body = "".join(
            [
                paragraph("第一项", num_id=1, ilvl=0),
                paragraph("", num_id=1, ilvl=0),
                paragraph("第三项", num_id=1, ilvl=0),
            ]
        )
        markdown, _, _ = self.convert_markdown(body)

        self.assertIn("1.\u00a0第一项", markdown)
        self.assertIn("3. 第三项", markdown)

    def test_outline_level_9_is_body_text(self):
        body = paragraph("显式正文", style="Heading1", outline=9)
        markdown, report, report_data = self.convert_markdown(body)

        self.assertNotIn("#", markdown)
        self.assertEqual(report_data["headings"], [])
        self.assertTrue(any(w.kind == "heading_conflict" for w in report.warnings))


if __name__ == "__main__":
    unittest.main()
