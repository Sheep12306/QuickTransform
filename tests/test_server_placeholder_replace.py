"""HTTP endpoint tests for the placeholder replacement tool."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from w2md.server.app import Handler, ThreadingHTTPServer


MARKDOWN = "# 文档\n\n{{SHOWDOC_IMAGE_000001}}\n\n{{SHOWDOC_IMAGE_000002}}\n"
SHOWDOC = (
    "![图1](https://doc.bizgo.com/Public/Uploads/a.png)\n"
    "![图2](http://doc.bizgo.com/Public/Uploads/b.png?sign=abc)\n"
)
MANIFEST = {
    "images": [
        {
            "placeholder": "{{SHOWDOC_IMAGE_000001}}",
            "order": 1,
            "alt_text": "架构图",
            "local_path": "assets/a.png",
        },
        {
            "placeholder": "{{SHOWDOC_IMAGE_000002}}",
            "order": 2,
            "alt_text": "表格图",
            "local_path": "assets/b.png",
        },
    ]
}


class PlaceholderReplaceEndpointTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:{0}".format(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, action, payload):
        request = urllib.request.Request(
            self.base + "/api/placeholder-replace/" + action,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_analyze_and_generate(self):
        payload = {
            "markdown": MARKDOWN,
            "showdoc_markdown": SHOWDOC,
            "manifest": MANIFEST,
        }
        status, analysis = self.post("analyze", payload)
        self.assertEqual(status, 200)
        self.assertTrue(analysis["can_generate"])
        self.assertEqual(analysis["counts"]["matched"], 2)

        status, result = self.post("generate", payload)
        self.assertEqual(status, 200)
        self.assertIn("![架构图](https://doc.bizgo.com/Public/Uploads/a.png)", result["markdown"])
        self.assertIn("![表格图](http://doc.bizgo.com/Public/Uploads/b.png?sign=abc)", result["markdown"])
        self.assertEqual(result["replaced_count"], 2)
        self.assertEqual(
            result["updated_manifest"]["images"][0]["replacement_status"], "replaced"
        )

    def test_mismatch_returns_422(self):
        payload = {
            "markdown": MARKDOWN,
            "showdoc_markdown": "![图1](https://doc.bizgo.com/Public/Uploads/a.png)\n",
            "manifest": MANIFEST,
        }
        status, data = self.post("generate", payload)
        self.assertEqual(status, 422)
        self.assertFalse(data["can_generate"])
        self.assertTrue(any("数量不一致" in item for item in data["errors"]))


if __name__ == "__main__":
    unittest.main()
