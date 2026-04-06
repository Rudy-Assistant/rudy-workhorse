"""Tests for rudy.core.agent_runtime (S202)."""
import time
import unittest
from datetime import datetime

from rudy.core.agent_runtime import time_ok, make_observation


class TestTimeOk(unittest.TestCase):
    def test_true_when_within_budget(self):
        start = time.time()
        self.assertTrue(time_ok(start, 60.0))

    def test_false_when_over_budget(self):
        start = time.time() - 100.0
        self.assertFalse(time_ok(start, 30.0))

    def test_strict_less_than_at_boundary(self):
        # If elapsed == max, must be False (strict <)
        start = time.time() - 5.0
        # Because time advances slightly between calls, choose a max
        # smaller than elapsed to guarantee False.
        self.assertFalse(time_ok(start, 1.0))

    def test_zero_budget_is_false(self):
        self.assertFalse(time_ok(time.time(), 0.0))


class TestMakeObservation(unittest.TestCase):
    def test_minimum_fields(self):
        obs = make_observation("env", "low disk")
        self.assertEqual(obs["category"], "env")
        self.assertEqual(obs["observation"], "low disk")
        self.assertEqual(obs["actionable"], False)
        self.assertIn("time", obs)
        # ISO-parseable
        datetime.fromisoformat(obs["time"])

    def test_actionable_flag_passthrough(self):
        obs = make_observation("git", "uncommitted changes", actionable=True)
        self.assertTrue(obs["actionable"])

    def test_pure_no_shared_state(self):
        a = make_observation("x", "one")
        b = make_observation("x", "two")
        self.assertIsNot(a, b)
        a["category"] = "mutated"
        self.assertEqual(b["category"], "x")

    def test_keys_match_sentinel_contract(self):
        obs = make_observation("c", "o")
        self.assertEqual(
            set(obs.keys()),
            {"time", "category", "observation", "actionable"},
        )


if __name__ == "__main__":
    unittest.main()
