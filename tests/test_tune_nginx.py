"""Tests for the server-side nginx tuning helper."""

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "tune_nginx.py"
SPEC = importlib.util.spec_from_file_location("tune_nginx", SCRIPT)
tune_nginx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tune_nginx)


class TuneNginxTest(unittest.TestCase):
    def test_adds_upload_limit_and_timeouts(self):
        text = (
            "server {\n"
            "    location / {\n"
            "        proxy_pass http://127.0.0.1:8080;\n"
            "    }\n"
            "}\n"
        )

        updated, changed = tune_nginx.tune_text(text)

        self.assertTrue(changed)
        self.assertIn("client_max_body_size 200m;", updated)
        self.assertIn("proxy_read_timeout 300s;", updated)
        self.assertIn("proxy_send_timeout 300s;", updated)
        self.assertIn("proxy_connect_timeout 60s;", updated)

    def test_replaces_existing_smaller_limits(self):
        text = (
            "server {\n"
            "    client_max_body_size 50m;\n"
            "    proxy_read_timeout 60s;\n"
            "    location / { proxy_pass http://127.0.0.1:8080; }\n"
            "}\n"
        )

        updated, changed = tune_nginx.tune_text(text)

        self.assertTrue(changed)
        self.assertIn("client_max_body_size 200m;", updated)
        self.assertNotIn("client_max_body_size 50m;", updated)
        self.assertIn("proxy_read_timeout 300s;", updated)
        self.assertNotIn("proxy_read_timeout 60s;", updated)

    def test_is_idempotent(self):
        text = (
            "server {\n"
            "    client_max_body_size 200m;\n"
            "    proxy_read_timeout 300s;\n"
            "    proxy_send_timeout 300s;\n"
            "    proxy_connect_timeout 60s;\n"
            "    location / { proxy_pass http://127.0.0.1:8080; }\n"
            "}\n"
        )

        updated, changed = tune_nginx.tune_text(text)

        self.assertFalse(changed)
        self.assertEqual(updated, text)

    def test_requires_server_block(self):
        with self.assertRaises(RuntimeError):
            tune_nginx.tune_text("client_max_body_size 50m;\n")


if __name__ == "__main__":
    unittest.main()
