"""Tests for document-order DOCX image extraction and ShowDoc placeholders."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fixture_builder import make_png
from w2md.config import Config
from w2md.image_extract import extract_docx_images
from w2md.pipeline import convert


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

EMF_BYTES = b"\x01\x00\x00\x00" + b"\x00" * 36 + b" EMF" + b"\x00" * 32

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

            placeholders = ["{{SHOWDOC_IMAGE_%06d}}" % index for index in range(1, 7)]
            positions = [markdown.index(placeholder) for placeholder in placeholders]
            self.assertEqual(positions, sorted(positions))
            self.assertNotIn("data:image", markdown)
            self.assertNotIn("assets/", markdown)
            self.assertIn("| 说明 | {{SHOWDOC_IMAGE_000002}} |", markdown)

            images = manifest["images"]
            self.assertEqual([image["placeholder"] for image in images], placeholders)
            self.assertEqual([image["order"] for image in images], list(range(1, 7)))

            first = images[0]
            self.assertEqual(first["source_part"], "word/media/a.png")
            self.assertEqual(first["relationship_id"], "rIdA")
            self.assertEqual(first["local_path"], "assets/order-image-000001.png")
            self.assertEqual(first["extension"], ".png")
            self.assertEqual(first["mime_type"], "image/png")
            self.assertEqual(first["alt_text"], "架构图")
            self.assertEqual(first["alt_source"], "docPr:descr")
            self.assertTrue(first["sha256_verified"])
            self.assertEqual(first["sha256"], hashlib.sha256(media["a"]).hexdigest())
            self.assertEqual((tmp / "assets" / "order-image-000001.png").read_bytes(), media["a"])
            self.assertIsNone(first["showdoc_url"])
            self.assertEqual(first["upload_status"], "not_uploaded")
            self.assertEqual(first["replacement_status"], "pending")

            self.assertEqual(images[1]["alt_text"], "表格图")
            self.assertEqual(images[1]["source_part"], "word/media/b.png")

            duplicate = images[2]
            self.assertTrue(duplicate["is_duplicate"])
            self.assertEqual(duplicate["duplicate_of"], placeholders[0])
            self.assertEqual(duplicate["local_path"], first["local_path"])

            vml_image = images[3]
            self.assertEqual(vml_image["alt_text"], "VML示意图")
            self.assertEqual(vml_image["alt_source"], "vml:alt")
            self.assertEqual(vml_image["source_part"], "word/media/c.png")

            emf = images[4]
            self.assertTrue(emf["is_compatibility_format"])
            self.assertEqual(emf["status"], "compatibility")
            self.assertEqual(emf["alt_text"], "图 4 兼容格式")
            self.assertEqual(emf["alt_source"], "caption")
            self.assertEqual(emf["extension"], ".emf")
            self.assertEqual((tmp / "assets" / "order-image-000004.emf").read_bytes(), EMF_BYTES)
            self.assertEqual(emf["sha256"], hashlib.sha256(EMF_BYTES).hexdigest())
            self.assertIn(emf["preview_status"], ("unavailable", "failed", "disabled"))

            missing = images[5]
            self.assertEqual(missing["status"], "failed")
            self.assertIn("rIdMissing", missing["error"])

            self.assertEqual(manifest["summary"]["occurrences"], 6)
            self.assertEqual(manifest["summary"]["unique_media"], 4)
            self.assertEqual(manifest["summary"]["duplicates"], 1)
            self.assertEqual(manifest["summary"]["failed"], 1)
            self.assertEqual(manifest["summary"]["compatibility"], 1)
            self.assertEqual(len(manifest["unreferenced_media"]), 1)
            self.assertEqual(manifest["unreferenced_media"][0]["part"], "word/media/unused.png")
            self.assertTrue(any(error["kind"] == "image_failed" for error in manifest["errors"]))

            self.assertEqual(report.stats["image_occurrences"], 6)
            self.assertEqual(report.stats["image_unique_media"], 4)
            self.assertEqual(report.stats["image_duplicates"], 1)
            self.assertEqual(report.stats["image_failed"], 1)
            self.assertEqual(report.stats["image_placeholders"], 6)
            self.assertTrue(any(w.kind == "image_compatibility" for w in report.warnings))
            self.assertTrue(any(w.kind == "image_unreferenced" for w in report.warnings))

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
