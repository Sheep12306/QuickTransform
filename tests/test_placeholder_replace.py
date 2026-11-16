"""Tests for the shared placeholder scanning / replacement helpers."""

import unittest

from w2md.placeholder_replace import list_placeholders, replace_placeholders


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


class PlaceholderHelperTest(unittest.TestCase):
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

    def test_replace_placeholders_keeps_structure_and_skips_code(self):
        result = replace_placeholders(
            MARKDOWN,
            {
                "{{SHOWDOC_IMAGE_000001}}": "https://doc.bizgo.com/Public/Uploads/a.png",
                "{{SHOWDOC_IMAGE_000002}}": "http://doc.bizgo.com/Public/Uploads/b.png?sign=abc",
                "{{SHOWDOC_IMAGE_000005}}": "https://doc.bizgo.com/Public/Uploads/c.png",
            },
            {
                "{{SHOWDOC_IMAGE_000001}}": "架构图",
                "{{SHOWDOC_IMAGE_000002}}": "表格图",
                "{{SHOWDOC_IMAGE_000005}}": "正文图",
            },
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.replaced_count, 3)
        self.assertEqual(result.skipped_code_count, 2)
        self.assertIn(
            "第一段 ![架构图](https://doc.bizgo.com/Public/Uploads/a.png)",
            result.markdown,
        )
        self.assertIn(
            "| 说明 | ![表格图](http://doc.bizgo.com/Public/Uploads/b.png?sign=abc) |",
            result.markdown,
        )
        self.assertIn("{{SHOWDOC_IMAGE_000003}}", result.markdown)
        self.assertIn("{{SHOWDOC_IMAGE_000004}}", result.markdown)
        self.assertNotIn("data:image", result.markdown)

    def test_partial_replacement_leaves_missing_tokens(self):
        result = replace_placeholders(
            MARKDOWN,
            {"{{SHOWDOC_IMAGE_000001}}": "https://doc.bizgo.com/Public/Uploads/a.png"},
            {"{{SHOWDOC_IMAGE_000001}}": "架构图"},
            partial=True,
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.replaced_count, 1)
        self.assertEqual(result.skipped_missing_count, 2)
        self.assertIn("{{SHOWDOC_IMAGE_000002}}", result.markdown)
        self.assertIn("{{SHOWDOC_IMAGE_000005}}", result.markdown)

    def test_invalid_url_blocks_replacement(self):
        result = replace_placeholders(
            MARKDOWN,
            {"{{SHOWDOC_IMAGE_000001}}": "ftp://example.com/a.png"},
        )

        self.assertTrue(result.errors)
        self.assertIn("非法", result.errors[0])
        self.assertEqual(result.markdown, MARKDOWN)

    def test_crlf_is_preserved(self):
        markdown = "一\r\n\r\n{{SHOWDOC_IMAGE_000001}}\r\n"
        result = replace_placeholders(
            markdown,
            {"{{SHOWDOC_IMAGE_000001}}": "https://doc.bizgo.com/Public/Uploads/a.png"},
        )

        self.assertEqual(result.errors, [])
        self.assertIn("\r\n", result.markdown)
        self.assertNotIn("{{SHOWDOC_IMAGE_000001}}", result.markdown)


if __name__ == "__main__":
    unittest.main()
