"""Tests for importing browser-extension upload_result.json files."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fixture_builder import make_png
from w2md.cli import main as cli_main
from w2md.upload_result import (
    analyze_upload_result,
    apply_analysis,
    build_missing_rows,
    missing_images_csv,
    missing_images_html,
    replacement_report,
    thumbnails_from_files,
    write_outputs,
)


DOC_ID = "doc-0123456789abcdef0123456789abcdef"


def placeholder(sequence):
    return "{{SHOWDOC_IMAGE_%06d}}" % sequence


def occurrence(sequence):
    return "IMG_OCC_%06d" % sequence


def url_for(sequence):
    return "http://doc.bizgo.com/Public/Uploads/2026-11-16/u%06d.png" % sequence


def sha_for(sequence):
    return ("%064x" % (sequence * 7919))[-64:]


def make_manifest(count, document_id=DOC_ID):
    images = []
    for sequence in range(1, count + 1):
        images.append(
            {
                "sequence": sequence,
                "occurrence_id": occurrence(sequence),
                "placeholder": placeholder(sequence),
                "source_file": "assets/original/image%06d.png" % sequence,
                "source_format": "png",
                "source_sha256": sha_for(sequence),
                "upload_file": "assets/upload/image%06d.png" % sequence,
                "upload_format": "png",
                "upload_sha256": sha_for(sequence),
                "compatibility": "supported",
                "requires_conversion": False,
                "local_file": "assets/upload/image%06d.png" % sequence,
                "file_name": "image%06d.png" % sequence,
                "sha256": sha_for(sequence),
                "size": 1000 + sequence,
                "mime_type": "image/png",
                "alt_text": "图%d" % sequence,
                "section": "第1章",
                "context_before": "前文%d" % sequence,
                "context_after": "后文%d" % sequence,
            }
        )
    return {
        "schema_version": 1,
        "document_id": document_id,
        "source_file": "doc.docx",
        "markdown_file": "doc.md",
        "images": images,
    }


def make_markdown(count):
    return "\n\n".join(
        "第 %d 段 %s" % (sequence, placeholder(sequence))
        for sequence in range(1, count + 1)
    ) + "\n"


def make_upload_result(count, failed_sequences=(), document_id=DOC_ID, declared=True):
    failed = set(failed_sequences)
    uploads = []
    missing = []
    for sequence in range(1, count + 1):
        record = {
            "upload_id": "UPLOAD_%03d" % sequence,
            "sequence": sequence,
            "occurrence_id": occurrence(sequence),
            "placeholder": placeholder(sequence),
            "file_name": "image%06d.png" % sequence,
            "sha256": sha_for(sequence),
            "http_status": 200,
        }
        if sequence in failed:
            record.update(
                {
                    "status": "failed",
                    "response_success": 0,
                    "url": "",
                    "error": "ShowDoc 返回 success=0",
                }
            )
            missing.append(
                {
                    "sequence": sequence,
                    "occurrence_id": occurrence(sequence),
                    "placeholder": placeholder(sequence),
                    "file_name": "image%06d.png" % sequence,
                    "sha256": sha_for(sequence),
                    "status": "failed",
                    "context_before": "前文%d" % sequence,
                    "context_after": "后文%d" % sequence,
                    "reason": "ShowDoc 返回 success=0",
                }
            )
        else:
            record.update(
                {
                    "status": "success",
                    "response_success": 1,
                    "url": url_for(sequence),
                    "error": "",
                }
            )
        uploads.append(record)

    result = {
        "schema_version": 1,
        "manifest_document_id": document_id,
        "recording_started_at": "2026-11-16T10:00:00+08:00",
        "recording_stopped_at": "2026-11-16T10:20:00+08:00",
        "page_url": "http://doc.bizgo.com/web/#/1/2",
        "uploads": uploads,
        "missing": missing,
    }
    if declared:
        success = count - len(failed)
        result.update(
            {
                "expected_count": count,
                "detected_request_count": count,
                "success_unique_count": success,
                "failed_count": len(failed),
                "not_uploaded_count": 0,
                "unmatched_count": 0,
            }
        )
    return result


def final_lines(markdown):
    return [line for line in markdown.splitlines() if line.strip()]


class UploadResultImportTest(unittest.TestCase):
    def test_400_placeholders_364_success_36_failed_does_not_shift(self):
        failed = set(11 * index for index in range(1, 37))
        self.assertEqual(len(failed), 36)

        analysis = analyze_upload_result(
            make_markdown(400),
            make_upload_result(400, failed),
            make_manifest(400),
        )

        self.assertTrue(analysis.can_generate, analysis.errors)
        self.assertEqual(analysis.counts["success"], 364)
        self.assertEqual(analysis.counts["failed"], 36)
        self.assertEqual(analysis.counts["not_uploaded"], 0)
        self.assertEqual(analysis.counts["unmatched"], 0)

        outcome = apply_analysis(make_markdown(400), analysis)
        self.assertTrue(outcome.ok, outcome.post_errors)
        self.assertEqual(outcome.replaced_count, 364)

        lines = final_lines(outcome.markdown)
        self.assertEqual(len(lines), 400)
        for sequence, line in enumerate(lines, start=1):
            if sequence in failed:
                self.assertIn(placeholder(sequence), line)
                self.assertNotIn(url_for(sequence), line)
            else:
                self.assertIn("![图%d](%s)" % (sequence, url_for(sequence)), line)
                self.assertNotIn(placeholder(sequence), line)

        rows = build_missing_rows(analysis)
        self.assertEqual(len(rows), 36)
        self.assertEqual(
            [row["序号"] for row in rows], sorted(failed)
        )
        csv_text = missing_images_csv(rows)
        self.assertIn("序号,occurrence_id,占位符", csv_text)
        self.assertEqual(csv_text.count("\n"), 37)

        report = replacement_report(analysis, outcome)
        self.assertEqual(report["counts"]["failed"], 36)
        self.assertEqual(report["replacement"]["replaced_count"], 364)

    def test_second_of_four_failed_keeps_only_its_placeholder(self):
        analysis = analyze_upload_result(
            make_markdown(4),
            make_upload_result(4, {2}),
            make_manifest(4),
        )
        outcome = apply_analysis(make_markdown(4), analysis)
        self.assertTrue(outcome.ok, outcome.post_errors)

        self.assertEqual(outcome.replaced_count, 3)
        self.assertIn("![图1](%s)" % url_for(1), outcome.markdown)
        self.assertIn(placeholder(2), outcome.markdown)
        self.assertNotIn(url_for(2), outcome.markdown)
        self.assertIn("![图3](%s)" % url_for(3), outcome.markdown)
        self.assertIn("![图4](%s)" % url_for(4), outcome.markdown)

        lines = final_lines(outcome.markdown)
        self.assertNotIn(url_for(3), lines[1])
        self.assertIn(placeholder(2), lines[1])

    def test_duplicate_image_reuses_one_url_by_sha(self):
        manifest = make_manifest(3)
        manifest["images"][2]["sha256"] = manifest["images"][0]["sha256"]
        manifest["images"][2]["source_sha256"] = manifest["images"][0]["source_sha256"]
        manifest["images"][2]["upload_sha256"] = manifest["images"][0]["upload_sha256"]
        upload_result = {
            "schema_version": 1,
            "manifest_document_id": DOC_ID,
            "uploads": [
                {
                    "upload_id": "UPLOAD_001",
                    "sequence": 1,
                    "occurrence_id": occurrence(1),
                    "placeholder": placeholder(1),
                    "file_name": "image000001.png",
                    "sha256": manifest["images"][0]["sha256"],
                    "status": "success",
                    "http_status": 200,
                    "response_success": 1,
                    "url": url_for(1),
                }
            ],
            "missing": [],
        }

        analysis = analyze_upload_result(make_markdown(3), upload_result, manifest)
        self.assertEqual(analysis.counts["success"], 2)
        self.assertEqual(analysis.counts["reused_by_sha"], 1)

        outcome = apply_analysis(make_markdown(3), analysis)
        self.assertEqual(outcome.replaced_count, 2)
        self.assertEqual(outcome.markdown.count(url_for(1)), 2)
        self.assertNotIn(placeholder(1), outcome.markdown)
        self.assertNotIn(placeholder(3), outcome.markdown)
        self.assertIn(placeholder(2), outcome.markdown)

    def test_local_file_without_upload_record_is_not_uploaded(self):
        upload_result = make_upload_result(3)
        upload_result["uploads"] = upload_result["uploads"][:2]
        upload_result["missing"] = []
        upload_result["detected_request_count"] = 2
        upload_result["success_unique_count"] = 2

        analysis = analyze_upload_result(make_markdown(3), upload_result, make_manifest(3))

        self.assertEqual(analysis.counts["not_uploaded"], 1)
        image = analysis.images[2]
        self.assertEqual(image.upload_status, "not_uploaded")
        self.assertEqual(image.local_file, "assets/upload/image000003.png")
        self.assertTrue(any("数量不足" in warning for warning in analysis.warnings))

        outcome = apply_analysis(make_markdown(3), analysis)
        self.assertIn(placeholder(3), outcome.markdown)
        self.assertEqual(len(build_missing_rows(analysis)), 1)

    def test_http_200_but_response_success_zero_is_failed(self):
        upload_result = make_upload_result(2)
        upload_result["uploads"][0].update(
            {
                "status": "success",
                "http_status": 200,
                "response_success": 0,
                "url": url_for(1),
            }
        )

        analysis = analyze_upload_result(make_markdown(2), upload_result, make_manifest(2))

        self.assertEqual(analysis.images[0].upload_status, "failed")
        self.assertIn("success=0", analysis.images[0].reason)
        self.assertEqual(analysis.images[1].upload_status, "success")
        outcome = apply_analysis(make_markdown(2), analysis)
        self.assertNotIn(url_for(1), outcome.markdown)
        self.assertIn(placeholder(1), outcome.markdown)

    def test_placeholder_inside_code_block_is_not_replaced(self):
        markdown = (
            "正文 %s\n\n"
            "```text\n%s\n```\n\n"
            "行内 `%s` 和正文 %s\n"
            % (placeholder(1), placeholder(2), placeholder(3), placeholder(4))
        )
        upload_result = make_upload_result(4)

        analysis = analyze_upload_result(markdown, upload_result, make_manifest(4))
        self.assertEqual(analysis.counts["code_block_placeholders"], 2)

        outcome = apply_analysis(markdown, analysis)
        self.assertEqual(outcome.replaced_count, 2)
        self.assertNotIn("```text\n![图2]", outcome.markdown)
        self.assertIn("```text\n" + placeholder(2) + "\n```", outcome.markdown)
        self.assertIn("`" + placeholder(3) + "`", outcome.markdown)
        self.assertIn("![图4](%s)" % url_for(4), outcome.markdown)

    def test_short_upload_result_reports_detailed_difference_without_pretending(self):
        upload_result = make_upload_result(10)
        upload_result["uploads"] = upload_result["uploads"][:6]
        upload_result["missing"] = upload_result["missing"][:0]
        upload_result["detected_request_count"] = 10
        upload_result["success_unique_count"] = 6
        upload_result["failed_count"] = 0

        analysis = analyze_upload_result(
            make_markdown(10), upload_result, make_manifest(10)
        )

        self.assertEqual(analysis.counts["success"], 6)
        self.assertEqual(analysis.counts["not_uploaded"], 4)
        self.assertTrue(analysis.requires_confirmation)
        self.assertTrue(any("数量不足" in warning for warning in analysis.warnings))
        self.assertTrue(
            any("detected_request_count" in item for item in analysis.declared_differences)
        )

        strict = analyze_upload_result(
            make_markdown(10), upload_result, make_manifest(10), mode="strict"
        )
        self.assertFalse(strict.can_generate)
        self.assertTrue(any("严格模式" in error for error in strict.errors))

    def test_document_id_mismatch_blocks_until_explicitly_allowed(self):
        upload_result = make_upload_result(2, document_id="doc-ffffffffffffffffffffffffffffffff")

        blocked = analyze_upload_result(
            make_markdown(2), upload_result, make_manifest(2)
        )
        self.assertFalse(blocked.can_generate)
        self.assertTrue(any("document_id 不一致" in error for error in blocked.errors))

        allowed = analyze_upload_result(
            make_markdown(2),
            upload_result,
            make_manifest(2),
            allow_mismatch=True,
        )
        self.assertTrue(allowed.can_generate, allowed.errors)
        self.assertTrue(any("document_id 不一致" in warning for warning in allowed.warnings))

    def test_hash_mismatch_requires_confirmation_and_is_not_replaced(self):
        upload_result = make_upload_result(2)
        upload_result["uploads"][0]["sha256"] = "f" * 64

        blocked = analyze_upload_result(
            make_markdown(2), upload_result, make_manifest(2)
        )
        self.assertFalse(blocked.can_generate)
        self.assertTrue(blocked.images[0].needs_review)
        self.assertTrue(any("不一致" in error for error in blocked.errors))

        allowed = analyze_upload_result(
            make_markdown(2),
            upload_result,
            make_manifest(2),
            allow_mismatch=True,
        )
        self.assertTrue(allowed.can_generate, allowed.errors)
        outcome = apply_analysis(make_markdown(2), allowed)
        self.assertIn(placeholder(1), outcome.markdown)
        self.assertNotIn(url_for(1), outcome.markdown)
        self.assertIn("![图2](%s)" % url_for(2), outcome.markdown)
        self.assertEqual(allowed.images[0].upload_status, "unmatched")

    def test_unexpected_upload_is_reported(self):
        upload_result = make_upload_result(1)
        upload_result["uploads"].append(
            {
                "upload_id": "UPLOAD_999",
                "sequence": 99,
                "occurrence_id": occurrence(99),
                "placeholder": placeholder(99),
                "file_name": "other.png",
                "sha256": "a" * 64,
                "status": "success",
                "http_status": 200,
                "response_success": 1,
                "url": url_for(99),
            }
        )
        upload_result["detected_request_count"] = 2
        upload_result["success_unique_count"] = 2
        upload_result["unexpected_upload_count"] = 1

        analysis = analyze_upload_result(make_markdown(1), upload_result, make_manifest(1))

        self.assertEqual(analysis.counts["unexpected_upload"], 1)
        rows = build_missing_rows(analysis)
        self.assertEqual(rows[0]["状态"], "unexpected_upload")
        self.assertTrue(analysis.can_generate)

    def test_fill_remaining_only_touches_remaining_placeholders(self):
        # Images 1 and 2 were already replaced; only 3 and 4 are left.
        markdown = (
            "![图1](%s)\n\n![图2](%s)\n\n第3段 %s\n\n第4段 %s\n"
            % (url_for(1), url_for(2), placeholder(3), placeholder(4))
        )
        upload_result = {
            "schema_version": 1,
            "manifest_document_id": DOC_ID,
            "expected_count": 2,
            "detected_request_count": 2,
            "uploads": [
                {
                    "upload_id": "UPLOAD_003",
                    "sequence": 3,
                    "occurrence_id": occurrence(3),
                    "placeholder": placeholder(3),
                    "sha256": sha_for(3),
                    "status": "success",
                    "http_status": 200,
                    "response_success": 1,
                    "url": url_for(3),
                },
                {
                    "upload_id": "UPLOAD_004",
                    "sequence": 4,
                    "occurrence_id": occurrence(4),
                    "placeholder": placeholder(4),
                    "sha256": sha_for(4),
                    "status": "success",
                    "http_status": 200,
                    "response_success": 1,
                    "url": url_for(4),
                },
            ],
            "missing": [],
        }

        analysis = analyze_upload_result(
            markdown,
            upload_result,
            make_manifest(4),
            mode="fill_remaining",
        )

        self.assertEqual(analysis.counts["target_images"], 2)
        self.assertEqual(analysis.counts["success"], 2)
        self.assertEqual(analysis.counts["fill_remaining_out_of_scope"], 2)
        self.assertTrue(analysis.can_generate, analysis.errors)

        outcome = apply_analysis(markdown, analysis)
        self.assertEqual(outcome.replaced_count, 2)
        self.assertIn("![图3](%s)" % url_for(3), outcome.markdown)
        self.assertIn("![图4](%s)" % url_for(4), outcome.markdown)
        self.assertIn("![图1](%s)" % url_for(1), outcome.markdown)
        self.assertIn("![图2](%s)" % url_for(2), outcome.markdown)

    def test_strict_mode_passes_when_everything_succeeded(self):
        analysis = analyze_upload_result(
            make_markdown(3),
            make_upload_result(3),
            make_manifest(3),
            mode="strict",
        )
        self.assertTrue(analysis.can_generate, analysis.errors)
        self.assertFalse(analysis.requires_confirmation)
        outcome = apply_analysis(make_markdown(3), analysis)
        self.assertEqual(outcome.replaced_count, 3)
        self.assertEqual(outcome.remaining_placeholders, [])

    def test_upload_record_with_only_sha256_matches_unique_image(self):
        manifest = make_manifest(2)
        upload_result = {
            "schema_version": 1,
            "manifest_document_id": DOC_ID,
            "uploads": [
                {
                    "upload_id": "UPLOAD_ONLY_HASH",
                    "sha256": sha_for(1),
                    "status": "success",
                    "http_status": 200,
                    "response_success": 1,
                    "url": url_for(1),
                }
            ],
            "missing": [],
        }

        analysis = analyze_upload_result(make_markdown(2), upload_result, manifest)

        self.assertEqual(analysis.uploads[0].match_kind, "sha256")
        self.assertEqual(analysis.images[0].upload_status, "success")
        self.assertEqual(analysis.images[1].upload_status, "not_uploaded")
        outcome = apply_analysis(make_markdown(2), analysis)
        self.assertIn("![图1](%s)" % url_for(1), outcome.markdown)
        self.assertIn(placeholder(2), outcome.markdown)

    def test_urls_complete_out_of_order_but_map_by_occurrence_hash(self):
        manifest = make_manifest(4)
        for image in manifest["images"]:
            sequence = image["sequence"]
            image.update(
                {
                    "source_file": "assets/original/image%06d.png" % sequence,
                    "source_format": "png",
                    "source_sha256": image["sha256"],
                    "upload_file": "assets/upload/image%06d.png" % sequence,
                    "upload_format": "png",
                    "upload_sha256": image["sha256"],
                    "compatibility": "supported",
                    "requires_conversion": False,
                }
            )
        # Completion order is 3, 1, 4, 2; URLs are deliberately unrelated to
        # sequence numbers.  Mapping must come from occurrence_id/hash only.
        uploads = [
            {
                "upload_id": "UPLOAD_003",
                "sequence": 3,
                "occurrence_id": occurrence(3),
                "placeholder": placeholder(3),
                "sha256": sha_for(3),
                "status": "success",
                "http_status": 200,
                "response_success": 1,
                "url": "http://doc.bizgo.com/Public/Uploads/late-small.png",
            },
            {
                "upload_id": "UPLOAD_001",
                "sequence": 1,
                "occurrence_id": occurrence(1),
                "placeholder": placeholder(1),
                "sha256": sha_for(1),
                "status": "success",
                "http_status": 200,
                "response_success": 1,
                "url": "http://doc.bizgo.com/Public/Uploads/early-large.png",
            },
            {
                "upload_id": "UPLOAD_004",
                "sequence": 4,
                "occurrence_id": occurrence(4),
                "placeholder": placeholder(4),
                "sha256": sha_for(4),
                "status": "success",
                "http_status": 200,
                "response_success": 1,
                "url": "http://doc.bizgo.com/Public/Uploads/fourth.png",
            },
            {
                "upload_id": "UPLOAD_002",
                "sequence": 2,
                "occurrence_id": occurrence(2),
                "placeholder": placeholder(2),
                "sha256": sha_for(2),
                "status": "success",
                "http_status": 200,
                "response_success": 1,
                "url": "http://doc.bizgo.com/Public/Uploads/second.png",
            },
        ]
        result = {
            "schema_version": 1,
            "manifest_document_id": DOC_ID,
            "uploads": uploads,
            "missing": [],
        }

        analysis = analyze_upload_result(make_markdown(4), result, manifest)
        outcome = apply_analysis(make_markdown(4), analysis)
        lines = final_lines(outcome.markdown)

        self.assertIn("early-large.png", lines[0])
        self.assertIn("second.png", lines[1])
        self.assertIn("late-small.png", lines[2])
        self.assertIn("fourth.png", lines[3])

    def test_converted_image_matches_upload_sha_and_special_stays(self):
        manifest = make_manifest(4)
        manifest["images"][1].update(
            {
                "compatibility": "conversion_failed",
                "placeholder": "{{SHOWDOC_CONVERSION_FAILED_IMAGE_000002}}",
                "source_file": "assets/original/image000002.emf",
                "source_format": "emf",
                "source_sha256": sha_for(2),
                "upload_file": None,
                "upload_sha256": None,
                "requires_conversion": True,
                "compatibility_reason": "EMF 转换失败",
            }
        )
        manifest["images"][2].update(
            {
                "compatibility": "converted",
                "source_file": "assets/original/image000003.emf",
                "source_format": "emf",
                "source_sha256": "c" * 64,
                "upload_file": "assets/upload/image000003.png",
                "upload_format": "png",
                "upload_sha256": "d" * 64,
                "requires_conversion": True,
            }
        )
        markdown = (
            "第1段 %s\n\n第2段 {{SHOWDOC_CONVERSION_FAILED_IMAGE_000002}}\n\n"
            "第3段 %s\n\n第4段 %s\n"
            % (placeholder(1), placeholder(3), placeholder(4))
        )

        uploads = [
            {
                "upload_id": "UPLOAD_001",
                "sequence": 1,
                "occurrence_id": occurrence(1),
                "placeholder": placeholder(1),
                "sha256": sha_for(1),
                "status": "success",
                "response_success": 1,
                "url": "http://doc.bizgo.com/Public/Uploads/one.png",
            },
            {
                "upload_id": "UPLOAD_003",
                "sequence": 3,
                "occurrence_id": occurrence(3),
                "placeholder": placeholder(3),
                "sha256": "d" * 64,  # hash of the converted PNG upload copy
                "status": "success",
                "response_success": 1,
                "url": "http://doc.bizgo.com/Public/Uploads/converted-three.png",
            },
            {
                "upload_id": "UPLOAD_004",
                "sequence": 4,
                "occurrence_id": occurrence(4),
                "placeholder": placeholder(4),
                "sha256": sha_for(4),
                "status": "failed",
                "response_success": 0,
                "url": "",
                "error": "ShowDoc 返回 success=0",
            },
            {
                "upload_id": "UPLOAD_SPECIAL",
                "sequence": 2,
                "occurrence_id": occurrence(2),
                "placeholder": "{{SHOWDOC_CONVERSION_FAILED_IMAGE_000002}}",
                "sha256": sha_for(2),
                "status": "success",
                "response_success": 1,
                "url": "http://doc.bizgo.com/Public/Uploads/should-not-be-used.png",
            },
        ]
        result = {
            "schema_version": 1,
            "manifest_document_id": DOC_ID,
            "uploads": uploads,
            "missing": [],
        }

        analysis = analyze_upload_result(markdown, result, manifest)
        self.assertTrue(analysis.can_generate, analysis.errors)
        self.assertEqual(analysis.counts["converted"], 1)
        self.assertEqual(analysis.counts["conversion_failed"], 1)
        self.assertEqual(analysis.counts["ignored_special_uploads"], 1)
        self.assertEqual(analysis.images[1].upload_status, "conversion_failed")

        outcome = apply_analysis(markdown, analysis)
        self.assertIn("one.png", outcome.markdown)
        self.assertIn("converted-three.png", outcome.markdown)
        self.assertNotIn("should-not-be-used.png", outcome.markdown)
        self.assertIn("{{SHOWDOC_CONVERSION_FAILED_IMAGE_000002}}", outcome.markdown)
        self.assertIn(placeholder(4), outcome.markdown)
        self.assertEqual(outcome.replaced_count, 2)

    def test_pending_and_interrupted_are_not_success(self):
        upload_result = make_upload_result(2)
        upload_result["uploads"][0]["status"] = "pending"
        upload_result["uploads"][1]["status"] = "interrupted"

        analysis = analyze_upload_result(
            make_markdown(2), upload_result, make_manifest(2)
        )

        self.assertEqual(analysis.images[0].upload_status, "pending")
        self.assertEqual(analysis.images[1].upload_status, "interrupted")
        self.assertEqual(analysis.counts["success"], 0)
        self.assertFalse(analysis.can_generate)
        self.assertTrue(any("成功 URL" in error for error in analysis.errors))

    def test_strict_mode_rejects_special_placeholders(self):
        manifest = make_manifest(2)
        manifest["images"][1].update(
            {
                "compatibility": "unsupported",
                "placeholder": "{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}",
                "upload_file": None,
                "upload_sha256": None,
                "source_format": "svg",
            }
        )
        markdown = "第一段 %s\n\n第二段 {{SHOWDOC_UNSUPPORTED_IMAGE_000002}}\n" % placeholder(1)
        upload_result = {
            "schema_version": 1,
            "manifest_document_id": DOC_ID,
            "uploads": [
                {
                    "upload_id": "UPLOAD_001",
                    "sequence": 1,
                    "occurrence_id": occurrence(1),
                    "placeholder": placeholder(1),
                    "sha256": sha_for(1),
                    "status": "success",
                    "response_success": 1,
                    "url": url_for(1),
                }
            ],
            "missing": [],
        }

        analysis = analyze_upload_result(
            markdown, upload_result, manifest, mode="strict"
        )
        self.assertFalse(analysis.can_generate)
        self.assertTrue(
            any("严格模式不允许存在特殊占位符" in error for error in analysis.errors)
        )

    def test_new_csv_columns_include_source_and_upload_paths(self):
        analysis = analyze_upload_result(
            make_markdown(2),
            make_upload_result(2, {2}),
            make_manifest(2),
        )
        csv_text = missing_images_csv(build_missing_rows(analysis))
        header = csv_text.splitlines()[0]
        for column in (
            "原始文件名",
            "原始路径",
            "上传文件名",
            "上传路径",
            "SHA-256",
            "状态",
            "失败原因",
        ):
            self.assertIn(column, header)

    def test_missing_upload_result_is_an_explicit_error(self):
        analysis = analyze_upload_result(make_markdown(1), None, make_manifest(1))

        self.assertFalse(analysis.can_generate)
        self.assertTrue(any("upload_result.json" in error for error in analysis.errors))

    def test_manifest_is_optional_but_reported(self):
        analysis = analyze_upload_result(
            make_markdown(2), make_upload_result(2), None
        )

        self.assertTrue(analysis.can_generate, analysis.errors)
        self.assertTrue(analysis.synthesized_manifest)
        self.assertTrue(any("未提供 manifest" in warning for warning in analysis.warnings))
        self.assertEqual(analysis.counts["manifest_images"], 0)
        outcome = apply_analysis(make_markdown(2), analysis)
        self.assertEqual(outcome.replaced_count, 2)

    def test_cli_writes_final_markdown_csv_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            markdown_path = tmp / "doc.md"
            upload_path = tmp / "upload_result.json"
            manifest_path = tmp / "manifest.json"
            output_dir = tmp / "out"

            markdown_path.write_text(make_markdown(3), encoding="utf-8")
            upload_path.write_text(
                json.dumps(make_upload_result(3, {2}), ensure_ascii=False),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(make_manifest(3), ensure_ascii=False),
                encoding="utf-8",
            )
            original = markdown_path.read_text(encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = cli_main(
                    [
                        "apply-upload-result",
                        str(markdown_path),
                        "--upload-result",
                        str(upload_path),
                        "--manifest",
                        str(manifest_path),
                        "-o",
                        str(output_dir),
                        "--mode",
                        "partial",
                        "--confirm-partial",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertIn("replaced 2", stdout.getvalue())
            self.assertEqual(markdown_path.read_text(encoding="utf-8"), original)

            final_files = list(output_dir.glob("final_markdown_*.md"))
            self.assertEqual(len(final_files), 1)
            final = final_files[0].read_text(encoding="utf-8")
            self.assertIn("![图1](" + url_for(1) + ")", final)
            self.assertIn(placeholder(2), final)
            self.assertIn("![图3](" + url_for(3) + ")", final)

            csv_text = (output_dir / "missing_images.csv").read_text(
                encoding="utf-8-sig"
            )
            self.assertEqual(len(csv_text.strip().splitlines()), 2)
            self.assertIn("IMG_OCC_000002", csv_text)

            report = json.loads(
                (output_dir / "replacement_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["replacement"]["replaced_count"], 2)
            self.assertEqual(report["counts"]["failed"], 1)
            self.assertTrue((output_dir / "missing_images.html").is_file())

    def test_cli_requires_confirmation_for_partial_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            markdown_path = tmp / "doc.md"
            upload_path = tmp / "upload_result.json"
            manifest_path = tmp / "manifest.json"
            markdown_path.write_text(make_markdown(2), encoding="utf-8")
            upload_path.write_text(
                json.dumps(make_upload_result(2, {1}), ensure_ascii=False),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(make_manifest(2), ensure_ascii=False),
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                code = cli_main(
                    [
                        "apply-upload-result",
                        str(markdown_path),
                        "--upload-result",
                        str(upload_path),
                        "--manifest",
                        str(manifest_path),
                        "-o",
                        str(tmp / "out"),
                    ]
                )

            self.assertEqual(code, 2)
            self.assertFalse((tmp / "out").exists())

    def test_crlf_line_endings_survive_replacement_and_file_write(self):
        markdown = (
            "第一段 %s\r\n\r\n第二段 %s\r\n" % (placeholder(1), placeholder(2))
        )
        analysis = analyze_upload_result(
            markdown, make_upload_result(2), make_manifest(2)
        )
        outcome = apply_analysis(markdown, analysis)
        self.assertIn("第一段 ![图1](%s)\r\n" % url_for(1), outcome.markdown)
        self.assertNotIn("\r\r\n", outcome.markdown)

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_outputs(
                tmp, outcome.markdown, analysis, outcome, include_html=False
            )
            raw = paths["markdown"].read_bytes()
        self.assertNotIn(b"\r\r\n", raw)
        self.assertIn(b"\r\n", raw)

    def test_cli_embeds_local_thumbnails_in_html_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            assets = tmp / "assets"
            (assets / "upload").mkdir(parents=True)
            (assets / "upload" / "image000002.png").write_bytes(make_png(20, 10))

            manifest = make_manifest(3)
            markdown = make_markdown(3)
            upload_result = make_upload_result(3, {2})

            analysis = analyze_upload_result(markdown, upload_result, manifest)
            thumbnails = thumbnails_from_files(analysis, [tmp])
            self.assertIn(placeholder(2), thumbnails)
            self.assertTrue(thumbnails[placeholder(2)].startswith("data:image/png;base64,"))

            outcome = apply_analysis(markdown, analysis)
            paths = write_outputs(
                tmp / "out",
                outcome.markdown,
                analysis,
                outcome,
                thumbnails=thumbnails,
            )
            page = paths["html"].read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", page)
            self.assertIn(placeholder(2), page)

    def test_html_report_rejects_non_image_thumbnail_payload(self):
        analysis = analyze_upload_result(
            make_markdown(1), make_upload_result(1, {1}), make_manifest(1)
        )
        page = missing_images_html(
            analysis,
            thumbnails={placeholder(1): "javascript:alert(1)"},
        )
        self.assertNotIn("javascript:", page)
        self.assertIn("无缩略图", page)

    def test_manual_placeholder_deletion_is_reported_not_restored(self):
        manifest = make_manifest(3)
        markdown = "第1段 %s\n\n第3段 %s\n" % (placeholder(1), placeholder(3))
        upload_result = make_upload_result(3)

        analysis = analyze_upload_result(markdown, upload_result, manifest)

        self.assertEqual(analysis.counts["manifest_not_in_markdown"], 1)
        image = analysis.images[1]
        self.assertFalse(image.in_markdown)
        outcome = apply_analysis(markdown, analysis)
        self.assertEqual(outcome.replaced_count, 2)
        self.assertNotIn(placeholder(2), outcome.markdown)
        self.assertNotIn("![图2]", outcome.markdown)


if __name__ == "__main__":
    unittest.main()
