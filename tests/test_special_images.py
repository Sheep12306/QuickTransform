"""Tests for special image handling after upload-result filling."""

import unittest

from w2md.special_images import (
    analyze_special_images,
    apply_special_images,
    update_special_manifest,
)


MARKDOWN = """# 文档

正文已回填 ![架构图](https://doc.bizgo.com/Public/Uploads/a.png)

{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}

行内 `{{SHOWDOC_OVERSIZED_IMAGE_000003}}`

```text
{{SHOWDOC_CONVERSION_FAILED_IMAGE_000004}}
```
"""

MANIFEST = {
    "document_id": "doc-1",
    "images": [
        {
            "sequence": 1,
            "occurrence_id": "IMG_OCC_000001",
            "placeholder": "{{SHOWDOC_IMAGE_000001}}",
            "compatibility": "supported",
            "alt_text": "架构图",
            "source_file": "assets/doc-image-000001.png",
            "local_path": "assets/doc-image-000001.png",
        },
        {
            "sequence": 2,
            "occurrence_id": "IMG_OCC_000002",
            "placeholder": "{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}",
            "compatibility": "unsupported",
            "compatibility_reason": "EMF 不支持直接上传",
            "alt_text": "矢量图",
            "source_file": "assets/doc-image-000002.emf",
            "local_path": "assets/doc-image-000002.emf",
        },
        {
            "sequence": 3,
            "occurrence_id": "IMG_OCC_000003",
            "placeholder": "{{SHOWDOC_OVERSIZED_IMAGE_000003}}",
            "compatibility": "oversized",
            "compatibility_reason": "图片超过 5 MB",
            "alt_text": "超限图",
            "source_file": "assets/doc-image-000003.png",
            "upload_file": "assets/upload/doc-image-000003.png",
            "local_path": "assets/upload/doc-image-000003.png",
        },
        {
            "sequence": 4,
            "occurrence_id": "IMG_OCC_000004",
            "placeholder": "{{SHOWDOC_CONVERSION_FAILED_IMAGE_000004}}",
            "compatibility": "conversion_failed",
            "compatibility_reason": "TIFF 转换失败",
            "alt_text": "转换失败图",
            "source_file": "assets/doc-image-000004.tif",
            "local_path": "assets/doc-image-000004.tif",
        },
    ],
}


URLS = {
    "{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}": "https://doc.bizgo.com/Public/Uploads/emf.png",
}


