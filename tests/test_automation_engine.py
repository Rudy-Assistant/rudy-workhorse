"""Tests for rudy.automation.engine — AutomationEngine central coordinator."""

import json
import sqlite3
from pathlib import Path

import pytest

from rudy.automation.engine import AutomationEngine, WorkflowTrigger


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_engine.sqlite"


@pytest.fixture
def engine(db_path):
    """Create an AutomationEngine instance with temp database."""
    return AutomationEngine(db_path=db_path)


class TestWorkflowTrigger:
    """Test WorkflowTrigger dataclass."""

    def test_basic_creation(self):
        """Test creating a basic WorkflowTrigger."""
        trigger = WorkflowTrigger(
            id="test-id",
            name="test trigger",
            trigger_type="webhook",
            config={"url": "http://example.com"},
            enabled=True,
            created_at="2026-03-28T10:00:00",
        )
        assert trigger.id == "test-id"
        assert trigger.name == "test trigger"
        assert trigger.trigger_type == "webhook"
        assert trigger.enabled is True

    def test_with_fire_tracking(self):
        """Test trigger with fire tracking."""
        trigger = WorkflowTrigger(
            id="test-id",
            name="test trigger",
            trigger_type="cron",
            config={},
            enabled=True,
            created_at="2026-03-28T10:00:00",
            last_fired="2026-03-28T10:05:00",
            fire_count=5,
        )
        assert trigger.fire_count == 5
        assert trigger.last_fired == "2026-03-28T10:05:00"


class TestAutomationEngineInit:
    """Test AutomationEngine initialization."""

    def test_creates_database(self, db_path):
        """Test that AutomationEngine creates the database."""
        AutomationEngine(db_path=db_path)
        assert db_path.exists()

    def test_creates_parent_directories(self, tmp_path):
        """Test that parent directories are created."""
        deep_path = tmp_path / "a" / "b" / "c" / "engine.sqlite"
        AutomationEngine(db_path=deep_path)
        assert deep_path.exists()

    def test_creates_schema(self, db_path):
        """Test that automation_triggers table is created."""
        AutomationEngine(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "automation_triggers" in table_names
        conn.close()

    def test_initializes_cache(self, engine):
        """Test that triggers cache is initialized."""
        assert isinstance(engine._triggers_cache, dict)
        assert len(engine._triggers_cache) == 0


class TestRegisterTrigger:
    """Test register_trigger method."""

    def test_register_webhook_trigger(self, engine):
        """Test registering a webhook trigger."""
        trigger_id = engine.register_trigger(
            name="webhook trigger",
            trigger_type="webhook",
            config={"url": "http://example.com", "secret": "abc123"},
        )
        assert trigger_id != ""
        assert trigger_id in engine._triggers_cache

    def test_register_cron_trigger(self, engine):
        """Test registering a cron trigger."""
        trigger_id = engine.register_trigger(
            name="daily report",
            trigger_type="cron",
            config={"schedule": "0 9 * * *", "task_type": "report"},
        )
        assert trigger_id != ""
        trigger = engine._triggers_cache[trigger_id]
        assert trigger.trigger_type == "cron"

    def test_register_email_trigger(self, engine):
        """Test registering an email trigger."""
        trigger_id = engine.register_trigger(
            name="email processor",
            trigger_type="email",
            config={"classify": True, "auto_respond": False},
        )
        assert trigger_id != ""
        assert engine._triggers_cache[trigger_id].trigger_type == "email"

    def test_register_manual_trigger(self, engine):
        """Test registering a manual trigger."""
        trigger_id = engine.register_trigger(
            name="manual workflow",
            trigger_type="manual",
            config={"description": "Manually invoked workflow"},
        )
        assert trigger_id != ""

    def test_register_persists_to_database(self, engine, db_path):
        """Test that registered trigger is persisted."""
        trigger_id = engine.register_trigger(
            name="test trigger",
            trigger_type="webhook",
            config={"test": "config"},
        )
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id, name, trigger_type FROM automation_triggers WHERE id = ?",
            (trigger_id,),
        ).fetchone()
        assert row is not None
        assert row[1] == "test trigger"
        assert row[2] == "webhook"
        conn.close()

    def test_register_sets_enabled_true(self, engine):
        """Test that newly registered trigger is enabled."""
        trigger_id = engine.register_trigger(
            name="test",
            trigger_type="webhook",
            config={},
        )
        trigger = engine._triggers_cache[trigger_id]
        assert trigger.enabled is True


