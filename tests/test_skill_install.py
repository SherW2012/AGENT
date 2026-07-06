import io
import shutil
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from bnct_tps_agent.audit import AuditLogger
from bnct_tps_agent.safety import SafetyPolicy
from bnct_tps_agent.skill_installer import parse_github_skill_url
from bnct_tps_agent.skills import SkillRegistry
from bnct_tps_agent.tool_registry import ToolRegistry


class FakeBinaryResponse:
    def __init__(self, data: bytes):
        self.data = data
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1):
        return self.data


def github_skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "demo-skill-main/SKILL.md",
            "---\n"
            "name: github-demo\n"
            "description: Demo GitHub skill.\n"
            "display_name: GitHub Demo\n"
            "---\n\n"
            "# GitHub Demo\n\nUse this skill for tests.\n",
        )
        archive.writestr("demo-skill-main/examples/example.txt", "hello")
    return buffer.getvalue()


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / "tests" / "runtime_output" / f"skill-install-{uuid.uuid4().hex}"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_github_url_parser_accepts_tree_and_blob_links(self):
        tree = parse_github_skill_url("https://github.com/acme/repo/tree/dev/skills/demo")
        self.assertEqual(tree.owner, "acme")
        self.assertEqual(tree.repo, "repo")
        self.assertEqual(tree.ref, "dev")
        self.assertEqual(tree.subpath, "skills/demo")

        blob = parse_github_skill_url("https://github.com/acme/repo/blob/main/skills/demo/SKILL.md")
        self.assertEqual(blob.ref, "main")
        self.assertEqual(blob.subpath, "skills/demo")

    def test_agent_tool_installs_skill_from_github_url_after_approval(self):
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(lambda *_args: True),
            AuditLogger(self.root / "audit"),
        )
        with patch("bnct_tps_agent.skill_installer._open_url", return_value=FakeBinaryResponse(github_skill_zip())):
            result = registry.execute(
                "install_agent_skill",
                {"url": "https://github.com/acme/demo-skill/tree/main", "ref": ""},
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["name"], "github-demo")
        self.assertTrue((self.root / ".agent" / "skills" / "github-demo" / "SKILL.md").is_file())
        catalog = registry.execute("list_agent_skills", {})
        self.assertIn("github-demo", {item["name"] for item in catalog["result"]["skills"]})

    def test_agent_can_author_its_own_skill(self):
        data_dir = self.root / "userdata"
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(lambda *_args: True),
            AuditLogger(self.root / "audit"),
            skill_registry=SkillRegistry(self.root, data_dir),
            data_dir=data_dir,
        )
        skill_md = (
            "---\n"
            "name: tps-launch\n"
            "description: Launch the TPS application via a registered script.\n"
            "display_name: TPS 启动\n"
            "short_description: 一键启动 TPS。\n"
            'icon: "🚀"\n'
            "interaction: direct\n"
            "---\n\n# TPS Launch\n\nUse run_build with the launch profile.\n"
        )
        result = registry.execute("create_agent_skill", {"skill_md": skill_md})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["name"], "tps-launch")
        # Stored in the user-level dir and immediately discoverable, no restart.
        self.assertTrue((data_dir / "skills" / "tps-launch" / "SKILL.md").is_file())
        catalog = registry.execute("list_agent_skills", {})
        self.assertIn("tps-launch", {item["name"] for item in catalog["result"]["skills"]})

    def test_instant_skill_declares_auto_approve_tools_in_catalog(self):
        data_dir = self.root / "userdata"
        skills_dir = data_dir / "skills" / "one-click"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\n"
            "name: one-click\n"
            "description: One-click build.\n"
            "interaction: instant\n"
            "auto_approve_tools:\n"
            "  - run_build\n"
            "---\n\n# One click\n",
            encoding="utf-8",
        )
        registry = SkillRegistry(self.root, data_dir)
        item = next(entry for entry in registry.public_catalog() if entry["name"] == "one-click")
        self.assertEqual(item["interaction"], "instant")
        self.assertEqual(item["autoApproveTools"], ["run_build"])

    def test_auto_approve_tools_ignored_unless_interaction_is_instant(self):
        # A skill must not get pre-approval without also being an explicit
        # one-click action the human launches by name.
        data_dir = self.root / "userdata"
        skills_dir = data_dir / "skills" / "sneaky"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\n"
            "name: sneaky\n"
            "description: Declares approvals without instant interaction.\n"
            "auto_approve_tools:\n"
            "  - write_project_text\n"
            "---\n\n# Sneaky\n",
            encoding="utf-8",
        )
        registry = SkillRegistry(self.root, data_dir)
        item = next(entry for entry in registry.public_catalog() if entry["name"] == "sneaky")
        self.assertEqual(item["interaction"], "guided")
        self.assertEqual(item["autoApproveTools"], [])

    def test_create_agent_skill_rejects_content_without_frontmatter(self):
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(lambda *_args: True),
            AuditLogger(self.root / "audit"),
            skill_registry=SkillRegistry(self.root, self.root / "userdata"),
            data_dir=self.root / "userdata",
        )
        result = registry.execute("create_agent_skill", {"skill_md": "# 只有正文没有 frontmatter"})
        self.assertFalse(result["ok"])

    def test_script_writes_escalate_to_execute_approval(self):
        recorded: list[tuple[str, str]] = []

        def approver(tool, risk, _arguments):
            recorded.append((tool, risk.value))
            return True

        registry = ToolRegistry(
            self.root,
            SafetyPolicy(approver),
            AuditLogger(self.root / "audit"),
            data_dir=self.root / "userdata",
        )
        result = registry.execute(
            "write_project_text",
            {"path": "launch_tps.bat", "content": "@echo off\nstart \"\" app.exe\n"},
        )
        self.assertTrue(result["ok"], result)
        self.assertIn(("write_project_text", "execute"), recorded)
        plain = registry.execute("write_project_text", {"path": "notes.md", "content": "hi"})
        self.assertTrue(plain["ok"], plain)
        self.assertIn(("write_project_text", "write"), recorded)

    def test_agent_tool_requires_approval_before_network_download(self):
        registry = ToolRegistry(
            self.root,
            SafetyPolicy(),
            AuditLogger(self.root / "audit"),
        )
        with patch("bnct_tps_agent.skill_installer._open_url") as open_url:
            result = registry.execute(
                "install_agent_skill",
                {"url": "https://github.com/acme/demo-skill/tree/main", "ref": ""},
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "PolicyDenied")
        open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
