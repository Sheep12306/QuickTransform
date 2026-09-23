"""Smoke test for the conversion pipeline."""

import json
import tempfile
import unittest
from pathlib import Path

from fixture_builder import build_sample_docx
from w2md.config import Config
from w2md.pipeline import convert


EXPECTED_HTML = """# 需求背景

本文档描述采购订单需求。

## 采购订单流程

**加粗**的普通文字。

<span style="color:#FF0000">红色警告</span>，<mark style="background-color:#FFFF00">黄色提醒</mark>，<u>下划线</u>文字。

| 字段 | 说明 |
| --- | --- |
| 数量 | 采购数量 |

![示例图片](sample_prd.assets/img-001.png)

### 字段说明
"""


EXPECTED_DROP = """# 需求背景

本文档描述采购订单需求。

## 采购订单流程

**加粗**的普通文字。

红色警告，黄色提醒，下划线文字。

| 字段 | 说明 |
| --- | --- |
| 数量 | 采购数量 |

![示例图片](sample_prd.assets/img-001.png)

### 字段说明
"""


class ConversionTest(unittest.TestCase):
    def test_default_drops_inline_styles(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "sample_prd.docx"
            build_sample_docx(docx)

            report, md_path = convert(docx, tmp)
            markdown = md_path.read_text(encoding="utf-8")

            self.assertEqual(markdown, EXPECTED_DROP)
            self.assertNotIn("<span", markdown)
            self.assertEqual(report.stats["headings"], 3)
            self.assertEqual(report.stats["tables"], 1)
            self.assertEqual(report.stats["images"], 1)
            self.assertEqual(report.status, "warn")
            self.assertTrue(any(w.kind == "style_dropped" for w in report.warnings))
            self.assertIn("![示例图片](sample_prd.assets/img-001.png)", markdown)
            self.assertTrue((tmp / "sample_prd.assets" / "img-001.png").is_file())

            data = json.loads((tmp / "sample_prd.report.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "warn")

    def test_html_mode_keeps_inline_styles(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "sample_prd.docx"
            build_sample_docx(docx)

            report, md_path = convert(docx, tmp, config=Config(inline_style="html"))
            markdown = md_path.read_text(encoding="utf-8")

            self.assertEqual(markdown, EXPECTED_HTML)
            self.assertIn('<span style="color:#FF0000">红色警告</span>', markdown)
            self.assertIn("![示例图片](sample_prd.assets/img-001.png)", markdown)
            self.assertEqual(report.status, "ok")

    def test_base64_embeds_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "sample_prd.docx"
            build_sample_docx(docx)

            report, md_path = convert(docx, tmp, config=Config(assets_mode="base64"))
            markdown = md_path.read_text(encoding="utf-8")

            self.assertIn("![示例图片](data:image/png;base64,", markdown)
            self.assertFalse((tmp / "sample_prd.assets").exists())
            self.assertEqual(report.stats["images"], 1)

    def test_placeholder_replaces_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "sample_prd.docx"
            build_sample_docx(docx)

            report, md_path = convert(docx, tmp, config=Config(assets_mode="placeholder"))
            markdown = md_path.read_text(encoding="utf-8")

            self.assertIn("**图片占位 1：示例图片**", markdown)
            self.assertNotIn("data:image", markdown)
            self.assertFalse((tmp / "sample_prd.assets").exists())
            self.assertEqual(report.stats["images"], 1)
            self.assertTrue(any(w.kind == "image_placeholder" for w in report.warnings))
