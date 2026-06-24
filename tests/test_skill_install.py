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
