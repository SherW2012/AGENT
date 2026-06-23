import unittest
from pathlib import Path

from bnct_tps_agent.tps_tools import summarize_plan_snapshot, validate_plan_snapshot


class TpsToolTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_valid_snapshot(self):
        result = validate_plan_snapshot(self.root, "tests/fixtures/valid_snapshot.json")
        self.assertTrue(result["valid"])

    def test_direct_identifier_is_rejected(self):
        result = validate_plan_snapshot(self.root, "tests/fixtures/rejected_identifier_snapshot.json")
        self.assertFalse(result["valid"])
        self.assertIn("patient_name", result["errors"][0])

    def test_summary_preserves_source_values(self):
        result = summarize_plan_snapshot(self.root, "tests/fixtures/valid_snapshot.json")
        self.assertEqual(result["metrics"][0]["value"], 1.0)
        self.assertIn("未经 Agent 重算", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