class TestListTriggers:
    """Test list_triggers method."""

    def test_list_all_triggers(self, engine):
        """Test listing all triggers."""
        engine.register_trigger("trigger1", "webhook", {})
        engine.register_trigger("trigger2", "cron", {})
        triggers = engine.list_triggers()
        assert len(triggers) == 2

    def test_list_by_type(self, engine):
        """Test filtering by trigger type."""
        engine.register_trigger("webhook1", "webhook", {})
        engine.register_trigger("webhook2", "webhook", {})
        engine.register_trigger("cron1", "cron", {})

        webhooks = engine.list_triggers(trigger_type="webhook")
        assert len(webhooks) == 2
        assert all(t["trigger_type"] == "webhook" for t in webhooks)

    def test_list_enabled_only(self, engine):
        """Test filtering to enabled triggers only."""
        id1 = engine.register_trigger("enabled", "webhook", {})
        id2 = engine.register_trigger("disabled", "cron", {})
        engine.disable_trigger(id2)

        enabled = engine.list_triggers(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["name"] == "enabled"

    def test_list_empty(self, engine):
        """Test listing when no triggers exist."""
        triggers = engine.list_triggers()
        assert triggers == []


class TestUnregisterTrigger:
    """Test unregister_trigger method."""

    def test_unregister_existing_trigger(self, engine):
        """Test unregistering an existing trigger."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})
        success = engine.unregister_trigger(trigger_id)
        assert success is True
        assert trigger_id not in engine._triggers_cache

    def test_unregister_nonexistent_trigger(self, engine):
        """Test unregistering a nonexistent trigger."""
        success = engine.unregister_trigger("unknown-id")
        assert success is False

    def test_unregister_removes_from_database(self, engine, db_path):
        """Test that unregister removes from database."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})
        engine.unregister_trigger(trigger_id)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id FROM automation_triggers WHERE id = ?",
            (trigger_id,),
        ).fetchone()
        assert row is None
        conn.close()


