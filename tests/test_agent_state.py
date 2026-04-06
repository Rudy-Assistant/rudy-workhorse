"""Tests for rudy/core/agent_state.py (S201).

Tempdir-isolated; never touches the real Sentinel state file. Stdlib unittest only.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rudy.core import agent_state  # noqa: E402


class AgentStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_file = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_returns_default_when_missing(self):
        s = agent_state.load_state(self.state_file)
        self.assertEqual(s["run_count"], 0)
        self.assertIsNone(s["last_run"])
        self.assertEqual(s["streak"], 0)
        # Mutating returned dict must NOT mutate the module-level default.
        s["run_count"] = 99
        s2 = agent_state.load_state(self.state_file)
        self.assertEqual(s2["run_count"], 0)

    def test_load_returns_custom_default(self):
        s = agent_state.load_state(self.state_file, default={"foo": "bar"})
        self.assertEqual(s, {"foo": "bar"})

    def test_load_recovers_from_corrupt_file(self):
        self.state_file.write_text("{not valid json")
        s = agent_state.load_state(self.state_file)
        self.assertEqual(s["run_count"], 0)

    def test_save_writes_and_increments(self):
        s = agent_state.load_state(self.state_file)
        agent_state.save_state(self.state_file, s)
        self.assertTrue(self.state_file.exists())
        loaded = json.loads(self.state_file.read_text())
        self.assertEqual(loaded["run_count"], 1)
        self.assertIsNotNone(loaded["last_run"])
        # Second save increments.
        agent_state.save_state(self.state_file, loaded)
        loaded2 = json.loads(self.state_file.read_text())
        self.assertEqual(loaded2["run_count"], 2)

    def test_save_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "a" / "b" / "c" / "state.json"
        agent_state.save_state(nested, {"run_count": 5})
        self.assertTrue(nested.exists())
        self.assertEqual(json.loads(nested.read_text())["run_count"], 6)

    def test_save_returns_state(self):
        out = agent_state.save_state(self.state_file, {"x": 1})
        self.assertEqual(out["x"], 1)
        self.assertIn("last_run", out)


if __name__ == "__main__":
    unittest.main()
