import unittest
from pathlib import Path

from bnct_tps_agent.project_tools import read_project_text, resolve_inside, resolve_write_target, write_project_text


class ProjectToolTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_inside(self.root, "../secret.txt")

    def test_write_and_read_text(self):
        result = write_project_text(self.root, "tests/runtime_output/example.py", "print('ok')\n")
        self.assertIn(result["operation"], {"created", "updated"})
        self.assertFalse(result["outsideRoot"])
        read = read_project_text(self.root, "tests/runtime_output/example.py")
        self.assertEqual(read["content"], "print('ok')")

    def test_absolute_write_target_outside_root_is_detected(self):
        target = (self.root.parent / "external-note.md").resolve()
        resolved, outside_root = resolve_write_target(self.root, str(target))
        self.assertEqual(resolved, target)
        self.assertTrue(outside_root)

    def test_disallowed_binary_extension_is_rejected(self):
        with self.assertRaises(ValueError):
            write_project_text(self.root, "tests/runtime_output/payload.exe", "not binary")

    def test_svn_metadata_paths_are_blocked(self):
        # The TPS checkout is SVN-managed: .svn is untouchable, read or write.
        with self.assertRaises(PermissionError):
            resolve_inside(self.root, ".svn/entries")
        with self.assertRaises(PermissionError):
            resolve_inside(self.root, "src/.svn/wc.db")
        with self.assertRaises(PermissionError):
            resolve_write_target(self.root, str(self.root / ".svn" / "tmp.txt"))
        with self.assertRaises(PermissionError):
            write_project_text(self.root, ".svn/hook.md", "x")

    def test_agent_written_scripts_may_not_contain_svn_commands(self):
        with self.assertRaises(PermissionError):
            write_project_text(
                self.root,
                "tests/runtime_output/sync.bat",
                "@echo off\nsvn revert -R .\nsvn update\n",
            )
        with self.assertRaises(PermissionError):
            write_project_text(
                self.root,
                "tests/runtime_output/sync2.sh",
                "#!/bin/sh\n/usr/bin/svn commit -m auto\n",
            )
        # Plain text mentioning svn is fine -- only runnable scripts are guarded.
        result = write_project_text(self.root, "tests/runtime_output/notes-svn.md", "svn 由人工操作")
        self.assertIn(result["operation"], {"created", "updated"})


if __name__ == "__main__":
    unittest.main()