class SpecialImageTest(unittest.TestCase):
    def test_analysis_lists_special_images_and_pending_count(self):
        analysis = analyze_special_images(MARKDOWN, MANIFEST)

        self.assertTrue(analysis.manifest_provided)
        self.assertEqual(analysis.counts["special_images"], 3)
        self.assertEqual(analysis.counts["in_markdown"], 1)
        self.assertEqual(analysis.counts["pending"], 1)
        self.assertEqual(analysis.counts["in_code_only"], 2)
        self.assertEqual(analysis.counts["normal_residue_occurrences"], 0)
        self.assertEqual(analysis.counts["occurrence_id_duplicates"], 0)
        self.assertFalse(analysis.can_generate)
        self.assertTrue(any("待处理" in error for error in analysis.errors))
        self.assertEqual(
            [item.placeholder for item in analysis.items],
            [
                "{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}",
                "{{SHOWDOC_OVERSIZED_IMAGE_000003}}",
                "{{SHOWDOC_CONVERSION_FAILED_IMAGE_000004}}",
            ],
        )

    def test_all_urls_filled_allows_generation(self):
        analysis = analyze_special_images(MARKDOWN, MANIFEST, urls=URLS)

        self.assertTrue(analysis.can_generate)
        self.assertEqual(analysis.counts["matched"], 1)
        self.assertEqual(analysis.counts["pending"], 0)
        self.assertEqual(analysis.items[0].status, "matched")
        self.assertEqual(analysis.items[1].line, None)

        mapping = {
            item.placeholder: item.url
            for item in analysis.items
            if item.status == "matched"
        }
        alt = {item.placeholder: item.alt_text for item in analysis.items}
        result = apply_special_images(MARKDOWN, mapping, alt)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.replaced_count, 1)
        self.assertTrue(result.final_check["passed"])
        self.assertEqual(result.final_check["remaining_total"], 0)
        self.assertEqual(result.final_check["code_block"], 2)
        self.assertIn(
            "![矢量图](https://doc.bizgo.com/Public/Uploads/emf.png)",
            result.markdown,
        )
        self.assertNotIn("{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}", result.markdown)
        self.assertIn("{{SHOWDOC_OVERSIZED_IMAGE_000003}}", result.markdown)
        self.assertIn("{{SHOWDOC_CONVERSION_FAILED_IMAGE_000004}}", result.markdown)

    def test_normal_placeholder_residue_blocks_generation(self):
        markdown = MARKDOWN.replace(
            "正文已回填 ![架构图](https://doc.bizgo.com/Public/Uploads/a.png)",
            "正文 {{SHOWDOC_IMAGE_000001}} 尚未回填",
        )
        analysis = analyze_special_images(markdown, MANIFEST, urls=URLS)

        self.assertFalse(analysis.can_generate)
        self.assertEqual(analysis.counts["normal_residue_occurrences"], 1)
        self.assertTrue(
            any("普通占位符残留" in error for error in analysis.errors)
        )
        self.assertFalse(analysis.checks["normal_residue"]["ok"])

    def test_invalid_url_is_reported(self):
        urls = dict(URLS)
        urls["{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}"] = "data:image/png;base64,AAAA"
        analysis = analyze_special_images(MARKDOWN, MANIFEST, urls=urls)

        self.assertFalse(analysis.can_generate)
        self.assertEqual(analysis.counts["invalid_url"], 1)
        self.assertFalse(analysis.checks["urls"]["ok"])
        self.assertTrue(any("URL 无效" in error for error in analysis.errors))

    def test_duplicate_occurrence_id_is_reported(self):
        manifest = {
            "images": [
                MANIFEST["images"][1],
                dict(MANIFEST["images"][2], occurrence_id="IMG_OCC_000002"),
            ]
        }
        analysis = analyze_special_images(MARKDOWN, manifest, urls=URLS)

        self.assertFalse(analysis.can_generate)
        self.assertEqual(analysis.counts["occurrence_id_duplicates"], 1)
        self.assertFalse(analysis.checks["occurrence_ids"]["ok"])
        self.assertTrue(
            any("occurrence_id 不唯一" in error for error in analysis.errors)
        )

    def test_unknown_special_placeholder_is_reported(self):
        markdown = MARKDOWN + "\n{{SHOWDOC_UNSUPPORTED_IMAGE_000099}}\n"
        analysis = analyze_special_images(markdown, MANIFEST, urls=URLS)

        self.assertFalse(analysis.can_generate)
        self.assertEqual(analysis.counts["unknown_placeholders"], 1)
        self.assertTrue(
            any("manifest 未包含的特殊占位符" in error for error in analysis.errors)
        )

    def test_manifest_without_special_images_is_rejected(self):
        manifest = {"images": [MANIFEST["images"][0]]}
        analysis = analyze_special_images(MARKDOWN, manifest)

        self.assertFalse(analysis.can_generate)
        self.assertTrue(any("没有特殊图片" in error for error in analysis.errors))

    def test_explicit_empty_url_clears_manifest_url(self):
        manifest = {
            "images": [
                dict(
                    MANIFEST["images"][1],
                    showdoc_url="https://doc.bizgo.com/Public/Uploads/old.png",
                )
            ]
        }
        with_manifest_url = analyze_special_images(MARKDOWN, manifest)
        self.assertEqual(
            with_manifest_url.items[0].url,
            "https://doc.bizgo.com/Public/Uploads/old.png",
        )

        cleared = analyze_special_images(
            MARKDOWN,
            manifest,
            urls={"{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}": ""},
        )
        self.assertIsNone(cleared.items[0].url)
        self.assertEqual(cleared.items[0].status, "pending")

    def test_final_check_blocks_remaining_special_placeholders(self):
        result = apply_special_images(MARKDOWN, {})

        self.assertFalse(result.final_check["passed"])
        self.assertTrue(result.errors)
        self.assertEqual(result.markdown, MARKDOWN)

    def test_updated_manifest_records_manual_urls(self):
        updated = update_special_manifest(MANIFEST, URLS)

        special = updated["images"][1]
        self.assertEqual(
            special["showdoc_url"], "https://doc.bizgo.com/Public/Uploads/emf.png"
        )
        self.assertEqual(special["upload_status"], "url_received")
        self.assertEqual(special["replacement_status"], "replaced")
        self.assertTrue(special["special_url_manual"])
        self.assertEqual(
            updated["special_replacement"],
            {"matched": 1, "pending": 2, "total": 3},
        )
        self.assertIsNone(MANIFEST["images"][1].get("showdoc_url"))


if __name__ == "__main__":
    unittest.main()
