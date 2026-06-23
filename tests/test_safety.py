import unittest

from bnct_tps_agent.safety import Risk, SafetyPolicy


class SafetyPolicyTests(unittest.TestCase):
    def test_read_is_allowed_without_callback(self):
        decision = SafetyPolicy().decide("read_project_text", Risk.READ, {})
        self.assertTrue(decision.allowed)

    def test_write_is_denied_without_callback(self):
        decision = SafetyPolicy().decide("write_project_text", Risk.WRITE, {})
        self.assertFalse(decision.allowed)

    def test_clinical_action_is_always_denied(self):
        policy = SafetyPolicy(lambda *_: True)
        decision = policy.decide("approve_plan", Risk.CLINICAL, {})
        self.assertFalse(decision.allowed)

    def test_approved_engineering_action_is_allowed(self):
        policy = SafetyPolicy(lambda *_: True)
        decision = policy.decide("run_unit_tests", Risk.EXECUTE, {})
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()

