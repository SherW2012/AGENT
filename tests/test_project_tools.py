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


if __name__ == "__main__":
    unittest.main()
