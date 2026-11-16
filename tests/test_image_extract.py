"""Tests for document-order DOCX image extraction and ShowDoc placeholders."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fixture_builder import make_png
from w2md.config import Config
from w2md.image_extract import _prepare_image, extract_docx_images
from w2md.pipeline import convert
from w2md.upload_result import analyze_upload_result, apply_analysis


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="emf" ContentType="image/x-emf"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdA" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/>
  <Relationship Id="rIdB" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/b.png"/>
  <Relationship Id="rIdC" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/c.png"/>
  <Relationship Id="rIdD" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/d.emf"/>
</Relationships>"""


def drawing(rid, description=None, image_id=1):
    description_attr = ' descr="{0}"'.format(description) if description else ""
    return (
        "<w:drawing><wp:inline><wp:extent cx=\"100\" cy=\"100\"/>"
        "<wp:docPr id=\"{0}\" name=\"图片 {0}\"{1}/>"
        "<a:graphic><a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        "<pic:pic><pic:nvPicPr><pic:cNvPr id=\"{0}\" name=\"图片 {0}\"/><pic:cNvPicPr/></pic:nvPicPr>"
        "<pic:blipFill><a:blip r:embed=\"{2}\"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        "<pic:spPr/></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>"
    ).format(image_id, description_attr, rid)


def vml(rid, alt):
    return '<w:pict><v:shape alt="{0}"><v:imagedata r:id="{1}"/></v:shape></w:pict>'.format(alt, rid)


DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
    xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
    xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
    xmlns:v="urn:schemas-microsoft-com:vml">
  <w:body>
    <w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>章节一</w:t></w:r></w:p>
    <w:p><w:r><w:t>正文开始</w:t></w:r><w:r>{drawing_a}</w:r></w:p>
    <w:tbl>
      <w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>
      <w:tr>
        <w:tc><w:p><w:r><w:t>说明</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r>{drawing_b}</w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>数量</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>采购数量</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p>
      <w:r>{drawing_a_again}</w:r>
      <w:r>{vml_c}</w:r>
    </w:p>
    <w:p><w:r>{drawing_d}</w:r></w:p>
    <w:p><w:r><w:t>图 4 兼容格式</w:t></w:r></w:p>
    <w:p><w:r>{drawing_missing}</w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>""".format(
    drawing_a=drawing("rIdA", "架构图", 1),
    drawing_b=drawing("rIdB", "表格图", 2),
    drawing_a_again=drawing("rIdA", "架构图", 3),
    vml_c=vml("rIdC", "VML示意图"),
    drawing_d=drawing("rIdD", None, 4),
    drawing_missing=drawing("rIdMissing", "缺失图片", 5),
)

# PyMuPDF sniffs the real bytes, so PNG content stored under an .emf media
# part exercises the EMF conversion path without depending on a binary EMF
# fixture.  The original .emf bytes are still preserved byte-for-byte.
EMF_BYTES = make_png(120, 90)

ALTERNATE_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
    xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
    xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
    xmlns:v="urn:schemas-microsoft-com:vml"
    xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">
  <w:body>
    <w:p><w:r>
      <mc:AlternateContent>
        <mc:Choice Requires="wps">{drawing_a}</mc:Choice>
        <mc:Fallback><w:pict><v:shape alt="回退图"><v:imagedata r:id="rIdA"/></v:shape></w:pict></mc:Fallback>
      </mc:AlternateContent>
    </w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>""".format(drawing_a=drawing("rIdA", "首选图", 1))


def build_fixture(path):
    png_a = make_png(8, 6)
    png_b = make_png(9, 7)
    png_c = make_png(10, 8)
    png_unused = make_png(3, 3)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("word/document.xml", DOCUMENT_XML)
        archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        archive.writestr("word/media/a.png", png_a)
        archive.writestr("word/media/b.png", png_b)
        archive.writestr("word/media/c.png", png_c)
        archive.writestr("word/media/d.emf", EMF_BYTES)
        archive.writestr("word/media/unused.png", png_unused)
    return {"a": png_a, "b": png_b, "c": png_c, "unused": png_unused}


