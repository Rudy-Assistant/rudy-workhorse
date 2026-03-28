"""
Tests for rudy.agents.sentinel — the Sentinel (trickle) agent.

Tests cover: initialization, observation recording, state management,
time budget enforcement, agent health scanning, finalization, and
the run() orchestration. External dependencies (subprocess, file system,
network) are mocked.
"""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure test directories exist before import
desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
(desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)

from rudy.agents.sentinel import Sentinel
from rudy.agents import LOGS_DIR


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sentinel(tmp_path, monkeypatch):
    """Create a Sentinel with all file paths redirected to tmp_path."""
    s = Sentinel()
    monkeypatch.setattr(type(s), "STATE_FILE", tmp_path / "sentinel-state.json")
    monkeypatch.setattr(type(s), "OBSERVATIONS_FILE", tmp_path / "sentinel-observations.json")
    monkeypatch.setattr(type(s), "MANIFEST_FILE", tmp_path / "capability-manifest.json")
    monkeypatch.setattr(type(s), "BRIEFING_FILE", tmp_path / "session-briefing.md")
    monkeypatch.setattr(type(s), "CONTINUATION_FILE", tmp_path / "continuation-prompt.md")
    return s


# ── Initialization Tests ─────────────────────────────────────────

class TestInit:
    def test_name_and_version(self):
        """Sentinel should identify itself correctly."""
        s = Sentinel()
        assert s.name == "sentinel"
        assert s.version == "2.0"

    def test_max_runtime(self):
        """Max runtime should be 30 seconds."""
        s = Sentinel()
        assert s.MAX_RUNTIME == 30


# ── Time Budget Tests ────────────────────────────────────────────

class TestTimeBudget:
    def test_time_ok_within_budget(self, sentinel):
        """_time_ok should return True when under MAX_RUNTIME."""
        sentinel.start = time.time()
        assert sentinel._time_ok() is True

    def test_time_ok_expired(self, sentinel):
        """_time_ok should return False when over MAX_RUNTIME."""
        sentinel.start = time.time() - 60  # 60 seconds ago
        assert sentinel._time_ok() is False

    def test_time_ok_initializes_start(self, sentinel):
        """_time_ok should initialize start time if not set."""
        if hasattr(sentinel, "start"):
            delattr(sentinel, "start")
        result = sentinel._time_ok()
        assert result is True
        assert hasattr(sentinel, "start")


# ── Observation Tests ─────────────────────────────────────────────

class TestObservation:
    def test_observe_records(self, sentinel):
        """_observe should record an observation with all fields."""
        sentinel.observations = []
        sentinel._observe("test_cat", "something happened", actionable=True)

        assert len(sentinel.observations) == 1
        obs = sentinel.observations[0]
        assert obs["category"] == "test_cat"
        assert obs["observation"] == "something happened"
        assert obs["actionable"] is True
        assert "time" in obs

    def test_observe_defaults_not_actionable(self, sentinel):
        """Observations should default to not actionable."""
        sentinel.observations = []
        sentinel._observe("cat", "msg")
        assert sentinel.observations[0]["actionable"] is False

    def test_observe_initializes_list(self, sentinel):
        """_observe should create observations list if missing."""
        if hasattr(sentinel, "observations"):
            delattr(sentinel, "observations")
        sentinel._observe("cat", "msg")
        assert len(sentinel.observations) == 1

    def test_multiple_observations_accumulate(self, sentinel):
        """Multiple observations should accumulate in order."""
        sentinel.observations = []
        sentinel._observe("a", "first")
        sentinel._observe("b", "second")
        sentinel._observe("c", "third")
        assert len(sentinel.observations) == 3
        assert sentinel.observations[0]["category"] == "a"
        assert sentinel.observations[2]["category"] == "c"


# ── State Management Tests ───────────────────────────────────────

