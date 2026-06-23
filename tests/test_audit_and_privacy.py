import json
import unittest
from pathlib import Path

from bnct_tps_agent.agent import ensure_prompt_is_deidentified
from bnct_tps_agent.audit import AuditLogger


class AuditAndPrivacyTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_prompt_identifier_assignment_is_rejected(self):
        with self.assertRaises(ValueError):
            ensure_prompt_is_deidentified("请分析 patient_name: ExamplePerson 的计划")

    def test_code_symbol_without_value_is_allowed(self):
        ensure_prompt_is_deidentified("搜索 patient_name 字段的定义")

    def test_tool_result_log_contains_no_payload_preview(self):
        logger = AuditLogger(self.root / "tests" / "runtime_output" / "audit")
        marker = "SENSITIVE_MARKER_FOR_TEST"
        logger.tool_result("read_project_text", {"ok": True, "result": {"content": marker}})
        last = json.loads(logger.path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertNotIn(marker, json.dumps(last))
        self.assertNotIn("preview", last)


if __name__ == "__main__":
    unittest.main()
