"""Comprehensive tests for rudy.offline_ops module."""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, call, mock_open
import socket

import rudy.offline_ops as mod


@pytest.fixture
def tmp_offline_dirs(tmp_path, monkeypatch):
    """Set up temporary offline directories and monkeypatch path constants."""
    offline_dir = tmp_path / "offline"
    offline_dir.mkdir()

    queue_file = offline_dir / "action-queue.json"
    state_file = offline_dir / "offline-state.json"
    decision_log = offline_dir / "decisions.json"

    monkeypatch.setattr(mod, "OFFLINE_DIR", offline_dir)
    monkeypatch.setattr(mod, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(mod, "STATE_FILE", state_file)
    monkeypatch.setattr(mod, "DECISION_LOG", decision_log)
    monkeypatch.setattr(mod, "DESKTOP", tmp_path)
    monkeypatch.setattr(mod, "LOGS", tmp_path / "logs")

    return {
        "offline_dir": offline_dir,
        "queue_file": queue_file,
        "state_file": state_file,
        "decision_log": decision_log,
    }


class TestLoadAndSaveJson:
    """Test JSON loading and saving utilities."""

    def test_load_json_existing_file(self, tmp_path):
        """Load valid JSON from file."""
        test_file = tmp_path / "test.json"
        data = {"key": "value", "number": 42}
        test_file.write_text(json.dumps(data))

        result = mod._load_json(test_file)
        assert result == data

    def test_load_json_nonexistent_file(self, tmp_path):
        """Load from nonexistent file returns default."""
        test_file = tmp_path / "nonexistent.json"
        result = mod._load_json(test_file)
        assert result == {}

        result_custom = mod._load_json(test_file, {"default": True})
        assert result_custom == {"default": True}

    def test_load_json_invalid_file(self, tmp_path):
        """Load invalid JSON returns default."""
        test_file = tmp_path / "invalid.json"
        test_file.write_text("not valid json {")

        result = mod._load_json(test_file)
        assert result == {}

    def test_save_json_creates_dirs(self, tmp_path):
        """Save JSON creates parent directories."""
        nested_file = tmp_path / "a" / "b" / "c" / "test.json"
        data = {"nested": "data"}

        mod._save_json(nested_file, data)

        assert nested_file.exists()
        assert json.loads(nested_file.read_text()) == data

    def test_save_json_overwrites(self, tmp_path):
        """Save JSON overwrites existing file."""
        test_file = tmp_path / "test.json"
        mod._save_json(test_file, {"old": "data"})
        mod._save_json(test_file, {"new": "data"})

        assert json.loads(test_file.read_text()) == {"new": "data"}

    def test_save_json_with_datetime(self, tmp_path):
        """Save JSON converts datetime objects via default=str."""
        test_file = tmp_path / "test.json"
        now = datetime.now()
        data = {"time": now, "value": 123}

        mod._save_json(test_file, data)

        loaded = json.loads(test_file.read_text())
        assert isinstance(loaded["time"], str)
        assert loaded["value"] == 123


class TestConnectivityChecker:
    """Test ConnectivityChecker class."""

    def test_check_dns_success(self):
        """DNS check succeeds when socket connection works."""
        checker = mod.ConnectivityChecker()

        with patch("socket.create_connection") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value = mock_sock

            result = checker.check_dns()

            assert result is True
            mock_socket.assert_called_once()
            mock_sock.close.assert_called_once()

    def test_check_dns_failure(self):
        """DNS check fails when all targets are unreachable."""
        checker = mod.ConnectivityChecker()

        with patch("socket.create_connection") as mock_socket:
            mock_socket.side_effect = socket.error("Connection refused")

            result = checker.check_dns()

            assert result is False
            assert mock_socket.call_count == 3  # Three DNS targets

    def test_check_dns_partial_failure(self):
        """DNS check succeeds if any target responds."""
        checker = mod.ConnectivityChecker()

        with patch("socket.create_connection") as mock_socket:
            mock_sock = MagicMock()
            # First target fails, second succeeds
            mock_socket.side_effect = [socket.error("Failed"), mock_sock]

            result = checker.check_dns()

            assert result is True
            mock_sock.close.assert_called_once()

    def test_check_http_success(self):
        """HTTP check succeeds with 200/204 response."""
        checker = mod.ConnectivityChecker()

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_get.return_value = mock_resp

            result = checker.check_http()

            assert result is True

    def test_check_http_failure(self):
        """HTTP check fails when all targets fail."""
        checker = mod.ConnectivityChecker()

        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Network error")

            result = checker.check_http()

            assert result is False

    def test_check_http_missing_import(self):
        """HTTP check fails gracefully without requests library."""
        checker = mod.ConnectivityChecker()

        with patch.dict("sys.modules", {"requests": None}):
            result = checker.check_http()
            assert result is False

    def test_check_dns_resolution_success(self):
        """DNS resolution check succeeds when domain resolves."""
        checker = mod.ConnectivityChecker()

        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [("AF_INET", 1, 6, "", ("192.0.2.1", 443))]

            result = checker.check_dns_resolution()

            assert result is True
            mock_gai.assert_called_once_with(
                "www.google.com", 443, socket.AF_INET, socket.SOCK_STREAM
            )

    def test_check_dns_resolution_failure(self):
        """DNS resolution check fails when domain cannot be resolved."""
        checker = mod.ConnectivityChecker()

        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.side_effect = socket.gaierror("Name not known")

            result = checker.check_dns_resolution()

            assert result is False

    def test_full_check_online(self):
        """Full check returns online when DNS and HTTP succeed."""
        checker = mod.ConnectivityChecker()

        with patch.object(checker, "check_dns") as mock_dns, \
             patch.object(checker, "check_http") as mock_http, \
             patch.object(checker, "check_dns_resolution") as mock_resolution:
            mock_dns.return_value = True
            mock_http.return_value = True
            mock_resolution.return_value = True

            result = checker.full_check()

            assert result["online"] is True
            assert result["dns_socket"] is True
            assert result["http"] is True
            assert result["dns_resolution"] is True
            assert "timestamp" in result

    def test_full_check_offline_no_dns(self):
        """Full check returns offline when DNS fails."""
        checker = mod.ConnectivityChecker()

        with patch.object(checker, "check_dns") as mock_dns:
            mock_dns.return_value = False

            result = checker.full_check()

            assert result["online"] is False
            assert result["dns_socket"] is False
            assert result["http"] is False  # Not called

    def test_full_check_offline_dns_resolution_only(self):
        """Full check offline when DNS socket works but no HTTP/resolution."""
        checker = mod.ConnectivityChecker()

        with patch.object(checker, "check_dns") as mock_dns, \
             patch.object(checker, "check_http") as mock_http, \
             patch.object(checker, "check_dns_resolution") as mock_resolution:
            mock_dns.return_value = True
            mock_http.return_value = False
            mock_resolution.return_value = False

            result = checker.full_check()

            assert result["online"] is False


class TestActionQueue:
    """Test ActionQueue class."""

    def test_init_creates_dir(self, tmp_offline_dirs):
        """Init creates offline directory."""
        mod.ActionQueue()

        assert tmp_offline_dirs["offline_dir"].exists()

    def test_init_loads_existing_queue(self, tmp_offline_dirs):
        """Init loads existing queue file."""
        existing = {
            "actions": [{"id": "test_1", "status": "pending"}],
            "replayed": []
        }
        tmp_offline_dirs["queue_file"].write_text(json.dumps(existing))

        queue = mod.ActionQueue()

        assert queue.queue == existing

    def test_init_creates_default_queue(self, tmp_offline_dirs):
        """Init creates default queue if file doesn't exist."""
        queue = mod.ActionQueue()

        assert "actions" in queue.queue
        assert "replayed" in queue.queue
        assert isinstance(queue.queue["actions"], list)

    def test_add_action(self, tmp_offline_dirs):
        """Add action appends to queue and persists."""
        queue = mod.ActionQueue()

        queue.add("send_email", {"to": "test@example.com"}, priority=3)

        assert len(queue.queue["actions"]) == 1
        action = queue.queue["actions"][0]
        assert action["type"] == "send_email"
        assert action["payload"] == {"to": "test@example.com"}
        assert action["priority"] == 3
        assert action["status"] == "pending"
        assert "id" in action
        assert "queued_at" in action

    def test_add_action_persists_to_file(self, tmp_offline_dirs):
        """Add action writes to disk."""
        queue = mod.ActionQueue()
        queue.add("webhook", {"url": "http://example.com"})

        # Read from disk
        saved = json.loads(tmp_offline_dirs["queue_file"].read_text())
        assert len(saved["actions"]) == 1
        assert saved["actions"][0]["type"] == "webhook"

    def test_pending_count(self, tmp_offline_dirs):
        """Pending count returns correct number."""
        queue = mod.ActionQueue()

        queue.add("send_email", {})
        queue.add("webhook", {})
        assert queue.pending_count == 2

        # Mark one as completed
        queue.queue["actions"][0]["status"] = "completed"
        assert queue.pending_count == 1

    def test_get_summary(self, tmp_offline_dirs):
        """Get summary returns queue statistics."""
        queue = mod.ActionQueue()

        queue.add("send_email", {})
        queue.add("webhook", {})
        queue.queue["replayed"].append({"type": "old_action"})

        summary = queue.get_summary()

        assert summary["pending"] == 2
        assert summary["total_queued"] == 2
        assert summary["total_replayed"] == 1

    def test_drain_empty_queue(self, tmp_offline_dirs):
        """Drain on empty queue returns empty results."""
        queue = mod.ActionQueue()

        results = queue.drain()

        assert results == []

    def test_drain_sorts_by_priority(self, tmp_offline_dirs):
        """Drain executes actions in priority order."""
        queue = mod.ActionQueue()

        queue.add("action_1", {}, priority=5)
        queue.add("action_2", {}, priority=1)
        queue.add("action_3", {}, priority=3)

        with patch.object(queue, "_execute") as mock_execute:
            mock_execute.return_value = {"success": True}
            queue.drain()

        calls = mock_execute.call_args_list
        assert calls[0][0][0]["priority"] == 1  # First
        assert calls[1][0][0]["priority"] == 3  # Second
        assert calls[2][0][0]["priority"] == 5  # Third

    def test_drain_handles_success(self, tmp_offline_dirs):
        """Drain marks successful actions as completed."""
        queue = mod.ActionQueue()
        queue.add("test_action", {})

        with patch.object(queue, "_execute") as mock_execute:
            mock_execute.return_value = {"success": True, "result": "ok"}
            results = queue.drain()

        assert len(results) == 1
        assert results[0]["success"] is True
        # After draining, actions are moved to replayed list
        assert queue.queue["replayed"][0]["status"] == "completed"

    def test_drain_handles_failure(self, tmp_offline_dirs):
        """Drain marks failed actions as failed."""
        queue = mod.ActionQueue()
        queue.add("test_action", {})

        with patch.object(queue, "_execute") as mock_execute:
            mock_execute.return_value = {"success": False, "error": "Test error"}
            results = queue.drain()

        assert results[0]["success"] is False
        # Failed actions remain in actions list but status updated
        assert any(a["status"] == "failed" for a in queue.queue["replayed"])

    def test_drain_only_pending_actions(self, tmp_offline_dirs):
        """Drain only processes pending actions."""
        queue = mod.ActionQueue()
        queue.add("action_1", {})
        queue.add("action_2", {})
        queue.queue["actions"][0]["status"] = "completed"

        with patch.object(queue, "_execute") as mock_execute:
            mock_execute.return_value = {"success": True}
            queue.drain()

        assert mock_execute.call_count == 1  # Only pending action

    def test_drain_trims_replayed_history(self, tmp_offline_dirs):
        """Drain trims replayed history to 100 when exceeds 200."""
        queue = mod.ActionQueue()
        queue.queue["replayed"] = [{"id": str(i)} for i in range(150)]

        for _ in range(100):
            queue.add("test", {})

        with patch.object(queue, "_execute") as mock_execute:
            mock_execute.return_value = {"success": True}
            queue.drain()

        assert len(queue.queue["replayed"]) <= 100

    def test_execute_send_email(self, tmp_offline_dirs):
        """Execute send_email action."""
        queue = mod.ActionQueue()
        action = {
            "type": "send_email",
            "payload": {"to": "test@example.com", "subject": "Test"}
        }

        with patch("rudy.email_multi.quick_send") as mock_send:
            mock_send.return_value = {"success": True}
            result = queue._execute(action)

        assert result["success"] is True
        mock_send.assert_called_once_with(to="test@example.com", subject="Test")

    def test_execute_webhook(self, tmp_offline_dirs):
        """Execute webhook action."""
        queue = mod.ActionQueue()
        action = {
            "type": "webhook",
            "payload": {
                "url": "http://example.com/webhook",
                "data": {"key": "value"},
                "headers": {"Authorization": "Bearer token"}
            }
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp

            result = queue._execute(action)

        assert result["success"] is True
        assert result["status_code"] == 200
        mock_post.assert_called_once_with(
            "http://example.com/webhook",
            json={"key": "value"},
            headers={"Authorization": "Bearer token"},
            timeout=15
        )

    def test_execute_webhook_failure(self, tmp_offline_dirs):
        """Execute webhook marks failure on non-2xx status."""
        queue = mod.ActionQueue()
        action = {
            "type": "webhook",
            "payload": {"url": "http://example.com", "data": {}, "headers": {}}
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_post.return_value = mock_resp

            result = queue._execute(action)

        assert result["success"] is False

    def test_execute_sync_knowledge(self, tmp_offline_dirs):
        """Execute sync_knowledge action."""
        queue = mod.ActionQueue()
        action = {"type": "sync_knowledge", "payload": {}}

        with patch("rudy.knowledge_base.KnowledgeBase") as mock_kb_class:
            mock_kb = MagicMock()
            mock_kb.index_all.return_value = {"indexed": 10}
            mock_kb_class.return_value = mock_kb

            result = queue._execute(action)

        assert result["success"] is True
        mock_kb.index_all.assert_called_once()

    def test_execute_check_jobs(self, tmp_offline_dirs):
        """Execute check_jobs action."""
        queue = mod.ActionQueue()
        action = {"type": "check_jobs", "payload": {}}

        with patch("rudy.web_intelligence.WebIntelligence") as mock_wi_class:
            mock_wi = MagicMock()
            mock_wi.search_jobs.return_value = [{"id": "1"}, {"id": "2"}]
            mock_wi_class.return_value = mock_wi

            result = queue._execute(action)

        assert result["success"] is True
        assert result["new_jobs"] == 2

    def test_execute_unknown_action(self, tmp_offline_dirs):
        """Execute unknown action type returns error."""
        queue = mod.ActionQueue()
        action = {"type": "unknown_type", "payload": {}}

        result = queue._execute(action)

        assert result["success"] is False
        assert "Unknown action type" in result["error"]

    def test_execute_exception_handling(self, tmp_offline_dirs):
        """Execute catches exceptions and truncates error."""
        queue = mod.ActionQueue()
        action = {
            "type": "send_email",
            "payload": {"to": "test@example.com"}
        }

        with patch("rudy.email_multi.quick_send") as mock_send:
            mock_send.side_effect = Exception("X" * 500)
            result = queue._execute(action)

        assert result["success"] is False
        assert len(result["error"]) <= 200


class TestDecisionLogger:
    """Test DecisionLogger class."""

    def test_init_loads_existing_log(self, tmp_offline_dirs):
        """Init loads existing decision log."""
        existing = {
            "log": [{"time": "2024-01-01", "context": "test"}]
        }
        tmp_offline_dirs["decision_log"].write_text(json.dumps(existing))

        logger = mod.DecisionLogger()

        assert logger.decisions == existing

    def test_init_creates_default_log(self, tmp_offline_dirs):
        """Init creates default log if file doesn't exist."""
        logger = mod.DecisionLogger()

        assert "log" in logger.decisions
        assert logger.decisions["log"] == []

    def test_log_decision(self, tmp_offline_dirs):
        """Log decision appends to log."""
        logger = mod.DecisionLogger()

        logger.log(
            context="Service failure",
            decision="Restart service",
            ai_reasoning="Service unresponsive for 5 minutes",
            action_taken="Sent restart command"
        )

        assert len(logger.decisions["log"]) == 1
        entry = logger.decisions["log"][0]
        assert entry["context"] == "Service failure"
        assert entry["decision"] == "Restart service"
        assert "time" in entry

    def test_log_truncates_reasoning(self, tmp_offline_dirs):
        """Log truncates ai_reasoning to 500 chars."""
        logger = mod.DecisionLogger()
        long_reasoning = "X" * 1000

        logger.log(context="test", decision="test", ai_reasoning=long_reasoning)

        entry = logger.decisions["log"][0]
        assert len(entry["ai_reasoning"]) == 500

    def test_log_trims_history(self, tmp_offline_dirs):
        """Log trims to 300 most recent when exceeds 500."""
        logger = mod.DecisionLogger()
        # Directly add entries to exceed 500
        logger.decisions["log"] = [{"id": i} for i in range(550)]

        # This log call will trigger trim since 550 > 500
        logger.log(context="Entry", decision="Decision")

        # Should be trimmed to 300 (the last 300 of previous 550 + new entry = 301 but trimmed down)
        # The trim happens AFTER append, so: 550 -> trim to 300 + 1 new = 301
        # But actually checking: it appends first (551), then checks if > 500, trims to last 300
        assert len(logger.decisions["log"]) == 300

    def test_get_recent(self, tmp_offline_dirs):
        """Get recent returns n most recent entries."""
        logger = mod.DecisionLogger()
        for i in range(30):
            logger.log(context=f"Entry {i}", decision=f"Decision {i}")

        recent = logger.get_recent(5)

        assert len(recent) == 5
        assert recent[-1]["context"] == "Entry 29"  # Most recent

    def test_get_recent_fewer_than_requested(self, tmp_offline_dirs):
        """Get recent returns all if fewer than requested."""
        logger = mod.DecisionLogger()
        logger.log(context="Entry 1", decision="Decision 1")
        logger.log(context="Entry 2", decision="Decision 2")

        recent = logger.get_recent(10)

        assert len(recent) == 2


class TestOfflineController:
    """Test OfflineController class."""

    def test_init(self, tmp_offline_dirs):
        """Init initializes components."""
        controller = mod.OfflineController()

        assert controller.checker is not None
        assert controller.queue is not None
        assert controller.logger is not None
        assert controller.state["mode"] == "online"

    def test_init_loads_existing_state(self, tmp_offline_dirs):
        """Init loads existing state file."""
        existing_state = {
            "mode": "offline",
            "offline_since": "2024-01-01T00:00:00",
            "outage_count": 5
        }
        tmp_offline_dirs["state_file"].write_text(json.dumps(existing_state))

        controller = mod.OfflineController()

        assert controller.state["mode"] == "offline"
        assert controller.state["offline_since"] == "2024-01-01T00:00:00"
        assert controller.state["outage_count"] == 5

    def test_heartbeat_online_no_change(self, tmp_offline_dirs):
        """Heartbeat when already online stays online."""
        controller = mod.OfflineController()

        with patch.object(controller.checker, "full_check") as mock_check:
            mock_check.return_value = {
                "online": True,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": True,
                "http": True,
                "dns_resolution": True,
            }

            status = controller.heartbeat()

        assert status["online"] is True
        assert status["mode"] == "online"
        assert controller.state["mode"] == "online"

    def test_heartbeat_offline_no_change(self, tmp_offline_dirs):
        """Heartbeat when already offline stays offline."""
        controller = mod.OfflineController()
        controller.state["mode"] = "offline"
        controller.state["offline_since"] = (
            datetime.now() - timedelta(minutes=10)
        ).isoformat()

        with patch.object(controller.checker, "full_check") as mock_check:
            mock_check.return_value = {
                "online": False,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": False,
                "http": False,
                "dns_resolution": False,
            }

            status = controller.heartbeat()

        assert status["online"] is False
        assert status["mode"] == "offline"
        assert status["current_outage_minutes"] > 0

    def test_heartbeat_transition_to_offline(self, tmp_offline_dirs):
        """Heartbeat transitions from online to offline."""
        controller = mod.OfflineController()
        assert controller.state["mode"] == "online"

        with patch.object(controller.checker, "full_check") as mock_check, \
             patch.object(controller.logger, "log") as mock_log:
            mock_check.return_value = {
                "online": False,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": False,
                "http": False,
                "dns_resolution": False,
            }

            status = controller.heartbeat()

        assert status["mode"] == "offline"
        assert controller.state["mode"] == "offline"
        assert controller.state["offline_since"] is not None
        assert controller.state["outage_count"] == 1
        mock_log.assert_called_once()
        # Check that email was queued
        assert controller.queue.pending_count == 1

    def test_heartbeat_transition_to_online(self, tmp_offline_dirs):
        """Heartbeat transitions from offline to online."""
        controller = mod.OfflineController()
        controller.state["mode"] = "offline"
        controller.state["offline_since"] = (
            datetime.now() - timedelta(minutes=5)
        ).isoformat()

        with patch.object(controller.checker, "full_check") as mock_check, \
             patch.object(controller.queue, "drain") as mock_drain, \
             patch.object(controller.logger, "log") as mock_log:
            mock_check.return_value = {
                "online": True,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": True,
                "http": True,
                "dns_resolution": True,
            }

            status = controller.heartbeat()

        assert status["mode"] == "online"
        assert controller.state["mode"] == "online"
        assert controller.state["offline_since"] is None
        mock_drain.assert_called_once()
        mock_log.assert_called_once()

    def test_heartbeat_updates_outage_duration(self, tmp_offline_dirs):
        """Heartbeat updates current outage duration when offline."""
        controller = mod.OfflineController()
        controller.state["mode"] = "offline"
        controller.state["offline_since"] = (
            datetime.now() - timedelta(minutes=15.5)
        ).isoformat()

        with patch.object(controller.checker, "full_check") as mock_check:
            mock_check.return_value = {
                "online": False,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": False,
                "http": False,
                "dns_resolution": False,
            }

            status = controller.heartbeat()

        assert status["current_outage_minutes"] >= 15.0

    def test_ai_decide_with_available_ai(self, tmp_offline_dirs):
        """AI decide uses local AI when available."""
        controller = mod.OfflineController()

        mock_ai_obj = MagicMock()
        mock_ai_obj.ensure_ready.return_value = True
        mock_ai_obj.ask.return_value = "Restart the service"

        with patch.object(controller, "_get_ai") as mock_get_ai:
            mock_get_ai.return_value = mock_ai_obj

            decision = controller.ai_decide("Service is down")

        assert decision["ai_available"] is True
        assert decision["response"] == "Restart the service"
        assert decision["situation"] == "Service is down"
        mock_ai_obj.ask.assert_called_once_with("Service is down", role="ops")

    def test_ai_decide_ai_not_available(self, tmp_offline_dirs):
        """AI decide uses fallback when AI unavailable."""
        controller = mod.OfflineController()

        with patch.object(controller, "_get_ai") as mock_get_ai:
            mock_get_ai.return_value = None

            decision = controller.ai_decide("Service is down")

        assert decision["ai_available"] is False
        assert "default heuristics" in decision["response"]

    def test_ai_decide_logs_decision(self, tmp_offline_dirs):
        """AI decide logs the decision."""
        controller = mod.OfflineController()

        with patch.object(controller, "_get_ai") as mock_get_ai, \
             patch.object(controller.logger, "log") as mock_log:
            mock_get_ai.return_value = None

            controller.ai_decide("Test situation")

        mock_log.assert_called_once()

    def test_queue_action(self, tmp_offline_dirs):
        """Queue action adds to action queue."""
        controller = mod.OfflineController()

        controller.queue_action("send_email", {"to": "test@example.com"}, priority=2)

        assert controller.queue.pending_count == 1
        action = controller.queue.queue["actions"][0]
        assert action["type"] == "send_email"
        assert action["priority"] == 2

    def test_get_status(self, tmp_offline_dirs):
        """Get status returns full status dict."""
        controller = mod.OfflineController()
        controller.state["outage_count"] = 3
        controller.state["total_offline_minutes"] = 120

        status = controller.get_status()

        assert status["mode"] == "online"
        assert status["online"] is True
        assert status["outage_count"] == 3
        assert status["total_offline_minutes"] == 120
        assert "queue" in status
        assert "recent_decisions" in status

    def test_get_status_when_offline(self, tmp_offline_dirs):
        """Get status reflects offline state."""
        controller = mod.OfflineController()
        controller.state["mode"] = "offline"
        controller.state["offline_since"] = datetime.now().isoformat()

        status = controller.get_status()

        assert status["online"] is False
        assert status["mode"] == "offline"
        assert status["offline_since"] is not None

    def test_get_ai_lazy_loads(self, tmp_offline_dirs):
        """Get AI lazy loads on first access."""
        controller = mod.OfflineController()
        assert controller._ai is None

        with patch("rudy.local_ai.OfflineAI") as mock_ai_class:
            mock_ai_instance = MagicMock()
            mock_ai_class.get.return_value = mock_ai_instance

            controller._get_ai()

        assert controller._ai is not None

    def test_get_ai_handles_import_error(self, tmp_offline_dirs):
        """Get AI returns None on import error."""
        controller = mod.OfflineController()

        with patch("rudy.local_ai.OfflineAI") as mock_ai_class:
            mock_ai_class.get.side_effect = ImportError("Module not found")

            ai = controller._get_ai()

        assert ai is None


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_is_online_true(self):
        """is_online returns True when DNS check succeeds."""
        with patch("socket.create_connection") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value = mock_sock

            result = mod.is_online()

        assert result is True

    def test_is_online_false(self):
        """is_online returns False when DNS check fails."""
        with patch("socket.create_connection") as mock_socket:
            mock_socket.side_effect = socket.error("Connection refused")

            result = mod.is_online()

        assert result is False

    def test_get_controller(self, tmp_offline_dirs):
        """get_controller returns OfflineController instance."""
        controller = mod.get_controller()

        assert isinstance(controller, mod.OfflineController)


class TestIntegration:
    """Integration tests for complete workflows."""

    def test_complete_outage_and_recovery_flow(self, tmp_offline_dirs):
        """Test complete flow: online -> offline -> recovery."""
        controller = mod.OfflineController()

        # Initially online
        assert controller.state["mode"] == "online"

        # Simulate outage
        with patch.object(controller.checker, "full_check") as mock_check:
            mock_check.return_value = {
                "online": False,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": False,
                "http": False,
                "dns_resolution": False,
            }
            controller.heartbeat()

        assert controller.state["mode"] == "offline"
        assert controller.queue.pending_count == 1  # Outage notification queued

        # Queue some actions while offline
        controller.queue_action("send_email", {"to": "test@example.com"})
        assert controller.queue.pending_count == 2

        # Recovery
        with patch.object(controller.checker, "full_check") as mock_check, \
             patch.object(controller.queue, "drain") as mock_drain:
            mock_check.return_value = {
                "online": True,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": True,
                "http": True,
                "dns_resolution": True,
            }
            mock_drain.return_value = [{"success": True}, {"success": True}]

            controller.heartbeat()

        assert controller.state["mode"] == "online"
        mock_drain.assert_called_once()

    def test_multiple_outages_counted(self, tmp_offline_dirs):
        """Test multiple outages increment counter."""
        controller = mod.OfflineController()

        for outage_num in range(3):
            # Go offline
            with patch.object(controller.checker, "full_check") as mock_check:
                mock_check.return_value = {
                    "online": False,
                    "timestamp": datetime.now().isoformat(),
                    "dns_socket": False,
                    "http": False,
                    "dns_resolution": False,
                }
                controller.heartbeat()

            assert controller.state["outage_count"] == outage_num + 1

            # Go back online
            with patch.object(controller.checker, "full_check") as mock_check, \
                 patch.object(controller.queue, "drain"):
                mock_check.return_value = {
                    "online": True,
                    "timestamp": datetime.now().isoformat(),
                    "dns_socket": True,
                    "http": True,
                    "dns_resolution": True,
                }
                controller.heartbeat()

    def test_action_queue_priority_execution(self, tmp_offline_dirs):
        """Test actions execute in priority order."""
        queue = mod.ActionQueue()

        queue.add("low_priority", {}, priority=10)
        queue.add("high_priority", {}, priority=1)
        queue.add("medium_priority", {}, priority=5)

        executed_order = []

        def track_execute(action):
            executed_order.append(action["priority"])
            return {"success": True}

        with patch.object(queue, "_execute") as mock_execute:
            mock_execute.side_effect = track_execute
            queue.drain()

        assert executed_order == [1, 5, 10]

    def test_decision_logging_throughout_outage(self, tmp_offline_dirs):
        """Test decisions logged throughout outage."""
        controller = mod.OfflineController()

        # Outage transition
        with patch.object(controller.checker, "full_check") as mock_check:
            mock_check.return_value = {
                "online": False,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": False,
                "http": False,
                "dns_resolution": False,
            }
            controller.heartbeat()

        # AI decision during outage
        with patch.object(controller, "_get_ai") as mock_get_ai:
            mock_get_ai.return_value = None
            controller.ai_decide("Service down")

        # Recovery
        with patch.object(controller.checker, "full_check") as mock_check, \
             patch.object(controller.queue, "drain"):
            mock_check.return_value = {
                "online": True,
                "timestamp": datetime.now().isoformat(),
                "dns_socket": True,
                "http": True,
                "dns_resolution": True,
            }
            controller.heartbeat()

        # Check decision log
        recent = controller.logger.get_recent(10)
        assert len(recent) >= 3  # Outage, decision, recovery

    def test_state_persistence_across_instances(self, tmp_offline_dirs):
        """Test state persists across controller instances."""
        # First instance
        controller1 = mod.OfflineController()
        controller1.queue_action("test_action", {"data": "value"})
        original_queue_count = controller1.queue.pending_count

        # Second instance - should load same state
        controller2 = mod.OfflineController()
        assert controller2.queue.pending_count == original_queue_count