class TestStateManagement:
    def test_load_fresh_state(self, sentinel):
        """Fresh state should have expected default structure."""
        state = sentinel._load_state()
        assert state["run_count"] == 0
        assert state["last_run"] is None
        assert state["file_hashes"] == {}
        assert state["last_agent_statuses"] == {}
        assert state["improvement_log"] == []
        assert state["streak"] == 0

    def test_load_existing_state(self, sentinel, tmp_path):
        """Should load previously saved state."""
        state_data = {"run_count": 42, "streak": 10, "last_run": "2026-03-28T10:00:00"}
        type(sentinel).STATE_FILE = tmp_path / "sentinel-state.json"
        (tmp_path / "sentinel-state.json").write_text(json.dumps(state_data))

        state = sentinel._load_state()
        assert state["run_count"] == 42
        assert state["streak"] == 10

    def test_load_corrupt_state_returns_default(self, sentinel, tmp_path):
        """Corrupt state file should return defaults."""
        type(sentinel).STATE_FILE = tmp_path / "sentinel-state.json"
        (tmp_path / "sentinel-state.json").write_text("not json!!")

        state = sentinel._load_state()
        assert state["run_count"] == 0

    def test_save_state_increments_count(self, sentinel, tmp_path):
        """_save_state should increment run_count and set last_run."""
        type(sentinel).STATE_FILE = tmp_path / "sentinel-state.json"
        state = {"run_count": 5, "streak": 3}
        sentinel._save_state(state)

        saved = json.loads((tmp_path / "sentinel-state.json").read_text())
        assert saved["run_count"] == 6
        assert "last_run" in saved

    def test_save_state_preserves_fields(self, sentinel, tmp_path):
        """_save_state should preserve other fields in state."""
        type(sentinel).STATE_FILE = tmp_path / "sentinel-state.json"
        state = {"run_count": 0, "custom_field": "preserved"}
        sentinel._save_state(state)

        saved = json.loads((tmp_path / "sentinel-state.json").read_text())
        assert saved["custom_field"] == "preserved"


# ── Agent Health Scan Tests ──────────────────────────────────────

class TestAgentHealthScan:
    def test_detects_status_change(self, sentinel, monkeypatch):
        """Should observe when an agent's status changes."""
        sentinel.observations = []

        # Mock read_status to return "error" for system_master
        def mock_read_status(name):
            if name == "system_master":
                return {"status": "error", "last_run": "2026-03-28T10:00:00"}
            return {"status": "healthy", "last_run": "2026-03-28T10:00:00"}

        monkeypatch.setattr(sentinel, "read_status", mock_read_status)

        state = {
            "last_agent_statuses": {
                "system_master": {"status": "healthy", "last_run": "2026-03-28T09:00:00"},
            }
        }
        sentinel._scan_agent_health(state)

        assert any(
            "system_master" in o["observation"] and "error" in o["observation"]
            for o in sentinel.observations
        )

    def test_detects_stale_system_master(self, sentinel, monkeypatch):
        """Should flag system_master if it hasn't run in over 1 hour."""
        sentinel.observations = []

        old_time = (datetime.now() - timedelta(hours=2)).isoformat()

        def mock_read_status(name):
            return {"status": "healthy", "last_run": old_time}

        monkeypatch.setattr(sentinel, "read_status", mock_read_status)

        state = {"last_agent_statuses": {}}
        sentinel._scan_agent_health(state)

        assert any(
            "staleness" in o["category"] and "system_master" in o["observation"]
            for o in sentinel.observations
        )

    def test_no_alert_for_unknown_previous(self, sentinel, monkeypatch):
        """Should not flag status change when previous was 'unknown'."""
        sentinel.observations = []

        def mock_read_status(name):
            return {"status": "healthy", "last_run": "2026-03-28T10:00:00"}

        monkeypatch.setattr(sentinel, "read_status", mock_read_status)

        state = {"last_agent_statuses": {}}  # No previous = unknown
        sentinel._scan_agent_health(state)

        assert not any(o["category"] == "agent_change" for o in sentinel.observations)

    def test_updates_agent_statuses_in_state(self, sentinel, monkeypatch):
        """After scan, state should contain current agent statuses."""
        sentinel.observations = []

        def mock_read_status(name):
            return {"status": "healthy", "last_run": "2026-03-28T10:00:00"}

        monkeypatch.setattr(sentinel, "read_status", mock_read_status)

        state = {"last_agent_statuses": {}}
        sentinel._scan_agent_health(state)

        assert "system_master" in state["last_agent_statuses"]
        assert state["last_agent_statuses"]["system_master"]["status"] == "healthy"


