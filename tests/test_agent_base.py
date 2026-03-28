"""
Tests for AgentBase — health contract, status management, crash dumps.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from rudy.agents import AgentBase, LOGS_DIR


class DummyAgent(AgentBase):
    """A minimal concrete agent for testing."""
    name = "test-dummy"
    version = "0.1"

    def __init__(self):
        super().__init__()
        self._should_crash = False
        self._ran = False

    def run(self, **kwargs):
        self._ran = True
        if self._should_crash:
            raise RuntimeError("Intentional test crash")
        self.summarize("Dummy ran successfully")


class DetailedAgent(AgentBase):
    """An agent that returns custom health details."""
    name = "test-detailed"
    version = "0.2"

    def run(self, **kwargs):
        pass

    def _health_details(self) -> dict:
        return {"feeds_tracked": 42, "last_digest": "2026-03-28"}


# ── Status Management Tests ───────────────────────────────────


class TestAgentStatus:
    def test_initial_status(self):
        agent = DummyAgent()
        assert agent.status["agent"] == "test-dummy"
        assert agent.status["version"] == "0.1"
        assert agent.status["status"] == "starting"

    def test_alert_recording(self):
        agent = DummyAgent()
        agent.alert("Something critical")
        assert "Something critical" in agent.status["critical_alerts"]
        assert len(agent.status["critical_alerts"]) == 1

    def test_warning_recording(self):
        agent = DummyAgent()
        agent.warn("Something concerning")
        assert "Something concerning" in agent.status["warnings"]

    def test_action_recording(self):
        agent = DummyAgent()
        agent.action("Did a thing")
        assert "Did a thing" in agent.status["actions_taken"]

    def test_summarize(self):
        agent = DummyAgent()
        agent.summarize("All clear")
        assert agent.status["summary"] == "All clear"

    def test_execute_sets_healthy_on_success(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent.execute()
            assert agent.status["status"] == "healthy"
            assert agent._ran is True
            assert agent.status["duration_seconds"] >= 0

    def test_execute_sets_error_on_crash(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent._should_crash = True
            agent.execute()
            assert agent.status["status"] == "error"
            assert any("Intentional" in a for a in agent.status["critical_alerts"])


# ── Health Check Contract Tests ───────────────────────────────


class TestHealthCheck:
    def test_health_check_returns_all_required_keys(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            health = agent.health_check()
            required_keys = {
                "agent", "version", "status", "last_run",
                "age_seconds", "alerts", "warnings", "summary", "details"
            }
            assert set(health.keys()) == required_keys

    def test_never_run_agent(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            health = agent.health_check()
            assert health["status"] == "never_run"
            assert health["last_run"] == "never"
            assert health["age_seconds"] == float("inf")
            assert health["alerts"] == 0
            assert health["warnings"] == 0

    def test_healthy_agent(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent.execute()
            health = agent.health_check()
            assert health["status"] == "healthy"
            assert health["alerts"] == 0
            assert health["age_seconds"] < 10  # just ran
            assert health["summary"] == "Dummy ran successfully"

    def test_error_agent(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent._should_crash = True
            agent.execute()
            health = agent.health_check()
            assert health["status"] == "error"
            assert health["alerts"] >= 1

    def test_degraded_agent(self, tmp_path):
        """Agent ran OK but had critical alerts."""
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent.execute()
            # Manually add an alert to the persisted status
            status_file = tmp_path / "test-dummy-status.json"
            status = json.loads(status_file.read_text())
            status["critical_alerts"] = ["Found suspicious activity"]
            status_file.write_text(json.dumps(status))
            health = agent.health_check()
            assert health["status"] == "degraded"

    def test_stale_agent(self, tmp_path):
        """Agent hasn't run in over 24 hours."""
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent.execute()
            # Backdate the last_run to 2 days ago
            status_file = tmp_path / "test-dummy-status.json"
            status = json.loads(status_file.read_text())
            status["last_run"] = (datetime.now() - timedelta(days=2)).isoformat()
            status_file.write_text(json.dumps(status))
            health = agent.health_check()
            assert health["status"] == "stale"
            assert health["age_seconds"] > 86400

    def test_custom_health_details(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DetailedAgent()
            health = agent.health_check()
            assert health["details"]["feeds_tracked"] == 42

    def test_health_check_is_json_serializable(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent.execute()
            health = agent.health_check()
            # Must not raise
            serialized = json.dumps(health)
            assert isinstance(serialized, str)


# ── Crash Dump Tests ──────────────────────────────────────────


class TestCrashDumps:
    def test_crash_dump_created(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent._should_crash = True
            agent.execute()
            crash_dir = tmp_path / "crash-dumps"
            assert crash_dir.exists()
            dumps = list(crash_dir.glob("test-dummy-*.json"))
            assert len(dumps) == 1

    def test_crash_dump_contents(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent._should_crash = True
            agent.execute()
            dump_file = list((tmp_path / "crash-dumps").glob("*.json"))[0]
            dump = json.loads(dump_file.read_text())
            assert dump["agent"] == "test-dummy"
            assert dump["error_type"] == "RuntimeError"
            assert "Intentional" in dump["error_message"]
            assert "traceback" in dump

    def test_crash_marker_created(self, tmp_path):
        with patch("rudy.agents.LOGS_DIR", tmp_path):
            agent = DummyAgent()
            agent._should_crash = True
            agent.execute()
            marker = tmp_path / "CRASH-DETECTED.txt"
            assert marker.exists()
            assert "test-dummy" in marker.read_text()
