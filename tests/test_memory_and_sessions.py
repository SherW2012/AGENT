import shutil
import unittest
import uuid
from pathlib import Path

from bnct_tps_agent.memory import append_agent_memory, forget_agent_memory, merge_auto_memory, read_auto_memory, sanitize_auto_memory_lines
from bnct_tps_agent.personal import (
    add_calendar_entry,
    add_quick_link,
    delete_calendar_entry,
    delete_quick_link,
    list_calendar_entries,
    list_quick_links,
    resolve_quick_link,
)
from bnct_tps_agent.sessions import SessionStore


class MemoryAndSessionTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / "tests" / "runtime_output"
        self.data_dir = base / f"mem-{uuid.uuid4().hex}"
        self.data_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_session_create_without_switching_current(self):
        store = SessionStore(self.data_dir)
        current = store.create("用户会话")["id"]
        background = store.create("后台会话", make_current=False)["id"]
        self.assertEqual(store.current_id(), current)
        self.assertNotEqual(background, current)

    def test_auto_memory_sanitizer_blocks_sensitive_lines(self):
        lines = [
            "- 用户偏好中文回答，术语保留英文",
            "- 患者张三的住院号是 12345",
            "- OPENAI_API_KEY sk-abcdef1234567890",
            "NONE",
            "- 用户主要维护 BNCT TPS 的 C++ 工程",
        ]
        cleaned = sanitize_auto_memory_lines(lines)
        self.assertEqual(len(cleaned), 2)
        self.assertTrue(all("患者" not in line and "sk-" not in line for line in cleaned))

    def test_session_summary_appears_in_recent_context(self):
        store = SessionStore(self.data_dir)
        session_id = store.create("长会话")["id"]
        for index in range(12):
            store.add_message(session_id, "user" if index % 2 == 0 else "assistant", f"消息 {index}")
        store.set_summary(session_id, "用户在调试剂量模块，已完成编译配置。", 4)
        context = store.recent_context(session_id, limit=4)
        self.assertIn("更早对话的自动摘要", context)
        self.assertIn("剂量模块", context)
        self.assertIn("消息 11", context)
        self.assertNotIn("消息 0", context)
        # upto never regresses
        store.set_summary(session_id, "新摘要", 2)
        self.assertEqual(store.get(session_id)["summarizedUpTo"], 4)

    def test_explicit_memory_append_dedupes(self):
        root = self.data_dir / "proj"
        root.mkdir()
        first = append_agent_memory(root, "坐姿提醒：不要驼背", "personal")
        second = append_agent_memory(root, "坐姿提醒：不要驼背", "personal")
        self.assertNotIn("duplicate", first)
        self.assertTrue(second.get("duplicate"))
        content = (root / ".bnct_agent" / "memory.md").read_text(encoding="utf-8")
        self.assertEqual(content.count("坐姿提醒：不要驼背"), 1)

    def test_forget_memory_removes_from_both_stores(self):
        root = self.data_dir / "proj2"
        root.mkdir()
        append_agent_memory(root, "坐姿提醒：不要驼背", "personal")
        append_agent_memory(root, "周报默认用 Excel", "workflow")
        merge_auto_memory(self.data_dir, ["- 关注体态健康，高频提醒坐姿", "- 就职于软件部门"])
        result = forget_agent_memory(root, self.data_dir, "坐姿")
        self.assertEqual(result["removedExplicit"], 1)
        self.assertEqual(result["removedImplicit"], 1)
        local = (root / ".bnct_agent" / "memory.md").read_text(encoding="utf-8")
        self.assertNotIn("坐姿", local)
        self.assertIn("周报默认用 Excel", local)
        auto = read_auto_memory(self.data_dir)
        self.assertNotIn("坐姿", auto)
        self.assertIn("软件部门", auto)
        # Too-short match is rejected to avoid mass deletion.
        with self.assertRaises(ValueError):
            forget_agent_memory(root, self.data_dir, "x")

    def test_auto_memory_merges_and_dedupes(self):
        added = merge_auto_memory(self.data_dir, ["- 偏好中文回答", "- 偏好中文回答", "- 常用 VS2019 编译"])
        self.assertEqual(added, 2)
        again = merge_auto_memory(self.data_dir, ["- 偏好中文回答"])
        self.assertEqual(again, 0)
        content = read_auto_memory(self.data_dir)
        self.assertIn("常用 VS2019 编译", content)


class PersonalPanelTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / "tests" / "runtime_output"
        self.data_dir = base / f"personal-{uuid.uuid4().hex}"
        self.data_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_calendar_entry_lifecycle(self):
        created = add_calendar_entry(self.data_dir, "2026-07-08", "评审剂量模块", "09:30")
        self.assertEqual(created["date"], "2026-07-08")
        self.assertEqual(list_calendar_entries(self.data_dir)["count"], 1)
        removed = delete_calendar_entry(self.data_dir, created["id"], "")
        self.assertEqual(removed["removed"], 1)
        self.assertEqual(list_calendar_entries(self.data_dir)["count"], 0)

    def test_calendar_validation(self):
        with self.assertRaises(ValueError):
            add_calendar_entry(self.data_dir, "07-08", "缺年份")
        with self.assertRaises(ValueError):
            add_calendar_entry(self.data_dir, "2026-13-40", "非法日期")
        with self.assertRaises(ValueError):
            add_calendar_entry(self.data_dir, "2026-07-08", "")
        with self.assertRaises(ValueError):
            add_calendar_entry(self.data_dir, "2026-07-08", "时间格式错", "9点半")

    def test_calendar_delete_by_text_match(self):
        add_calendar_entry(self.data_dir, "2026-07-08", "评审剂量模块")
        add_calendar_entry(self.data_dir, "2026-07-09", "整理周报")
        removed = delete_calendar_entry(self.data_dir, "", "剂量")
        self.assertEqual(removed["removed"], 1)
        with self.assertRaises(ValueError):
            delete_calendar_entry(self.data_dir, "", "x")  # too-short match rejected

    def test_quick_link_lifecycle_and_open(self):
        add_quick_link(self.data_dir, "禅道", "https://zentao.example.com/bug")
        # Same name replaces the URL instead of duplicating.
        add_quick_link(self.data_dir, "禅道", "https://zentao.example.com/task")
        links = list_quick_links(self.data_dir)
        self.assertEqual(links["count"], 1)
        self.assertIn("task", links["links"][0]["url"])
        resolved = resolve_quick_link(self.data_dir, "禅道")
        self.assertIn("task", resolved["url"])
        # Fuzzy match works; unknown names list what exists.
        self.assertEqual(resolve_quick_link(self.data_dir, "禅")["name"], "禅道")
        with self.assertRaises(ValueError):
            resolve_quick_link(self.data_dir, "不存在")
        delete_quick_link(self.data_dir, "禅道")
        self.assertEqual(list_quick_links(self.data_dir)["count"], 0)

    def test_quick_link_rejects_non_http_urls(self):
        with self.assertRaises(ValueError):
            add_quick_link(self.data_dir, "本地脚本", "file:///C:/tools/run.bat")
        with self.assertRaises(ValueError):
            add_quick_link(self.data_dir, "脚本", "javascript:alert(1)")


if __name__ == "__main__":
    unittest.main()
