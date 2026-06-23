import unittest

from bnct_tps_agent.gui import compact_arguments, format_tool_event


class GuiHelperTests(unittest.TestCase):
    def test_compact_arguments_hides_content(self):
        rendered = compact_arguments({"path": "a.py", "content": "secret body"})
        self.assertNotIn("secret body", rendered)
        self.assertIn("11 chars", rendered)

    def test_tool_event_format(self):
        rendered = format_tool_event({"type": "tool_finished", "tool": "read_project_text", "ok": True})
        self.assertIn("read_project_text", rendered)
        self.assertIn("完成", rendered)


if __name__ == "__main__":
    unittest.main()