class ImageExtractionTest(unittest.TestCase):
    def test_placeholder_mode_extracts_in_body_order_and_verifies_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "order.docx"
            media = build_fixture(docx)

            report, md_path = convert(docx, tmp, config=Config(assets_mode="placeholder"))
            markdown = md_path.read_text(encoding="utf-8")
            manifest = json.loads((tmp / "assets" / "manifest.json").read_text(encoding="utf-8"))

            placeholders = ["{{SHOWDOC_IMAGE_%06d}}" % index for index in range(1, 6)]
            placeholders.append("{{SHOWDOC_CONVERSION_FAILED_IMAGE_000006}}")
            positions = [markdown.index(placeholder) for placeholder in placeholders]
            self.assertEqual(positions, sorted(positions))
            self.assertNotIn("data:image", markdown)
            self.assertNotIn("assets/", markdown)
            self.assertIn("| 说明 | {{SHOWDOC_IMAGE_000002}} |", markdown)

            images = manifest["images"]
            self.assertEqual([image["placeholder"] for image in images], placeholders)
            self.assertEqual([image["order"] for image in images], list(range(1, 7)))
            self.assertEqual([image["sequence"] for image in images], list(range(1, 7)))
            self.assertEqual(
                [image["occurrence_id"] for image in images],
                ["IMG_OCC_%06d" % index for index in range(1, 7)],
            )
            self.assertEqual(len(set(image["occurrence_id"] for image in images)), 6)
            self.assertTrue(manifest["document_id"].startswith("doc-"))
            self.assertEqual(len(manifest["document_id"]), 4 + 32)
            self.assertEqual(manifest["source_file"], "order.docx")
            self.assertEqual(manifest["markdown_file"], "order.md")
            self.assertTrue(manifest["created_at"])

            first = images[0]
            self.assertEqual(first["compatibility"], "supported")
            self.assertFalse(first["requires_conversion"])
            self.assertEqual(first["source_file"], "assets/original/order-image-000001.png")
            self.assertEqual(first["upload_file"], "assets/upload/order-image-000001.png")
            self.assertEqual(first["file_name"], "order-image-000001.png")
            self.assertEqual(first["local_file"], "assets/upload/order-image-000001.png")
            self.assertEqual(first["source_format"], "png")
            self.assertEqual(first["upload_format"], "png")
            self.assertEqual(first["section"], "章节一")
            self.assertEqual(first["context_before"], "正文开始")
            self.assertEqual(first["context_after"], "说明")
            self.assertEqual(first["source_part"], "word/media/a.png")
            self.assertEqual(first["relationship_id"], "rIdA")
            self.assertEqual(first["local_path"], "assets/upload/order-image-000001.png")
            self.assertEqual(first["extension"], ".png")
            self.assertEqual(first["mime_type"], "image/png")
            self.assertEqual(first["alt_text"], "架构图")
            self.assertEqual(first["alt_source"], "docPr:descr")
            self.assertTrue(first["sha256_verified"])
            self.assertEqual(first["source_sha256"], hashlib.sha256(media["a"]).hexdigest())
            self.assertEqual(first["sha256"], first["source_sha256"])
            self.assertEqual(first["upload_sha256"], first["source_sha256"])
            self.assertEqual(
                (tmp / "assets" / "original" / "order-image-000001.png").read_bytes(),
                media["a"],
            )
            self.assertEqual(
                (tmp / "assets" / "upload" / "order-image-000001.png").read_bytes(),
                media["a"],
            )
            self.assertIsNone(first["showdoc_url"])
            self.assertEqual(first["upload_status"], "not_uploaded")
            self.assertEqual(first["replacement_status"], "pending")

            self.assertEqual(images[1]["alt_text"], "表格图")
            self.assertEqual(images[1]["source_part"], "word/media/b.png")

            duplicate = images[2]
            self.assertTrue(duplicate["is_duplicate"])
            self.assertEqual(duplicate["duplicate_of"], placeholders[0])
            self.assertEqual(duplicate["local_path"], first["local_path"])
            self.assertEqual(duplicate["upload_file"], first["upload_file"])

            vml_image = images[3]
            self.assertEqual(vml_image["alt_text"], "VML示意图")
            self.assertEqual(vml_image["alt_source"], "vml:alt")
            self.assertEqual(vml_image["source_part"], "word/media/c.png")

            emf = images[4]
            self.assertEqual(emf["compatibility"], "converted")
            self.assertTrue(emf["requires_conversion"])
            self.assertEqual(emf["status"], "compatibility")
            self.assertEqual(emf["alt_text"], "图 4 兼容格式")
            self.assertEqual(emf["alt_source"], "caption")
            self.assertEqual(emf["source_format"], "emf")
            self.assertEqual(emf["upload_format"], "png")
            self.assertEqual(emf["source_file"], "assets/original/order-image-000005.emf")
            self.assertEqual(emf["upload_file"], "assets/upload/order-image-000005.png")
            self.assertEqual(
                (tmp / "assets" / "original" / "order-image-000005.emf").read_bytes(),
                EMF_BYTES,
            )
            upload_bytes = (
                tmp / "assets" / "upload" / "order-image-000005.png"
            ).read_bytes()
            self.assertTrue(upload_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(emf["source_sha256"], hashlib.sha256(EMF_BYTES).hexdigest())
            self.assertEqual(emf["upload_sha256"], hashlib.sha256(upload_bytes).hexdigest())
            self.assertNotEqual(emf["source_sha256"], emf["upload_sha256"])
            self.assertEqual(emf["preview_status"], "generated")

            missing = images[5]
            self.assertEqual(missing["status"], "failed")
            self.assertEqual(missing["compatibility"], "conversion_failed")
            self.assertEqual(
                missing["placeholder"], "{{SHOWDOC_CONVERSION_FAILED_IMAGE_000006}}"
            )
            self.assertIn("rIdMissing", missing["error"])

            self.assertEqual(manifest["summary"]["occurrences"], 6)
            self.assertEqual(manifest["summary"]["unique_media"], 4)
            self.assertEqual(manifest["summary"]["duplicates"], 1)
            self.assertEqual(manifest["summary"]["supported"], 4)
            self.assertEqual(manifest["summary"]["converted"], 1)
            self.assertEqual(manifest["summary"]["conversion_failed"], 1)
            self.assertEqual(manifest["summary"]["special"], 1)
            self.assertEqual(manifest["summary"]["failed"], 1)
            self.assertEqual(manifest["summary"]["compatibility"], 1)
            self.assertEqual(len(manifest["unreferenced_media"]), 1)
            self.assertEqual(manifest["unreferenced_media"][0]["part"], "word/media/unused.png")
            self.assertTrue(any(error["kind"] == "image_failed" for error in manifest["errors"]))

            self.assertEqual(report.stats["image_occurrences"], 6)
            self.assertEqual(report.stats["image_unique_media"], 4)
            self.assertEqual(report.stats["image_duplicates"], 1)
            self.assertEqual(report.stats["image_failed"], 1)
            self.assertEqual(report.stats["image_converted"], 1)
            self.assertEqual(report.stats["image_conversion_failed"], 1)
            self.assertEqual(report.stats["image_placeholders"], 6)
            self.assertTrue(any(w.kind == "image_converted" for w in report.warnings))
            self.assertTrue(any(w.kind == "image_unreferenced" for w in report.warnings))

    def test_converted_emf_uses_upload_sha_for_replacement_and_keeps_special(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "order.docx"
            build_fixture(docx)

            report, md_path = convert(docx, tmp, config=Config(assets_mode="placeholder"))
            markdown = md_path.read_text(encoding="utf-8")
            manifest = json.loads((tmp / "assets" / "manifest.json").read_text(encoding="utf-8"))
            images = manifest["images"]

            converted = [
                image for image in images if image["compatibility"] == "converted"
            ]
            self.assertEqual(len(converted), 1)
            converted = converted[0]
            self.assertEqual(converted["source_format"], "emf")
            self.assertEqual(converted["upload_format"], "png")
            self.assertNotEqual(converted["source_sha256"], converted["upload_sha256"])
            self.assertTrue(
                (tmp / "assets" / "original" / "order-image-000005.emf").is_file()
            )
            self.assertTrue(
                (tmp / "assets" / "upload" / "order-image-000005.png").is_file()
            )

            uploads = []
            urls = {}
            for image in images:
                if image["compatibility"] in ("supported", "converted"):
                    url = "http://doc.bizgo.com/Public/Uploads/u%06d.png" % image["sequence"]
                    urls[image["placeholder"]] = url
                    uploads.append(
                        {
                            "upload_id": "UPLOAD_%03d" % image["sequence"],
                            "sequence": image["sequence"],
                            "occurrence_id": image["occurrence_id"],
                            "placeholder": image["placeholder"],
                            "file_name": image["file_name"],
                            # The extension hashes the actual upload copy.
                            "sha256": image["upload_sha256"],
                            "status": "success",
                            "http_status": 200,
                            "response_success": 1,
                            "url": url,
                        }
                    )
            upload_result = {
                "schema_version": 1,
                "manifest_document_id": manifest["document_id"],
                "expected_count": len(uploads),
                "detected_request_count": len(uploads),
                "success_unique_count": len(uploads),
                "failed_count": 0,
                "not_uploaded_count": 0,
                "unmatched_count": 0,
                "uploads": uploads,
                "missing": [],
            }

            analysis = analyze_upload_result(markdown, upload_result, manifest)
            self.assertTrue(analysis.can_generate, analysis.errors)
            self.assertEqual(analysis.counts["converted"], 1)
            self.assertEqual(analysis.counts["conversion_failed"], 1)
            outcome = apply_analysis(markdown, analysis)
            self.assertTrue(outcome.ok, outcome.post_errors)
            self.assertIn(urls[converted["placeholder"]], outcome.markdown)
            self.assertNotIn(converted["placeholder"], outcome.markdown)
            self.assertIn("{{SHOWDOC_CONVERSION_FAILED_IMAGE_000006}}", outcome.markdown)
            self.assertEqual(
                (tmp / "assets" / "original" / "order-image-000005.emf").read_bytes(),
                EMF_BYTES,
            )

    def test_oversized_images_keep_special_placeholders_and_later_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "order.docx"
            build_fixture(docx)

            report, md_path = convert(
                docx,
                tmp,
                config=Config(
                    assets_mode="placeholder",
                    max_upload_bytes=100000,
                    max_image_dimension=1,
                    preview_max_dimension=30,
                ),
            )
            markdown = md_path.read_text(encoding="utf-8")
            manifest = json.loads((tmp / "assets" / "manifest.json").read_text(encoding="utf-8"))

            oversized = [
                image
                for image in manifest["images"]
                if image["compatibility"] == "oversized"
            ]
            self.assertTrue(oversized)
            for image in oversized:
                self.assertTrue(image["placeholder"].startswith("{{SHOWDOC_OVERSIZED_IMAGE_"))
                self.assertTrue(image["upload_file"])
                self.assertTrue(image["upload_sha256"])
                self.assertTrue((tmp / image["upload_file"]).is_file())
                self.assertIn(image["placeholder"], markdown)
                self.assertTrue(image["requires_conversion"])

            # The special images keep their original sequence and the following
            # image is not renumbered.
            tokens = [
                image["placeholder"]
                for image in manifest["images"]
                if image["placeholder"] in markdown
            ]
            positions = [markdown.index(token) for token in tokens]
            self.assertEqual(positions, sorted(positions))
            self.assertEqual(
                [image["sequence"] for image in manifest["images"]],
                list(range(1, 7)),
            )

    def test_oversized_png_generates_preview_upload_copy(self):
        prepared = _prepare_image(
            make_png(80, 60),
            ".png",
            max_upload_bytes=5 * 1024 * 1024,
            max_image_dimension=40,
            preview_max_dimension=30,
            generate_previews=True,
        )
        self.assertEqual(prepared["compatibility"], "oversized")
        self.assertTrue(prepared["requires_conversion"])
        self.assertIsNotNone(prepared["upload_bytes"])
        self.assertEqual(prepared["upload_extension"], ".png")
        self.assertLessEqual(
            max(prepared["upload_width"], prepared["upload_height"]), 30
        )

    def test_unsupported_and_unrenderable_formats_get_special_categories(self):
        svg = _prepare_image(
            b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10'/></svg>",
            ".svg",
            max_upload_bytes=1024 * 1024,
            max_image_dimension=4000,
            preview_max_dimension=2000,
            generate_previews=True,
        )
        self.assertEqual(svg["compatibility"], "unsupported")
        self.assertIsNone(svg["upload_bytes"])

        broken_emf = _prepare_image(
            b"not a real emf",
            ".emf",
            max_upload_bytes=1024 * 1024,
            max_image_dimension=4000,
            preview_max_dimension=2000,
            generate_previews=True,
        )
        self.assertEqual(broken_emf["compatibility"], "conversion_failed")
        self.assertIsNone(broken_emf["upload_bytes"])

    def test_alternate_content_counts_only_preferred_representation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "alternate.docx"
            with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("[Content_Types].xml", CONTENT_TYPES)
                archive.writestr("_rels/.rels", ROOT_RELS)
                archive.writestr("word/document.xml", ALTERNATE_DOCUMENT)
                archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
                archive.writestr("word/media/a.png", make_png(4, 4))

            report, md_path = convert(docx, tmp, config=Config(assets_mode="placeholder"))
            markdown = md_path.read_text(encoding="utf-8")
            manifest = json.loads((tmp / "assets" / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["summary"]["occurrences"], 1)
            self.assertEqual(len(manifest["images"]), 1)
            self.assertEqual(manifest["images"][0]["alt_text"], "首选图")
            self.assertEqual(markdown.count("{{SHOWDOC_IMAGE_000001}}"), 1)
            self.assertNotIn("{{SHOWDOC_IMAGE_000002}}", markdown)

    def test_standalone_module_writes_manifest_without_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "order.docx"
            build_fixture(docx)

            result = extract_docx_images(docx, tmp)

            self.assertTrue(result.manifest_path.is_file())
            self.assertEqual(len(result.occurrences), 6)
            self.assertEqual(result.manifest["images"][0]["placeholder"], "{{SHOWDOC_IMAGE_000001}}")
            for image in result.manifest["images"]:
                self.assertIsNone(image["showdoc_url"])
                self.assertEqual(image["upload_status"], "not_uploaded")
                self.assertEqual(image["replacement_status"], "pending")

    def test_folder_mode_still_extracts_table_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "order.docx"
            media = build_fixture(docx)

            report, md_path = convert(docx, tmp, config=Config(assets_mode="folder"))
            markdown = md_path.read_text(encoding="utf-8")

            self.assertIn("![表格图](order.assets/img-002.png)", markdown)
            self.assertTrue((tmp / "order.assets" / "img-002.png").is_file())
            self.assertEqual((tmp / "order.assets" / "img-002.png").read_bytes(), media["b"])


if __name__ == "__main__":
    unittest.main()
