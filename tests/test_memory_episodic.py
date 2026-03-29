"""Tests for rudy.memory.episodic — Episodic Memory (event timeline)."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rudy.memory.episodic import EpisodicMemory


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_memory.sqlite"


@pytest.fixture
def ep(db_path):
    return EpisodicMemory(db_path)


# ── Initialization ──────────────────────────────────────────────


class TestInit:
    def test_creates_db_file(self, db_path):
        EpisodicMemory(db_path)
        assert db_path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "c" / "memory.sqlite"
        EpisodicMemory(deep_path)
        assert deep_path.exists()

    def test_tables_created(self, db_path):
        EpisodicMemory(db_path)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "events" in table_names
        assert "daily_summaries" in table_names
        conn.close()

    def test_wal_mode_enabled(self, db_path):
        EpisodicMemory(db_path)
        conn = sqlite3.connect(str(db_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()


# ── log_event ───────────────────────────────────────────────────


class TestLogEvent:
    def test_basic_event(self, ep):
        row_id = ep.log_event("sentinel", "alert")
        assert row_id > 0

    def test_event_with_payload(self, ep):
        payload = {"threat": "unknown MAC", "mac": "AA:BB:CC:DD:EE:FF"}
        row_id = ep.log_event("sentinel", "alert", payload=payload)
        events = ep.query(agent="sentinel")
        assert len(events) == 1
        assert events[0]["payload"]["threat"] == "unknown MAC"

    def test_event_with_session_id(self, ep):
        ep.log_event("rudy", "action", session_id="session-123")
        events = ep.query(session_id="session-123")
        assert len(events) == 1

    def test_event_with_tags(self, ep):
        ep.log_event("sentinel", "alert", tags=["security", "network"])
        events = ep.query(tags=["security"])
        assert len(events) == 1
        assert "security" in events[0]["tags"]

    def test_event_with_custom_timestamp(self, ep):
        ts = "2026-03-01T12:00:00"
        ep.log_event("rudy", "action", timestamp=ts)
        events = ep.query(agent="rudy")
        assert events[0]["timestamp"] == ts

    def test_multiple_events(self, ep):
        for i in range(10):
            ep.log_event("test", f"type_{i}")
        assert ep.count() == 10

    def test_empty_payload_defaults_to_dict(self, ep):
        ep.log_event("test", "event")
        events = ep.query(agent="test")
        assert events[0]["payload"] == {}

    def test_complex_payload_serialization(self, ep):
        payload = {
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "number": 42.5,
        }
        ep.log_event("test", "complex", payload=payload)
        events = ep.query(agent="test")
        assert events[0]["payload"]["nested"]["key"] == "value"
        assert events[0]["payload"]["list"] == [1, 2, 3]


# ── query ───────────────────────────────────────────────────────


class TestQuery:
    def test_filter_by_agent(self, ep):
        ep.log_event("sentinel", "alert")
        ep.log_event("rudy", "action")
        ep.log_event("sentinel", "scan")
        results = ep.query(agent="sentinel")
        assert len(results) == 2
        assert all(r["agent"] == "sentinel" for r in results)

    def test_filter_by_event_type(self, ep):
        ep.log_event("sentinel", "alert")
        ep.log_event("sentinel", "scan")
        ep.log_event("rudy", "alert")
        results = ep.query(event_type="alert")
        assert len(results) == 2

    def test_filter_by_time_range(self, ep):
        old_ts = (datetime.now() - timedelta(hours=2)).isoformat()
        new_ts = datetime.now().isoformat()
        ep.log_event("test", "old", timestamp=old_ts)
        ep.log_event("test", "new", timestamp=new_ts)
        cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
        results = ep.query(since=cutoff)
        assert len(results) == 1
        assert results[0]["event_type"] == "new"

    def test_limit_and_offset(self, ep):
        for i in range(20):
            ep.log_event("test", f"event_{i}")
        page1 = ep.query(limit=5, offset=0)
        page2 = ep.query(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        assert page1[0]["id"] != page2[0]["id"]

    def test_newest_first_ordering(self, ep):
        ep.log_event("test", "first", timestamp="2026-01-01T00:00:00")
        ep.log_event("test", "second", timestamp="2026-01-02T00:00:00")
        results = ep.query()
        assert results[0]["event_type"] == "second"
        assert results[1]["event_type"] == "first"

    def test_combined_filters(self, ep):
        ep.log_event("sentinel", "alert", tags=["security"])
        ep.log_event("sentinel", "scan", tags=["routine"])
        ep.log_event("rudy", "alert", tags=["email"])
        results = ep.query(agent="sentinel", event_type="alert")
        assert len(results) == 1

    def test_empty_result(self, ep):
        results = ep.query(agent="nonexistent")
        assert results == []


# ── count ───────────────────────────────────────────────────────


class TestCount:
    def test_total_count(self, ep):
        ep.log_event("a", "x")
        ep.log_event("b", "y")
        assert ep.count() == 2

    def test_filtered_count(self, ep):
        ep.log_event("sentinel", "alert")
        ep.log_event("rudy", "action")
        assert ep.count(agent="sentinel") == 1

    def test_empty_count(self, ep):
        assert ep.count() == 0


# ── get_recent ──────────────────────────────────────────────────


class TestGetRecent:
    def test_returns_agent_events(self, ep):
        ep.log_event("sentinel", "alert")
        ep.log_event("rudy", "action")
        ep.log_event("sentinel", "scan")
        results = ep.get_recent("sentinel", limit=10)
        assert len(results) == 2
        assert all(r["agent"] == "sentinel" for r in results)

    def test_respects_limit(self, ep):
        for i in range(10):
            ep.log_event("test", f"event_{i}")
        results = ep.get_recent("test", limit=3)
        assert len(results) == 3


# ── get_timeline ────────────────────────────────────────────────


class TestGetTimeline:
    def test_chronological_order(self, ep):
        ep.log_event("test", "first", timestamp="2026-01-01T00:00:00")
        ep.log_event("test", "second", timestamp="2026-01-02T00:00:00")
        ep.log_event("test", "third", timestamp="2026-01-03T00:00:00")
        timeline = ep.get_timeline("2026-01-01T00:00:00", "2026-01-03T23:59:59")
        assert timeline[0]["event_type"] == "first"
        assert timeline[2]["event_type"] == "third"

    def test_filter_by_agents(self, ep):
        ep.log_event("sentinel", "alert", timestamp="2026-01-01T00:00:00")
        ep.log_event("rudy", "action", timestamp="2026-01-01T01:00:00")
        ep.log_event("system", "health", timestamp="2026-01-01T02:00:00")
        timeline = ep.get_timeline(
            "2026-01-01T00:00:00", agents=["sentinel", "rudy"]
        )
        assert len(timeline) == 2

    def test_empty_range(self, ep):
        ep.log_event("test", "event", timestamp="2026-01-01T00:00:00")
        timeline = ep.get_timeline("2026-06-01T00:00:00")
        assert timeline == []


# ── compress_old_events ─────────────────────────────────────────


class TestCompression:
    def test_compresses_old_events(self, ep):
        old_ts = (datetime.now() - timedelta(days=60)).isoformat()
        for i in range(5):
            ep.log_event("test", "old_event", timestamp=old_ts)
        ep.log_event("test", "recent_event")
        result = ep.compress_old_events(days_threshold=30)
        assert result["events_compressed"] == 5
        assert result["summaries_created"] >= 1
        assert ep.count() == 1  # Only the recent event remains

    def test_preserves_recent_events(self, ep):
        ep.log_event("test", "recent")
        result = ep.compress_old_events(days_threshold=30)
        assert result["events_compressed"] == 0
        assert ep.count() == 1

    def test_idempotent_compression(self, ep):
        old_ts = (datetime.now() - timedelta(days=60)).isoformat()
        ep.log_event("test", "old", timestamp=old_ts)
        ep.compress_old_events(days_threshold=30)
        result2 = ep.compress_old_events(days_threshold=30)
        assert result2["events_compressed"] == 0

    def test_summary_contains_key_events(self, ep):
        old_ts = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT12:00:00")
        ep.log_event("sentinel", "alert", payload={"threat": "test"}, timestamp=old_ts)
        ep.compress_old_events(days_threshold=30)
        conn = sqlite3.connect(str(ep._db_path))
        row = conn.execute("SELECT summary FROM daily_summaries LIMIT 1").fetchone()
        summary = json.loads(row[0])
        assert "sentinel" in summary["agents_active"]
        conn.close()


# ── get_stats ───────────────────────────────────────────────────


class TestStats:
    def test_empty_stats(self, ep):
        stats = ep.get_stats()
        assert stats["total_events"] == 0
        assert stats["active_agents"] == []

    def test_stats_after_events(self, ep):
        ep.log_event("sentinel", "alert")
        ep.log_event("rudy", "action")
        stats = ep.get_stats()
        assert stats["total_events"] == 2
        assert set(stats["active_agents"]) == {"sentinel", "rudy"}
        assert stats["oldest_event"] is not None
        assert stats["newest_event"] is not None
