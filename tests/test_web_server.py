import json
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bnct_tps_agent.web_server import (
    AgentHTTPServer,
    ApplicationState,
    acquire_instance_lock,
    approval_arguments,
    existing_server_is_healthy,
    load_or_create_web_token,
)


class WebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.old_api_keys = {
            name: os.environ.pop(name, None)
            for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY")
        }
        cls.state = ApplicationState(cls.root, "unit-test-token")
        cls.server = AgentHTTPServer(("127.0.0.1", 0), cls.state)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        for name, value in cls.old_api_keys.items():
            if value is not None:
                os.environ[name] = value

    def _json(self, path):
        request = Request(self.base + path, headers={"X-BNCT-Token": "unit-test-token"})
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path, payload):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BNCT-Token": "unit-test-token"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_static_page_loads(self):
        with urlopen(self.base + "/", timeout=5) as response:
            body = response.read().decode("utf-8")
        self.assertIn("BNCT TPS Agent", body)
        self.assertIn("今天想处理什么", body)
        self.assertIn('<div class="file-preview" id="preview-content">', body)
        self.assertIn('id="browse-folder-button"', body)

    def test_frontend_includes_safe_markdown_and_light_theme(self):
        with urlopen(self.base + "/app.js", timeout=5) as response:
            script = response.read().decode("utf-8")
        with urlopen(self.base + "/styles.css", timeout=5) as response:
            styles = response.read().decode("utf-8")
        self.assertIn("function renderMarkdown", script)
        self.assertIn('document.createElement("strong")', script)
        self.assertNotIn("container.innerHTML", script)
        self.assertIn("color-scheme: light", styles)
        self.assertIn(".markdown-body strong", styles)
        self.assertIn("font-size: 15px", styles)

    def test_api_requires_random_token(self):
        with self.assertRaises(HTTPError) as context:
            urlopen(self.base + "/api/config", timeout=5)
        self.assertEqual(context.exception.code, 401)

    def test_config_and_files_endpoints(self):
        config = self._json("/api/config")
        files = self._json("/api/files?limit=20")
        self.assertEqual(config["root"], str(self.root))
        self.assertEqual({item["id"] for item in config["providers"]}, {"openai", "deepseek", "kimi"})
        self.assertFalse(config["apiKeyConfigured"])
        self.assertIn("README.md", files["files"])

    def test_running_server_is_detected_for_single_instance_launch(self):
        self.assertTrue(existing_server_is_healthy("127.0.0.1", self.server.server_address[1]))

    def test_project_instance_lock_rejects_second_server(self):
        root = self.root / "tests" / "runtime_output" / "instance-lock"
        first = acquire_instance_lock(root)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(acquire_instance_lock(root))
        finally:
            first.close()
        third = acquire_instance_lock(root)
        self.assertIsNotNone(third)
        third.close()

    def test_provider_can_be_switched_without_an_openai_key(self):
        config = self._post_json("/api/config", {"provider": "deepseek", "root": str(self.root)})
        self.assertEqual(config["provider"], "deepseek")
        self.assertEqual(config["model"], "deepseek-v4-pro")
        self.assertEqual(config["baseUrl"], "https://api.deepseek.com")
        self.assertFalse(config["apiKeyConfigured"])

    def test_native_folder_picker_result_is_returned(self):
        with patch("bnct_tps_agent.web_server.choose_project_folder", return_value=str(self.root)):
            result = self._post_json("/api/pick-folder", {"initial": str(self.root)})
        self.assertEqual(result["path"], str(self.root))

    def test_offline_snapshot_demo(self):
        request = Request(
            self.base + "/api/offline-demo",
            data=b"{}",
            headers={"Content-Type": "application/json", "X-BNCT-Token": "unit-test-token"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["validation"]["result"]["valid"])

    def test_approval_preview_is_bounded(self):
        result = approval_arguments({"content": "x" * 5000})
        self.assertLess(len(result["content"]), 4100)
        self.assertIn("more chars", result["content"])

    def test_web_token_survives_service_restart(self):
        root = self.root / "tests" / "runtime_output" / "web-token-restart"
        token_path = root / ".bnct_agent" / "web-token"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("replace-this-invalid-token", encoding="utf-8")
        first = load_or_create_web_token(root)
        second = load_or_create_web_token(root)
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(first, second)
        self.assertEqual(token_path.read_text(encoding="utf-8"), first)


if __name__ == "__main__":
    unittest.main()
