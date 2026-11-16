"""Embedded Word documents / videos / HTML are manual placeholders."""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fixture_builder import make_png
from w2md.config import Config
from w2md.pipeline import convert
from w2md.upload_result import analyze_upload_result


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="mp4" ContentType="video/mp4"/>
  <Default Extension="htm" ContentType="text/html"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/photo.png"/>
  <Relationship Id="rIdIcon" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/icon.png"/>
  <Relationship Id="rIdOle" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="embeddings/Microsoft_Word_Document1.docx"/>
  <Relationship Id="rIdVideo" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/video" Target="media/clip.mp4"/>
  <Relationship Id="rIdPoster" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/poster.png"/>
  <Relationship Id="rIdHtml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk" Target="afchunk1.htm"/>
</Relationships>"""

DRAWING = (
    "<w:drawing><wp:inline><wp:extent cx=\"100\" cy=\"100\"/>"
    "<wp:docPr id=\"1\" name=\"图片 1\"/>"
    "<a:graphic><a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
    "<pic:pic><pic:nvPicPr><pic:cNvPr id=\"1\" name=\"图片 1\"/><pic:cNvPicPr/></pic:nvPicPr>"
    "<pic:blipFill><a:blip r:embed=\"rIdImage\"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
    "<pic:spPr/></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>"
)

VIDEO_DRAWING = (
    "<w:drawing><wp:inline><wp:extent cx=\"100\" cy=\"100\"/>"
    "<wp:docPr id=\"2\" name=\"视频\"/>"
    "<a:graphic><a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
    "<pic:pic><pic:nvPicPr><pic:cNvPr id=\"2\" name=\"视频\"/>"
    "<pic:nvPr><a:videoFile r:link=\"rIdVideo\"/></pic:nvPr></pic:nvPicPr>"
    "<pic:blipFill><a:blip r:embed=\"rIdPoster\"/></pic:blipFill>"
    "<pic:spPr/></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>"
)

OLE_OBJECT = """<w:object w:dxaOrig="100" w:dyaOrig="100">
  <v:shape id="_x0000_i1025" type="#_x0000_t75" style="width:100pt;height:100pt">
    <v:imagedata r:id="rIdIcon" o:title="嵌入文档"/>
    <o:OLEObject Type="Embed" ProgID="Word.Document.12" ShapeID="_x0000_i1025"
      DrawAspect="Content" ObjectID="_1" r:id="rIdOle"/>
  </v:shape>
</w:object>"""

DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
    xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
    xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
    xmlns:v="urn:schemas-microsoft-com:vml"
    xmlns:o="urn:schemas-microsoft-com:office:office">
  <w:body>
    <w:p><w:r><w:t>普通图片</w:t></w:r><w:r>{drawing}</w:r></w:p>
    <w:p><w:r>{ole}</w:r></w:p>
    <w:p><w:r>{video}</w:r></w:p>
    <w:p><w:r><w:t>正文结束</w:t></w:r></w:p>
    <w:altChunk r:id="rIdHtml"/>
    <w:sectPr/>
  </w:body>
</w:document>""".format(drawing=DRAWING, ole=OLE_OBJECT, video=VIDEO_DRAWING)


def build_fixture(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("word/document.xml", DOCUMENT_XML)
        archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        archive.writestr("word/media/photo.png", make_png(8, 6))
        archive.writestr("word/media/icon.png", make_png(6, 4))
        archive.writestr("word/media/poster.png", make_png(7, 5))
        archive.writestr("word/embeddings/Microsoft_Word_Document1.docx", b"embedded-docx")
        archive.writestr("word/media/clip.mp4", b"fake-mp4-bytes")
        archive.writestr("word/afchunk1.htm", b"<html><body>chunk</body></html>")


class EmbeddedObjectTest(unittest.TestCase):
    def test_embedded_objects_use_manual_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docx = tmp / "embedded.docx"
            build_fixture(docx)

            report, md_path = convert(
                docx, tmp, config=Config(assets_mode="placeholder")
            )
            markdown = md_path.read_text(encoding="utf-8")
            manifest = json.loads(
                (tmp / "assets" / "manifest.json").read_text(encoding="utf-8")
            )
            images = manifest["images"]

            self.assertEqual(
                [image["placeholder"] for image in images],
                [
                    "{{SHOWDOC_IMAGE_000001}}",
                    "{{SHOWDOC_EMBEDDED_000002}}",
                    "{{SHOWDOC_EMBEDDED_000003}}",
                    "{{SHOWDOC_EMBEDDED_000004}}",
                ],
            )
            self.assertEqual(manifest["summary"]["occurrences"], 4)
            self.assertEqual(manifest["summary"]["embedded"], 3)
            self.assertEqual(manifest["summary"]["supported"], 1)
            self.assertEqual(manifest["summary"]["unreferenced_media"], 0)
            self.assertEqual(manifest["errors"], [])

            placed = [image["placeholder"] for image in images]
            positions = [markdown.index(token) for token in placed]
            self.assertEqual(positions, sorted(positions))
            self.assertNotIn("UNMATCHED", markdown)
            self.assertIn("{{SHOWDOC_EMBEDDED_000002}}", markdown)
            self.assertIn("{{SHOWDOC_EMBEDDED_000003}}", markdown)
            self.assertIn("{{SHOWDOC_EMBEDDED_000004}}", markdown)

            ole = images[1]
            self.assertEqual(ole["compatibility"], "embedded")
            self.assertTrue(ole["manual_upload"])
            self.assertEqual(ole["embedded_label"], "DOCX")
            self.assertEqual(ole["prog_id"], "Word.Document.12")
            self.assertEqual(
                ole["embedded_part"], "word/embeddings/Microsoft_Word_Document1.docx"
            )
            self.assertIsNone(ole["source_file"])
            self.assertIsNone(ole["upload_file"])
            self.assertEqual(ole["source_size"], len(b"embedded-docx"))
            self.assertEqual(ole["status"], "manual_upload")

            video = images[2]
            self.assertEqual(video["embedded_label"], "视频")
            self.assertEqual(video["embedded_part"], "word/media/clip.mp4")

            html = images[3]
            self.assertEqual(html["embedded_label"], "HTML")
            self.assertEqual(html["embedded_part"], "word/afchunk1.htm")

            self.assertTrue(
                any(w.kind == "embedded_object" for w in report.warnings)
            )

            analysis = analyze_upload_result(
                markdown,
                {
                    "schema_version": 1,
                    "manifest_document_id": manifest["document_id"],
                    "uploads": [],
                    "expected_count": 1,
                },
                manifest,
            )
            self.assertEqual(analysis.counts["embedded"], 3)
            self.assertEqual(analysis.counts["special_images"], 3)
            self.assertEqual(analysis.counts["normal_images"], 1)
            self.assertEqual(len(analysis.targets), 1)
            self.assertEqual(
                analysis.targets[0].placeholder, "{{SHOWDOC_IMAGE_000001}}"
            )
            self.assertTrue(
                any(
                    "嵌入对象" in warning and "手动上传" in warning
                    for warning in analysis.warnings
                )
            )


if __name__ == "__main__":
    unittest.main()
