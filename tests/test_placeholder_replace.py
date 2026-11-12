"""Tests for the ShowDoc placeholder replacement module."""

import unittest

from w2md.placeholder_replace import (
    analyze_replacement,
    extract_image_urls,
    list_placeholders,
    replace_placeholders,
    update_manifest,
)


MARKDOWN = """# 文档

第一段 {{SHOWDOC_IMAGE_000001}}

| 列 | 图 |
| --- | --- |
| 说明 | {{SHOWDOC_IMAGE_000002}} |

```text
{{SHOWDOC_IMAGE_000003}}
```

行内 `{{SHOWDOC_IMAGE_000004}}` 和正文 {{SHOWDOC_IMAGE_000005}}
"""

SHOWDOC = """![图1](https://doc.bizgo.com/Public/Uploads/a.png)

![图2](http://doc.bizgo.com/Public/Uploads/b.png?sign=abc&expires=123)

![图3](https://doc.bizgo.com/Public/Uploads/c.png)
"""

MANIFEST = {
    "images": [
        {
            "placeholder": "{{SHOWDOC_IMAGE_000001}}",
            "order": 1,
            "alt_text": "架构图",
            "local_path": "assets/doc-image-000001.png",
            "showdoc_url": None,
            "upload_status": "not_uploaded",
            "replacement_status": "pending",
        },
        {
            "placeholder": "{{SHOWDOC_IMAGE_000002}}",
            "order": 2,
            "alt_text": "表格图",
            "local_path": "assets/doc-image-000002.png",
            "showdoc_url": None,
            "upload_status": "not_uploaded",
            "replacement_status": "pending",
        },
        {
            "placeholder": "{{SHOWDOC_IMAGE_000005}}",
            "order": 5,
            "alt_text": "正文图",
            "local_path": "assets/doc-image-000003.png",
            "showdoc_url": None,
            "upload_status": "not_uploaded",
            "replacement_status": "pending",
        },
    ]
}


