"""HTTP endpoint test for the standalone Word image extraction tool."""

import io
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
import uuid
import zipfile
from pathlib import Path

from test_image_extract import build_fixture
from w2md.server.app import Handler, ThreadingHTTPServer


class WordImageEndpointTest(unittest.TestCase):
    def test_asset_job_can_be_recovered_after_restart(self):
        token = uuid.uuid4().hex
        assets = Path(tempfile.gettempdir()) / "quicktranser_word_images" / token / "assets"
        assets.mkdir(parents=True)
        (assets / "sample.png").write_bytes(b"png")
        try:
            handler = object.__new__(Handler)
            job = Handler._recover_asset_job(handler, token)
            self.assertIsNotNone(job)
            self.assertEqual(Path(job["assets_dir"]), assets)
            self.assertIsNone(Handler._recover_asset_job(handler, "not-a-token"))
        finally:
            shutil.rmtree(assets.parent, ignore_errors=True)

    def test_endpoint_returns_ordered_original_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "order.docx"
            build_fixture(docx)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = "http://127.0.0.1:{0}".format(server.server_address[1])
                request = urllib.request.Request(
                    base + "/api/word2image/extract?filename=order.docx",
                    data=docx.read_bytes(),
                    method="POST",
                )
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 200)
                    body = json.loads(response.read().decode("utf-8"))

                self.assertEqual(body["summary"]["occurrences"], 6)
                self.assertEqual(body["summary"]["failed"], 1)
                self.assertEqual(len(body["images"]), 6)
                first = body["images"][0]
                self.assertEqual(first["placeholder"], "{{SHOWDOC_IMAGE_000001}}")
                self.assertEqual(first["order"], 1)
                self.assertTrue(first["sha256_verified"])
                self.assertEqual(first["status"], "extracted")

                with urllib.request.urlopen(base + first["url"]) as response:
                    raw = response.read()
                self.assertEqual(len(raw), first["size"])

                failed = [image for image in body["images"] if image["status"] == "failed"]
                self.assertEqual(len(failed), 1)
                self.assertIn("rIdMissing", failed[0]["error"])

                with urllib.request.urlopen(base + body["manifest_url"]) as response:
                    manifest = json.loads(response.read().decode("utf-8"))
                self.assertEqual(manifest["summary"]["occurrences"], 6)

                names = [image["filename"] for image in body["images"] if image["url"]][:3]
                zip_request = urllib.request.Request(
                    base + "/api/word2image/zip",
                    data=json.dumps(
                        {"token": body["token"], "files": names, "zip_name": "order-images.zip"}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(zip_request) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get("Content-Type"), "application/zip")
                    archive = zipfile.ZipFile(io.BytesIO(response.read()))
                self.assertEqual(sorted(archive.namelist()), sorted(set(names)))
                for name in sorted(set(names)):
                    with archive.open(name) as member:
                        self.assertTrue(member.read())
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
