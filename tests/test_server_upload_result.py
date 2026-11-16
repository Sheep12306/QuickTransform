"""HTTP endpoint tests for the upload_result importer."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from w2md.server.app import Handler, ThreadingHTTPServer


DOC_ID = "doc-0123456789abcdef0123456789abcdef"
MARKDOWN = "第一段 {{SHOWDOC_IMAGE_000001}}\n\n第二段 {{SHOWDOC_IMAGE_000002}}\n"
MANIFEST = {
    "schema_version": 1,
    "document_id": DOC_ID,
    "images": [
        {
            "sequence": 1,
            "occurrence_id": "IMG_OCC_000001",
            "placeholder": "{{SHOWDOC_IMAGE_000001}}",
            "file_name": "image001.png",
            "local_file": "assets/image001.png",
            "sha256": "1" * 64,
            "alt_text": "图1",
        },
        {
            "sequence": 2,
            "occurrence_id": "IMG_OCC_000002",
            "placeholder": "{{SHOWDOC_IMAGE_000002}}",
            "file_name": "image002.png",
            "local_file": "assets/image002.png",
            "sha256": "2" * 64,
            "alt_text": "图2",
        },
    ],
}
UPLOAD_RESULT = {
    "schema_version": 1,
    "manifest_document_id": DOC_ID,
    "expected_count": 2,
    "detected_request_count": 2,
    "success_unique_count": 1,
    "failed_count": 1,
    "not_uploaded_count": 0,
    "unmatched_count": 0,
    "uploads": [
        {
            "upload_id": "UPLOAD_001",
            "sequence": 1,
            "occurrence_id": "IMG_OCC_000001",
            "placeholder": "{{SHOWDOC_IMAGE_000001}}",
            "file_name": "image001.png",
            "sha256": "1" * 64,
            "status": "success",
            "http_status": 200,
            "response_success": 1,
            "url": "http://doc.bizgo.com/Public/Uploads/a.png",
            "error": "",
        },
        {
            "upload_id": "UPLOAD_002",
            "sequence": 2,
            "occurrence_id": "IMG_OCC_000002",
            "placeholder": "{{SHOWDOC_IMAGE_000002}}",
            "file_name": "image002.png",
            "sha256": "2" * 64,
            "status": "failed",
            "http_status": 200,
            "response_success": 0,
            "url": "",
            "error": "ShowDoc 返回 success=0",
        },
    ],
    "missing": [
        {
            "sequence": 2,
            "occurrence_id": "IMG_OCC_000002",
            "placeholder": "{{SHOWDOC_IMAGE_000002}}",
            "file_name": "image002.png",
            "sha256": "2" * 64,
            "status": "failed",
            "reason": "ShowDoc 返回 success=0",
        }
    ],
}


class UploadResultEndpointTest(unittest.TestCase):
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
            self.base + "/api/upload-result/" + action,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def payload(self, **extra):
        data = {
            "markdown": MARKDOWN,
            "manifest": MANIFEST,
            "upload_result": UPLOAD_RESULT,
            "mode": "partial",
        }
        data.update(extra)
        return data

    def test_analyze_reports_partial_success(self):
        status, analysis = self.post("analyze", self.payload())
        self.assertEqual(status, 200)
        self.assertTrue(analysis["can_generate"])
        self.assertTrue(analysis["requires_confirmation"])
        self.assertEqual(analysis["counts"]["success"], 1)
        self.assertEqual(analysis["counts"]["failed"], 1)
        self.assertEqual(analysis["document_id_match"], True)

    def test_generate_requires_confirmation_then_succeeds(self):
        status, data = self.post("generate", self.payload())
        self.assertEqual(status, 409)
        self.assertTrue(data["requires_confirmation"])
        self.assertIn("失败 1", data["error"])

        status, data = self.post("generate", self.payload(confirmed=True))
        self.assertEqual(status, 200, data.get("error"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["replaced_count"], 1)
        self.assertIn("![图1](http://doc.bizgo.com/Public/Uploads/a.png)", data["markdown"])
        self.assertIn("{{SHOWDOC_IMAGE_000002}}", data["markdown"])
        self.assertNotIn("Public/Uploads/b.png", data["markdown"])

        artifacts = data["artifacts"]
        self.assertIn("序号,occurrence_id,占位符", artifacts["csv"]["content"])
        self.assertIn("failed", artifacts["csv"]["content"])
        report = json.loads(artifacts["report"]["content"])
        self.assertEqual(report["replacement"]["replaced_count"], 1)
        self.assertIn("<!doctype html>", artifacts["html"]["content"])
        self.assertTrue(data["remaining_placeholders"])

    def test_missing_upload_result_is_rejected_clearly(self):
        payload = self.payload()
        payload.pop("upload_result")
        status, data = self.post("analyze", payload)
        self.assertEqual(status, 400)
        self.assertIn("upload_result.json", data["error"])

    def test_document_id_mismatch_blocks_generate(self):
        result = json.loads(json.dumps(UPLOAD_RESULT))
        result["manifest_document_id"] = "doc-ffffffffffffffffffffffffffffffff"
        status, data = self.post("generate", self.payload(upload_result=result, confirmed=True))
        self.assertEqual(status, 422)
        self.assertFalse(data["can_generate"])
        self.assertTrue(any("document_id 不一致" in error for error in data["errors"]))


if __name__ == "__main__":
    unittest.main()