# ── Work Queue Scan Tests ────────────────────────────────────────

class TestWorkQueueScan:
    def test_detects_pending_items(self, sentinel, tmp_path, monkeypatch):
        """Should observe pending items in work queue."""
        sentinel.observations = []

        queue_file = tmp_path / "task-queue.json"
        queue_file.write_text(json.dumps({"pending": ["task1", "task2", "task3"]}))

        monkeypatch.setattr("rudy.agents.sentinel.LOGS_DIR", tmp_path)

        state = {}
        sentinel._scan_work_queue(state)

        assert any("3 items in work queue" in o["observation"] for o in sentinel.observations)

    def test_no_observation_for_missing_queue(self, sentinel, tmp_path, monkeypatch):
        """Should not observe anything if queue file doesn't exist."""
        sentinel.observations = []
        monkeypatch.setattr("rudy.agents.sentinel.LOGS_DIR", tmp_path)

        state = {}
        sentinel._scan_work_queue(state)

        assert len(sentinel.observations) == 0


# ── Incoming Requests Scan Tests ─────────────────────────────────

class TestIncomingRequests:
    def test_detects_new_commands(self, sentinel, tmp_path, monkeypatch):
        """Should observe new pending command files."""
        sentinel.observations = []

        cmd_dir = tmp_path / "rudy-commands"
        cmd_dir.mkdir()
        (cmd_dir / "task1.py").write_text("print('hi')")
        # No .result file = pending

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)

        state = {"pending_commands": []}
        sentinel._scan_incoming_requests(state)

        assert any("task1.py" in o["observation"] for o in sentinel.observations)

    def test_detects_completed_commands(self, sentinel, tmp_path, monkeypatch):
        """Should observe when commands complete."""
        sentinel.observations = []

        cmd_dir = tmp_path / "rudy-commands"
        cmd_dir.mkdir()
        # No pending files anymore

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)

        state = {"pending_commands": ["old_task.py"]}
        sentinel._scan_incoming_requests(state)

        assert any("old_task.py" in o["observation"] for o in sentinel.observations)

    def test_ignores_running_commands(self, sentinel, tmp_path, monkeypatch):
        """Should ignore files prefixed with _running_."""
        sentinel.observations = []

        cmd_dir = tmp_path / "rudy-commands"
        cmd_dir.mkdir()
        (cmd_dir / "_running_task.py").write_text("print('in progress')")

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)

        state = {"pending_commands": []}
        sentinel._scan_incoming_requests(state)

        assert not any("_running_" in o["observation"] for o in sentinel.observations)


# ── Finalize Tests ───────────────────────────────────────────────