class PlaceholderReplaceTest(unittest.TestCase):
    def test_placeholders_skip_fenced_inline_and_indented_code(self):
        markdown = MARKDOWN + "\n    {{SHOWDOC_IMAGE_000006}}\n"
        occurrences = list_placeholders(markdown)

        outside = [item.placeholder for item in occurrences if not item.in_code]
        inside = [item.placeholder for item in occurrences if item.in_code]

        self.assertEqual(
            outside,
            [
                "{{SHOWDOC_IMAGE_000001}}",
                "{{SHOWDOC_IMAGE_000002}}",
                "{{SHOWDOC_IMAGE_000005}}",
            ],
        )
        self.assertEqual(
            inside,
            [
                "{{SHOWDOC_IMAGE_000003}}",
                "{{SHOWDOC_IMAGE_000004}}",
                "{{SHOWDOC_IMAGE_000006}}",
            ],
        )

    def test_indented_nested_list_is_not_treated_as_code(self):
        markdown = "- 列表项\n\n    {{SHOWDOC_IMAGE_000007}}\n"
        occurrences = list_placeholders(markdown)

        self.assertEqual(len(occurrences), 1)
        self.assertFalse(occurrences[0].in_code)

    def test_urls_are_extracted_in_order_with_sign_parameters(self):
        urls = extract_image_urls(SHOWDOC)

        self.assertEqual(
            [item.url for item in urls],
            [
                "https://doc.bizgo.com/Public/Uploads/a.png",
                "http://doc.bizgo.com/Public/Uploads/b.png?sign=abc&expires=123",
                "https://doc.bizgo.com/Public/Uploads/c.png",
            ],
        )
        self.assertTrue(all(item.valid for item in urls))

    def test_count_mismatch_stops_generation(self):
        analysis = analyze_replacement(MARKDOWN, SHOWDOC[: SHOWDOC.index("![图3]")])

        self.assertFalse(analysis.can_generate)
        self.assertTrue(any("数量不一致" in error for error in analysis.errors))
        self.assertEqual(analysis.counts["placeholders"], 3)
        self.assertEqual(analysis.counts["urls"], 2)

    def test_extra_urls_are_reported(self):
        analysis = analyze_replacement(MARKDOWN, SHOWDOC + "![图4](https://doc.bizgo.com/Public/Uploads/d.png)\n")

        self.assertFalse(analysis.can_generate)
        self.assertTrue(any("多余 URL" in error for error in analysis.errors))

    def test_manifest_count_mismatch_is_reported(self):
        manifest = {"images": MANIFEST["images"][:2]}
        analysis = analyze_replacement(MARKDOWN, SHOWDOC, manifest=manifest)

        self.assertFalse(analysis.can_generate)
        self.assertTrue(any("manifest" in error for error in analysis.errors))

    def test_default_mapping_and_structure_preserving_replacement(self):
        analysis = analyze_replacement(MARKDOWN, SHOWDOC, manifest=MANIFEST)
        self.assertTrue(analysis.can_generate)
        self.assertEqual(
            [item.placeholder for item in analysis.mapping],
            [
                "{{SHOWDOC_IMAGE_000001}}",
                "{{SHOWDOC_IMAGE_000002}}",
                "{{SHOWDOC_IMAGE_000005}}",
            ],
        )
        self.assertEqual(analysis.counts["code_block_placeholders"], 2)

        result = replace_placeholders(
            MARKDOWN,
            {item.placeholder: item.url for item in analysis.mapping},
            {item.placeholder: item.alt_text for item in analysis.mapping},
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.replaced_count, 3)
        self.assertEqual(result.skipped_code_count, 2)
        self.assertIn(
            "第一段 ![架构图](https://doc.bizgo.com/Public/Uploads/a.png)",
            result.markdown,
        )
        self.assertIn(
            "| 说明 | ![表格图](http://doc.bizgo.com/Public/Uploads/b.png?sign=abc&expires=123) |",
            result.markdown,
        )
        self.assertIn("{{SHOWDOC_IMAGE_000003}}", result.markdown)
        self.assertIn("{{SHOWDOC_IMAGE_000004}}", result.markdown)
        self.assertNotIn("data:image", result.markdown)

    def test_manual_mapping_reorders_urls_and_allows_reuse(self):
        analysis = analyze_replacement(
            MARKDOWN,
            SHOWDOC,
            manifest=MANIFEST,
            mapping=[
                {
                    "placeholder": "{{SHOWDOC_IMAGE_000001}}",
                    "url": "https://doc.bizgo.com/Public/Uploads/c.png",
                },
                {
                    "placeholder": "{{SHOWDOC_IMAGE_000002}}",
                    "url": "https://doc.bizgo.com/Public/Uploads/c.png",
                },
                {
                    "placeholder": "{{SHOWDOC_IMAGE_000005}}",
                    "url": "https://doc.bizgo.com/Public/Uploads/a.png",
                },
            ],
        )

        self.assertTrue(analysis.can_generate)
        self.assertTrue(any("未被映射使用" in warning for warning in analysis.warnings))
        result = replace_placeholders(
            MARKDOWN,
            {item.placeholder: item.url for item in analysis.mapping},
            {item.placeholder: item.alt_text for item in analysis.mapping},
        )
        self.assertIn("![架构图](https://doc.bizgo.com/Public/Uploads/c.png)", result.markdown)
        self.assertIn("![表格图](https://doc.bizgo.com/Public/Uploads/c.png)", result.markdown)
        self.assertIn("![正文图](https://doc.bizgo.com/Public/Uploads/a.png)", result.markdown)

    def test_fallback_alt_text(self):
        analysis = analyze_replacement(MARKDOWN, SHOWDOC, manifest=MANIFEST)
        mapping = {item.placeholder: item.url for item in analysis.mapping}
        alt = {item.placeholder: item.alt_text for item in analysis.mapping}
        result = replace_placeholders(MARKDOWN, mapping, alt)

        self.assertIn("![架构图](", result.markdown)
        self.assertIn("![表格图](", result.markdown)
        self.assertIn("![正文图](", result.markdown)

        no_manifest = analyze_replacement(MARKDOWN, SHOWDOC)
        no_manifest_alt = {
            item.placeholder: item.alt_text for item in no_manifest.mapping
        }
        self.assertEqual(no_manifest_alt["{{SHOWDOC_IMAGE_000001}}"], "图片1")
        self.assertEqual(no_manifest_alt["{{SHOWDOC_IMAGE_000005}}"], "图片5")

    def test_update_manifest_sets_url_and_status(self):
        updated = update_manifest(
            MANIFEST,
            {
                "{{SHOWDOC_IMAGE_000001}}": "https://doc.bizgo.com/Public/Uploads/a.png",
                "{{SHOWDOC_IMAGE_000002}}": "https://doc.bizgo.com/Public/Uploads/b.png",
                "{{SHOWDOC_IMAGE_000005}}": "https://doc.bizgo.com/Public/Uploads/c.png",
            },
        )

        self.assertEqual(updated["images"][0]["upload_status"], "url_received")
        self.assertEqual(updated["images"][0]["replacement_status"], "replaced")
        self.assertEqual(updated["images"][0]["showdoc_url"], "https://doc.bizgo.com/Public/Uploads/a.png")
        self.assertEqual(updated["replacement"], {"matched": 3, "missing": 0, "total": 3})
        self.assertIsNone(MANIFEST["images"][0]["showdoc_url"])

    def test_invalid_and_base64_urls_are_rejected(self):
        showdoc = (
            "![x](ftp://example.com/a.png)\n"
            "![y](data:image/png;base64,AAAA)\n"
        )
        markdown = (
            "{{SHOWDOC_IMAGE_000001}}\n\n{{SHOWDOC_IMAGE_000002}}\n"
        )
        analysis = analyze_replacement(markdown, showdoc)

        self.assertFalse(analysis.can_generate)
        self.assertTrue(any("非法" in error for error in analysis.errors))
        self.assertTrue(any("Base64" in error for error in analysis.errors))

    def test_crlf_is_preserved(self):
        markdown = "一\r\n\r\n{{SHOWDOC_IMAGE_000001}}\r\n"
        showdoc = "![a](https://doc.bizgo.com/Public/Uploads/a.png)\n"
        analysis = analyze_replacement(markdown, showdoc)
        result = replace_placeholders(
            markdown,
            {"{{SHOWDOC_IMAGE_000001}}": analysis.urls[0].url},
        )

        self.assertEqual(result.errors, [])
        self.assertIn("\r\n", result.markdown)
        self.assertNotIn("\n\n{{SHOWDOC_IMAGE_000001}}", result.markdown)

    def test_empty_inputs_do_not_generate(self):
        analysis = analyze_replacement("", "")

        self.assertFalse(analysis.can_generate)
        self.assertTrue(analysis.errors)


if __name__ == "__main__":
    unittest.main()
