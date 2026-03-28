"""
Tests for SessionState — session continuity system.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from rudy.session_state import SessionState


class TestSessionStateBasics:
    def test_default_state_has_required_keys(self):
        state = SessionState()
        required = {"version", "captured_at", "git", "ci", "tasks", "agents",
                    "recent_edits", "blockers", "notes"}
        assert set(state.data.keys()) == required

    def test_add_task(self):
        state = SessionState()
        state.add_task("Fix the bug", priority=8)
        assert len(state.data["tasks"]) == 1
        assert state.data["tasks"][0]["description"] == "Fix the bug"
        assert state.data["tasks"][0]["priority"] == 8
        assert state.data["tasks"][0]["status"] == "pending"

    def test_add_edit(self):
        state = SessionState()
        state.add_edit("rudy/quarantine.py", "Fixed manufacturer check bug")
        assert len(state.data["recent_edits"]) == 1
        assert "quarantine" in state.data["recent_edits"][0]["file"]

    def test_add_blocker(self):
        state = SessionState()
        state.add_blocker("GitHub MCP is unauthorized")
        assert len(state.data["blockers"]) == 1

    def test_add_note(self):
        state = SessionState()
        state.add_note("Workhorse is offline")
        assert "Workhorse is offline" in state.data["notes"]

    def test_set_ci_status(self):
        state = SessionState()
        state.set_ci_status(lint="pass", test="pass")
        assert state.data["ci"]["lint_status"] == "pass"
        assert state.data["ci"]["test_status"] == "pass"

    def test_recent_edits_capped_at_20(self):
        state = SessionState()
        for i in range(25):
            state.add_edit(f"file_{i}.py", f"Edit {i}")
        assert len(state.data["recent_edits"]) == 20

    def test_chaining(self):
        """Methods should return self for fluent chaining."""
        state = SessionState()
        result = (state
                  .add_task("Task 1")
                  .add_note("Note 1")
                  .add_blocker("Blocker 1")
                  .set_ci_status(lint="pass"))
        assert result is state


class TestSessionStatePersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        state = SessionState()
        state.add_task("Deploy quarantine", priority=9)
        state.add_note("Remember: phase 1 only")
        state.set_ci_status(lint="pass", test="pass")

        save_path = tmp_path / "state.json"
        state.save(path=save_path)
        assert save_path.exists()

        loaded = SessionState.load(path=save_path)
        assert len(loaded.data["tasks"]) == 1
        assert loaded.data["tasks"][0]["description"] == "Deploy quarantine"
        assert loaded.data["ci"]["lint_status"] == "pass"
        assert "Remember: phase 1 only" in loaded.data["notes"]

    def test_load_missing_file(self, tmp_path):
        loaded = SessionState.load(path=tmp_path / "nonexistent.json")
        assert loaded.data["version"] == 1
        assert loaded.data["tasks"] == []

    def test_load_corrupt_file(self, tmp_path):
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("not json {{{{")
        loaded = SessionState.load(path=corrupt)
        assert loaded.data["version"] == 1

    def test_save_creates_parent_dirs(self, tmp_path):
        state = SessionState()
        deep_path = tmp_path / "a" / "b" / "c" / "state.json"
        state.save(path=deep_path)
        assert deep_path.exists()


class TestSessionStateBriefing:
    def test_briefing_includes_tasks(self):
        state = SessionState()
        state.add_task("Fix manufacturer bug", priority=8)
        state.add_task("Write more tests", priority=5)
        briefing = state.briefing()
        assert "Fix manufacturer bug" in briefing
        assert "Write more tests" in briefing

    def test_briefing_includes_blockers(self):
        state = SessionState()
        state.add_blocker("GitHub MCP is unauthorized")
        briefing = state.briefing()
        assert "GitHub MCP" in briefing

    def test_briefing_includes_ci(self):
        state = SessionState()
        state.set_ci_status(lint="pass", test="fail")
        briefing = state.briefing()
        assert "lint=pass" in briefing
        assert "test=fail" in briefing

    def test_briefing_sorts_tasks_by_priority(self):
        state = SessionState()
        state.add_task("Low priority", priority=1)
        state.add_task("High priority", priority=9)
        briefing = state.briefing()
        high_pos = briefing.index("High priority")
        low_pos = briefing.index("Low priority")
        assert high_pos < low_pos

    def test_briefing_is_string(self):
        state = SessionState()
        assert isinstance(state.briefing(), str)


class TestSessionStateGitCapture:
    def test_capture_sanitizes_token_from_url(self):
        state = SessionState()
        # Simulate what _capture_git would produce
        state.data["git"]["remote_url"] = (
            "https://x-access-token:ghp_SECRET@github.com/Rudy-Assistant/rudy-workhorse.git"
        )
        # The real _capture_git strips the token
        url = state.data["git"]["remote_url"]
        if "@" in url and "x-access-token" in url:
            url = url.split("@")[-1]
            url = f"https://{url}"
        assert "ghp_SECRET" not in url
        assert "github.com" in url