class TestFinalize:
    def test_increments_streak_when_healthy(self, sentinel, tmp_path):
        """Streak should increment when no critical alerts."""
        sentinel.observations = []
        type(sentinel).OBSERVATIONS_FILE = tmp_path / "obs.json"

        state = {"streak": 5, "run_count": 0}
        with patch.object(sentinel, "_save_state"):
            with patch.object(sentinel, "_file_github_anomalies"):
                sentinel._finalize(state)

        assert state["streak"] == 6

    def test_resets_streak_on_critical_alert(self, sentinel, tmp_path):
        """Streak should reset when there are critical alerts."""
        sentinel.observations = []
        sentinel.status["critical_alerts"] = ["something bad"]
        type(sentinel).OBSERVATIONS_FILE = tmp_path / "obs.json"

        state = {"streak": 10, "run_count": 0}
        with patch.object(sentinel, "_save_state"):
            with patch.object(sentinel, "_file_github_anomalies"):
                sentinel._finalize(state)

        assert state["streak"] == 0

    def test_saves_observations_to_file(self, sentinel, tmp_path):
        """Observations should be written to disk."""
        sentinel.observations = [
            {"time": "now", "category": "test", "observation": "test obs", "actionable": False}
        ]
        type(sentinel).OBSERVATIONS_FILE = tmp_path / "obs.json"

        state = {"streak": 0, "run_count": 0}
        with patch.object(sentinel, "_save_state"):
            with patch.object(sentinel, "_file_github_anomalies"):
                sentinel._finalize(state)

        saved = json.loads((tmp_path / "obs.json").read_text())
        assert len(saved) == 1
        assert saved[0]["category"] == "test"

    def test_observations_capped_at_100(self, sentinel, tmp_path):
        """Observation history should be capped at 100."""
        existing = [{"time": "old", "category": f"old-{i}", "observation": "x", "actionable": False}
                    for i in range(90)]
        type(sentinel).OBSERVATIONS_FILE = tmp_path / "obs.json"
        (tmp_path / "obs.json").write_text(json.dumps(existing))

        sentinel.observations = [
            {"time": "new", "category": f"new-{i}", "observation": "y", "actionable": False}
            for i in range(20)
        ]

        state = {"streak": 0, "run_count": 0}
        with patch.object(sentinel, "_save_state"):
            with patch.object(sentinel, "_file_github_anomalies"):
                sentinel._finalize(state)

        saved = json.loads((tmp_path / "obs.json").read_text())
        assert len(saved) == 100

    def test_generates_summary(self, sentinel, tmp_path):
        """Finalize should set a human-readable summary."""
        sentinel.observations = [
            {"time": "now", "category": "test", "observation": "test", "actionable": True},
            {"time": "now", "category": "test", "observation": "test2", "actionable": False},
        ]
        type(sentinel).OBSERVATIONS_FILE = tmp_path / "obs.json"

        state = {"streak": 3, "run_count": 0}
        with patch.object(sentinel, "_save_state"):
            with patch.object(sentinel, "_file_github_anomalies"):
                sentinel._finalize(state)

        assert "2 things" in sentinel.status["summary"]
        assert "1 actionable" in sentinel.status["summary"]
        assert "Streak: 4" in sentinel.status["summary"]


# ── Capability Scan Tests ────────────────────────────────────────

class TestCapabilityScan:
    def test_skips_when_cached_and_not_4th_run(self, sentinel, tmp_path):
        """Should skip manifest generation if cached and not 4th run."""
        type(sentinel).MANIFEST_FILE = tmp_path / "manifest.json"
        (tmp_path / "manifest.json").write_text("{}")

        sentinel.observations = []
        state = {"run_count": 5}  # 5 % 4 != 0
        sentinel._scan_capabilities(state)

        # Should not have updated observations about capabilities
        assert not any("capabilities" in o.get("category", "") for o in sentinel.observations)

    def test_builds_manifest_on_4th_run(self, sentinel, tmp_path, monkeypatch):
        """Should build manifest on every 4th run."""
        type(sentinel).MANIFEST_FILE = tmp_path / "manifest.json"

        # Create a minimal rudy directory
        rudy_dir = tmp_path / "rudy"
        rudy_dir.mkdir()
        (rudy_dir / "email_multi.py").write_text("# module")
        (rudy_dir / "network_defense.py").write_text("# module")

        agents_dir = rudy_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "sentinel.py").write_text("# agent")

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)
        monkeypatch.setattr("rudy.agents.sentinel.LOGS_DIR", tmp_path)

        sentinel.observations = []
        state = {"run_count": 4}  # 4 % 4 == 0
        sentinel._scan_capabilities(state)

        assert (tmp_path / "manifest.json").exists()
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert len(manifest["modules"]) == 2  # email_multi, network_defense
        assert "sentinel" in manifest["agents"]


# ── Service Health Scan Tests ────────────────────────────────────

class TestServiceHealthScan:
    def test_detects_service_state_change(self, sentinel, monkeypatch):
        """Should observe when a service changes state."""
        sentinel.observations = []

        # Mock all subprocess calls to return quickly
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        monkeypatch.setattr("rudy.agents.sentinel.subprocess.run", lambda *a, **kw: mock_result)

        # Mock urllib for Ollama check
        monkeypatch.setattr("urllib.request.urlopen", MagicMock(side_effect=Exception("down")))

        state = {
            "service_health": {
                "ollama": "running (3 models)",
                "tailscale": "connected",
                "rustdesk": "running",
                "command_runner": "running (1 proc)",
            }
        }
        sentinel._scan_service_health(state)

        # Services should have changed from their previous state
        assert any(o["category"] == "service_change" for o in sentinel.observations)

    def test_first_run_no_change_alerts(self, sentinel, monkeypatch):
        """First run (no previous state) should not flag changes."""
        sentinel.observations = []

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        monkeypatch.setattr("rudy.agents.sentinel.subprocess.run", lambda *a, **kw: mock_result)
        monkeypatch.setattr("urllib.request.urlopen", MagicMock(side_effect=Exception("down")))

        state = {"service_health": {}}
        sentinel._scan_service_health(state)

        # Should NOT have any service_change observations
        assert not any(o["category"] == "service_change" for o in sentinel.observations)