class TestEnableDisableTrigger:
    """Test enable_trigger and disable_trigger methods."""

    def test_enable_trigger(self, engine):
        """Test enabling a trigger."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})
        engine.disable_trigger(trigger_id)

        success = engine.enable_trigger(trigger_id)
        assert success is True
        assert engine._triggers_cache[trigger_id].enabled is True

    def test_disable_trigger(self, engine):
        """Test disabling a trigger."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})
        success = engine.disable_trigger(trigger_id)
        assert success is True
        assert engine._triggers_cache[trigger_id].enabled is False

    def test_disable_and_enable_persistence(self, engine, db_path):
        """Test that enabled/disabled state persists."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})
        engine.disable_trigger(trigger_id)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT enabled FROM automation_triggers WHERE id = ?",
            (trigger_id,),
        ).fetchone()
        assert row[0] == 0
        conn.close()

    def test_enable_nonexistent_trigger(self, engine):
        """Test enabling a nonexistent trigger."""
        success = engine.enable_trigger("unknown-id")
        assert success is False

    def test_disable_nonexistent_trigger(self, engine):
        """Test disabling a nonexistent trigger."""
        success = engine.disable_trigger("unknown-id")
        assert success is False


class TestProcessEvent:
    """Test process_event method."""

    def test_process_event_matches_triggers(self, engine):
        """Test that process_event matches triggers by type."""
        trigger_id = engine.register_trigger(
            "webhook trigger",
            "webhook",
            {},
        )
        results = engine.process_event("webhook", {"data": "test"})
        assert len(results) == 1
        assert results[0]["trigger_id"] == trigger_id

    def test_process_event_no_matching_triggers(self, engine):
        """Test processing event with no matching triggers."""
        engine.register_trigger("webhook trigger", "webhook", {})
        results = engine.process_event("cron", {"data": "test"})
        assert len(results) == 0

    def test_process_event_ignores_disabled_triggers(self, engine):
        """Test that disabled triggers are not fired."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})
        engine.disable_trigger(trigger_id)

        results = engine.process_event("webhook", {})
        assert len(results) == 0

    def test_process_event_multiple_matching_triggers(self, engine):
        """Test processing event with multiple matching triggers."""
        engine.register_trigger("trigger1", "webhook", {})
        engine.register_trigger("trigger2", "webhook", {})

        results = engine.process_event("webhook", {})
        assert len(results) == 2

    def test_process_event_passes_event_data(self, engine):
        """Test that event data is passed through."""
        engine.register_trigger("trigger", "webhook", {})
        results = engine.process_event("webhook", {"key": "value"})
        assert len(results) == 1
        assert results[0]["status"] in ["fired", "executed", "error"]


class TestFireTracking:
    """Test fire count and last_fired tracking."""

    def test_fire_count_increments(self, engine):
        """Test that fire_count increments when trigger fires."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})

        engine.process_event("webhook", {})
        assert engine._triggers_cache[trigger_id].fire_count == 1

        engine.process_event("webhook", {})
        assert engine._triggers_cache[trigger_id].fire_count == 2

    def test_last_fired_updates(self, engine, db_path):
        """Test that last_fired timestamp is updated in database."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})

        engine.process_event("webhook", {})

        # Verify last_fired is set in database
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT last_fired FROM automation_triggers WHERE id = ?",
            (trigger_id,),
        ).fetchone()
        assert row is not None
        assert row[0] is not None
        conn.close()

    def test_fire_tracking_persists_to_database(self, engine, db_path):
        """Test that fire tracking persists to database."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})
        engine.process_event("webhook", {})

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT fire_count, last_fired FROM automation_triggers WHERE id = ?",
            (trigger_id,),
        ).fetchone()
        assert row[0] == 1
        assert row[1] is not None
        conn.close()


class TestSetOracle:
    """Test Oracle integration."""

    def test_set_oracle(self, engine):
        """Test injecting Oracle reference."""
        class MockOracle:
            pass

        oracle = MockOracle()
        engine.set_oracle(oracle)
        assert engine._oracle is oracle

    def test_process_event_without_oracle(self, engine):
        """Test that process_event works without Oracle."""
        trigger_id = engine.register_trigger("trigger", "webhook", {})
        results = engine.process_event("webhook", {})
        assert len(results) == 1
        assert results[0]["status"] == "fired"


class TestPersistence:
    """Test database persistence."""

    def test_triggers_survive_restart(self, db_path):
        """Test that triggers survive engine restart."""
        engine1 = AutomationEngine(db_path=db_path)
        trigger_id = engine1.register_trigger("trigger", "webhook", {})

        engine2 = AutomationEngine(db_path=db_path)
        assert trigger_id in engine2._triggers_cache
        assert engine2._triggers_cache[trigger_id].name == "trigger"

    def test_fire_count_survives_restart(self, db_path):
        """Test that fire_count survives restart."""
        engine1 = AutomationEngine(db_path=db_path)
        trigger_id = engine1.register_trigger("trigger", "webhook", {})
        engine1.process_event("webhook", {})
        engine1.process_event("webhook", {})

        engine2 = AutomationEngine(db_path=db_path)
        assert engine2._triggers_cache[trigger_id].fire_count == 2
