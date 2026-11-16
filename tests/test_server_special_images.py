"""HTTP endpoint tests for special image handling."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from w2md.server.app import Handler, ThreadingHTTPServer


MARKDOWN = """# 文档

{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}
"""
MANIFEST = {
    "images": [
        {
            "sequence": 2,
            "occurrence_id": "IMG_OCC_000002",
            "placeholder": "{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}",
            "compatibility": "unsupported",
            "alt_text": "矢量图",
            "source_file": "assets/a.emf",
        }
    ]
}
URL = "https://doc.bizgo.com/Public/Uploads/a.png"


class SpecialImagesEndpointTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:{0}".format(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_analyze_reports_pending_without_url(self):
        status, analysis = self.post(
            "/api/special-images/analyze",
            {"markdown": MARKDOWN, "manifest": MANIFEST},
        )

        self.assertEqual(status, 200)
        self.assertFalse(analysis["can_generate"])
        self.assertEqual(analysis["counts"]["pending"], 1)
        self.assertEqual(analysis["counts"]["special_images"], 1)

    def test_generate_replaces_special_placeholder(self):
        payload = {
            "markdown": MARKDOWN,
            "manifest": MANIFEST,
            "urls": {"{{SHOWDOC_UNSUPPORTED_IMAGE_000002}}": URL},
        }
        status, analysis = self.post("/api/special-images/analyze", payload)
        self.assertEqual(status, 200)
        self.assertTrue(analysis["can_generate"])

        status, result = self.post("/api/special-images/generate", payload)
        self.assertEqual(status, 200)
        self.assertIn("![矢量图](" + URL + ")", result["markdown"])
        self.assertEqual(result["replaced_count"], 1)
        self.assertTrue(result["final_check"]["passed"])
        self.assertEqual(
            result["updated_manifest"]["images"][0]["showdoc_url"], URL
        )

    def test_generate_returns_422_when_pending(self):
        status, data = self.post(
            "/api/special-images/generate",
            {"markdown": MARKDOWN, "manifest": MANIFEST},
        )

        self.assertEqual(status, 422)
        self.assertFalse(data["can_generate"])
        self.assertTrue(any("待处理" in item for item in data["errors"]))

    def test_missing_manifest_is_reported_in_analysis(self):
        status, data = self.post(
            "/api/special-images/analyze",
            {"markdown": MARKDOWN},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["can_generate"])
        self.assertEqual(data["items"], [])
        self.assertTrue(any("manifest" in item for item in data["errors"]))

    def test_legacy_placeholder_route_is_gone(self):
        status, _data = self.post(
            "/api/placeholder-replace/analyze",
            {"markdown": MARKDOWN, "showdoc_markdown": ""},
        )

        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