# ── Environment Scan Tests ───────────────────────────────────────

class TestEnvironmentScan:
    def test_detects_file_change(self, sentinel, tmp_path, monkeypatch):
        """Should observe when a critical file's hash changes."""
        sentinel.observations = []

        # Create a "critical" file
        test_file = tmp_path / "CLAUDE.md"
        test_file.write_text("original content")

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)

        import hashlib
        old_hash = hashlib.md5(b"different content").hexdigest()[:12]

        state = {"file_hashes": {"CLAUDE.md": old_hash}, "last_disk_free_gb": 100}

        # Mock shutil.disk_usage
        monkeypatch.setattr("shutil.disk_usage", lambda p: (500 * 1024**3, 400 * 1024**3, 100 * 1024**3))

        sentinel._scan_environment(state)

        assert any(
            "config_change" in o["category"] and "CLAUDE.md" in o["observation"]
            for o in sentinel.observations
        )

    def test_no_alert_for_first_scan(self, sentinel, tmp_path, monkeypatch):
        """First scan (no previous hashes) should not report changes."""
        sentinel.observations = []

        test_file = tmp_path / "CLAUDE.md"
        test_file.write_text("content")

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)
        monkeypatch.setattr("shutil.disk_usage", lambda p: (500 * 1024**3, 400 * 1024**3, 100 * 1024**3))

        state = {"file_hashes": {}}
        sentinel._scan_environment(state)

        assert not any("config_change" in o["category"] for o in sentinel.observations)

    def test_detects_disk_shrinkage(self, sentinel, tmp_path, monkeypatch):
        """Should observe when disk space drops significantly."""
        sentinel.observations = []

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)
        # Report 45 GB free (was 50)
        monkeypatch.setattr("shutil.disk_usage", lambda p: (500 * 1024**3, 455 * 1024**3, 45 * 1024**3))

        state = {"file_hashes": {}, "last_disk_free_gb": 50}
        sentinel._scan_environment(state)

        assert any("disk_trend" in o["category"] for o in sentinel.observations)


# ── Opportunity Scan Tests ───────────────────────────────────────

class TestOpportunityScan:
    def test_detects_stale_results(self, sentinel, tmp_path, monkeypatch):
        """Should flag stale .result files older than 24h."""
        sentinel.observations = []

        cmd_dir = tmp_path / "rudy-commands"
        cmd_dir.mkdir()

        # Create 6 old result files
        for i in range(6):
            f = cmd_dir / f"task{i}.result"
            f.write_text("done")
            # Set modification time to 2 days ago
            old_time = time.time() - 48 * 3600
            os.utime(f, (old_time, old_time))

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)
        monkeypatch.setattr("rudy.agents.sentinel.LOGS_DIR", tmp_path)

        state = {}
        sentinel._scan_for_opportunities(state)

        assert any("result files older than 24h" in o["observation"] for o in sentinel.observations)

    def test_detects_large_logs(self, sentinel, tmp_path, monkeypatch):
        """Should flag when total log size exceeds 50 MB."""
        sentinel.observations = []

        # Create a large log file
        log_file = tmp_path / "big.log"
        log_file.write_bytes(b"x" * (60 * 1024 * 1024))  # 60 MB

        cmd_dir = tmp_path / "rudy-commands"
        cmd_dir.mkdir()

        monkeypatch.setattr("rudy.agents.sentinel.DESKTOP", tmp_path)
        monkeypatch.setattr("rudy.agents.sentinel.LOGS_DIR", tmp_path)

        state = {}
        sentinel._scan_for_opportunities(state)

        assert any("log size" in o["observation"] for o in sentinel.observations)
