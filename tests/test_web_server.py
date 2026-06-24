import json
import os
import shutil
import threading
import unittest
import base64
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bnct_tps_agent.skills import SkillRegistry
from bnct_tps_agent.web_server import (
    AgentHTTPServer,
    ApplicationState,
    acquire_instance_lock,
    approval_arguments,
    build_task_prompt,
    existing_server_is_healthy,
    load_or_create_web_token,
    normalize_attachments,
)


def explicit_element(group, element, vr, value):
    if isinstance(value, str):
        raw = value.encode("ascii")
    else:
        raw = value
    if len(raw) % 2:
        raw += b"\x00" if vr == "UI" else b" "
    tag = group.to_bytes(2, "little") + element.to_bytes(2, "little")
    if vr in {"OB", "OD", "OF", "OL", "OW", "SQ", "UC", "UR", "UT", "UN"}:
        return tag + vr.encode("ascii") + b"\x00\x00" + len(raw).to_bytes(4, "little") + raw
    return tag + vr.encode("ascii") + len(raw).to_bytes(2, "little") + raw


def minimal_ct_dicom():
    preamble = b"\x00" * 128 + b"DICM"
    meta = b"".join(
        [
            explicit_element(0x0002, 0x0010, "UI", "1.2.840.10008.1.2.1"),
            explicit_element(0x0002, 0x0002, "UI", "1.2.840.10008.5.1.4.1.1.2"),
        ]
    )
    dataset = b"".join(
        [
            explicit_element(0x0008, 0x0060, "CS", "CT"),
            explicit_element(0x0010, 0x0010, "PN", "Wang^Test"),
            explicit_element(0x0010, 0x0020, "LO", "PID123"),
            explicit_element(0x0028, 0x0010, "US", (512).to_bytes(2, "little")),
            explicit_element(0x0028, 0x0011, "US", (256).to_bytes(2, "little")),
            explicit_element(0x7FE0, 0x0010, "OW", b"\x00\x01\x02\x03"),
        ]
    )
    return preamble + meta + dataset


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
        self.assertIn('id="workspace-switch-button"', body)
        self.assertIn('id="import-skill-button"', body)
        self.assertIn('id="session-list"', body)
        self.assertIn('id="attachment-input"', body)
        self.assertIn('id="settings-button"', body)
        self.assertIn('name="web-search-mode"', body)
        self.assertIn('name="web-search-network"', body)
        self.assertIn('data-settings-section="connection"', body)
        self.assertIn('data-settings-section="web-search"', body)
        self.assertNotIn('id="memory-pill"', body)
        self.assertIn("SKILLS", body)
        self.assertIn("了解边界", body)
        self.assertNotIn("记住偏好", body)
        self.assertNotIn("界面优先保持亮色", body)
        self.assertNotIn("QUICK TASKS", body)
        self.assertNotIn("Safety boundary", body)
        self.assertNotIn("LIVE TRACE", body)

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
        self.assertIn(".session-item", styles)
        self.assertIn(".attachment-chip", styles)
        self.assertIn("function renderSkills", script)
        self.assertIn("function streamApi", script)
        self.assertIn("function appendAssistantDraft", script)
        self.assertIn("/api/chat-stream", script)
        self.assertIn("webSearchMode", script)
        self.assertIn("webSearchNetwork", script)
        self.assertIn("LONG_PASTE_CHAR_THRESHOLD", script)
        self.assertIn("function handlePromptPaste", script)
        self.assertIn('kind: "pasted"', script)
        self.assertIn(".skill-import-card", styles)
        self.assertIn(".activity-panel", styles)
        self.assertIn(".sidebar-settings-button", styles)
        self.assertIn(".settings-tab", styles)
        self.assertIn(".web-search-picker", styles)
        self.assertNotIn(".memory-pill", styles)

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
        self.assertIn("memory", config)
        self.assertEqual(config["webSearchMode"], "auto")
        self.assertEqual(config["webSearchNetwork"], "auto")
        self.assertEqual(config["memory"]["projectFile"], "CLAUDE.md")
        self.assertIn("skills", config)
        skill_names = {item["name"] for item in config["skills"]}
        self.assertTrue({"code-review", "debug", "dicom-tags", "run", "verify"}.issubset(skill_names))
        self.assertNotIn("web-search", skill_names)
        self.assertIn("README.md", files["files"])

    def test_session_endpoints_create_favorite_search_and_delete(self):
        created = self._post_json("/api/sessions", {})
        session_id = created["session"]["id"]
        self.assertEqual(created["config"]["currentSessionId"], session_id)

        favored = self._post_json("/api/session/favorite", {"id": session_id, "favorite": True})
        self.assertIn(session_id, {item["id"] for item in favored["sessions"]})
        self.assertTrue(next(item for item in favored["sessions"] if item["id"] == session_id)["favorite"])

        listed = self._json("/api/sessions?query=%E6%96%B0%E4%BC%9A%E8%AF%9D")
        self.assertIn(session_id, {item["id"] for item in listed["sessions"]})

        deleted = self._post_json("/api/session/delete", {"id": session_id})
        self.assertNotEqual(deleted["config"]["currentSessionId"], session_id)

    def test_attachment_prompt_builder_is_bounded_and_labeled(self):
        prompt_attachments, stored = normalize_attachments(
            [{"name": "notes.md", "type": "text/markdown", "size": 12, "content": "**hello**"}]
        )
        self.assertEqual(stored[0]["name"], "notes.md")
        prompt = build_task_prompt("总结附件", "用户: 上一轮", prompt_attachments)
        self.assertIn("当前会话最近上下文", prompt)
        self.assertIn("附件 1: notes.md", prompt)
        self.assertIn("用户当前任务", prompt)

    def test_dicom_attachment_is_parsed_and_deidentified(self):
        content = base64.b64encode(minimal_ct_dicom()).decode("ascii")
        prompt_attachments, stored = normalize_attachments(
            [
                {
                    "name": "ct.dcm",
                    "type": "application/dicom",
                    "size": len(content),
                    "originalSize": 514000,
                    "encoding": "base64",
                    "content": content,
                }
            ],
            SkillRegistry(self.root),
        )
        self.assertEqual(stored[0]["kind"], "dicom")
        self.assertEqual(stored[0]["skill"], "dicom-tags")
        self.assertGreater(stored[0]["tags"], 3)
        summary = prompt_attachments[0]["content"]
        self.assertIn("DICOM 附件已由 `dicom-tags` skill 解析", summary)
        self.assertIn("| (0008,0060) | Modality | CS | CT |", summary)
        self.assertIn("| (0010,0010) | PatientName | PN | [已脱敏] |", summary)
        self.assertNotIn("Wang^Test", summary)
        self.assertNotIn("PID123", summary)

    def test_skill_registry_loads_and_reads_dicom_skill(self):
        registry = SkillRegistry(self.root)
        catalog = registry.public_catalog()
        self.assertTrue({"code-review", "debug", "dicom-tags", "run", "verify"}.issubset({item["name"] for item in catalog}))
        self.assertNotIn("web-search", {item["name"] for item in catalog})
        self.assertIn("web-search", {item["name"] for item in registry.public_catalog(include_background=True)})
        self.assertIn("web-search", registry.catalog_context())
        skill = registry.read_skill("dicom-tags")
        self.assertIn("SKILL.md", skill["files"])
        self.assertIn("scripts/parse_dicom.py", skill["files"])
        self.assertIn("DICOM Tags", skill["content"])

    def test_import_skill_endpoint_copies_local_skill(self):
        skill_name = f"unit-import-{uuid.uuid4().hex[:10]}"
        target = self.root / ".agent" / "skills" / skill_name
        shutil.rmtree(target, ignore_errors=True)
        source = self.root / "tests" / "runtime_output" / f"{skill_name}-source"
        shutil.rmtree(source, ignore_errors=True)
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\n"
            f"name: {skill_name}\n"
            "description: Imported test skill.\n"
            "display_name: Unit Import\n"
            "short_description: Test import path.\n"
            "---\n\n"
            "# Unit Import\n",
            encoding="utf-8",
        )
        result = self._post_json("/api/import-skill", {"source": str(source)})
        self.assertEqual(result["skill"]["name"], skill_name)
        self.assertIn(skill_name, {item["name"] for item in result["config"]["skills"]})

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
