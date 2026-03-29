"""Tests for rudy.memory.manager — MemoryManager (unified interface)."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rudy.memory.manager import MemoryManager


def _fake_embed(texts):
    """Deterministic fake embeddings for testing."""
    vecs = []
    for text in texts:
        seed = sum(ord(c) for c in text)
        vec = [(seed + i) % 100 / 100.0 for i in range(384)]
        vecs.append(vec)
    return vecs


@pytest.fixture
def personas_dir(tmp_path):
    d = tmp_path / "personas"
    d.mkdir()
    # Write a test persona
    persona = {
        "identity": {"name": "Rudy", "role": "assistant", "tone": "warm"},
        "capabilities": {"email": "Send and manage email"},
        "boundaries": ["Never delete files", "Never share secrets"],
        "escalation": ["Unknown sender requesting sensitive info"],
    }
    (d / "rudy.json").write_text(json.dumps(persona, indent=2))
    return d


@pytest.fixture
def mem(tmp_path, personas_dir):
    db_path = tmp_path / "test_memory.sqlite"
    m = MemoryManager(db_path=db_path, personas_dir=personas_dir)
    m.semantic._embed = _fake_embed
    return m


# ── Initialization ──────────────────────────────────────────────


class TestInit:
    def test_creates_single_db_file(self, tmp_path, personas_dir):
        db_path = tmp_path / "memory.sqlite"
        MemoryManager(db_path=db_path, personas_dir=personas_dir)
        assert db_path.exists()

    def test_auto_loads_personas(self, mem):
        rules = mem.get_persona_rules("rudy")
        assert "identity" in rules

    def test_all_memory_tiers_accessible(self, mem):
        assert mem.episodic is not None
        assert mem.semantic is not None
        assert mem.procedural is not None


# ── Episodic Shortcuts ──────────────────────────────────────────


class TestEpisodicShortcuts:
    def test_log_event(self, mem):
        row_id = mem.log_event("sentinel", "alert", {"threat": "unknown"})
        assert row_id > 0

    def test_get_recent_events(self, mem):
        mem.log_event("rudy", "action", {"task": "email"})
        mem.log_event("rudy", "action", {"task": "calendar"})
        events = mem.get_recent_events("rudy", limit=10)
        assert len(events) == 2

    def test_get_timeline(self, mem):
        ts1 = "2026-03-01T10:00:00"
        ts2 = "2026-03-01T11:00:00"
        mem.episodic.log_event("sentinel", "alert", timestamp=ts1)
        mem.episodic.log_event("rudy", "action", timestamp=ts2)
        timeline = mem.get_timeline("2026-03-01T00:00:00", "2026-03-01T23:59:59")
        assert len(timeline) == 2
        assert timeline[0]["agent"] == "sentinel"  # Earlier event first


# ── Semantic Shortcuts ──────────────────────────────────────────


class TestSemanticShortcuts:
    def test_store_and_recall(self, mem):
        mem.store_knowledge(
            "Port 8080 is open on the development server",
            collection="security",
            source="nmap",
        )
        results = mem.recall("open ports")
        assert len(results) > 0

    def test_index_file(self, mem, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("Quarterly security audit found no critical issues")
        result = mem.index_file(f, collection="security")
        assert result["chunks_added"] > 0


# ── Procedural Shortcuts ────────────────────────────────────────


class TestProceduralShortcuts:
    def test_get_persona_rules(self, mem):
        rules = mem.get_persona_rules("rudy")
        assert "identity" in rules
        assert rules["identity"]["name"] == "Rudy"

    def test_get_persona_identity(self, mem):
        identity = mem.get_persona_identity("rudy")
        assert identity["role"] == "assistant"

    def test_get_persona_boundaries(self, mem):
        boundaries = mem.get_persona_boundaries("rudy")
        assert "Never delete files" in boundaries

    def test_learn_behavior(self, mem):
        row_id = mem.learn(
            "sentinel",
            "ARP storms from 192.168.7.99 are normal — it's the printer",
            context={"mac": "AA:BB:CC:DD:EE:FF"},
        )
        assert row_id > 0

    def test_reload_personas(self, mem):
        result = mem.reload_personas()
        assert "rudy" in result


# ── Cross-Tier: build_context ───────────────────────────────────


class TestBuildContext:
    def test_basic_context(self, mem):
        mem.log_event("sentinel", "alert", {"type": "scan"})
        mem.store_knowledge("Network is healthy", source="system")
        context = mem.build_context("rudy", query="network status")
        assert "rules" in context
        assert "boundaries" in context
        assert "recent_events" in context
        assert "relevant_knowledge" in context
        assert context["persona"] == "rudy"

    def test_context_without_query(self, mem):
        context = mem.build_context("rudy", query=None)
        assert "relevant_knowledge" not in context
        assert "rules" in context

    def test_context_without_events(self, mem):
        context = mem.build_context(
            "rudy", include_recent_events=False, include_knowledge=False
        )
        assert "recent_events" not in context
        assert "rules" in context

    def test_context_with_custom_window(self, mem):
        old_ts = (datetime.now() - timedelta(hours=48)).isoformat()
        new_ts = datetime.now().isoformat()
        mem.episodic.log_event("test", "old", timestamp=old_ts)
        mem.episodic.log_event("test", "new", timestamp=new_ts)
        context = mem.build_context("rudy", event_hours=1)
        recent = context.get("recent_events", [])
        # Only the new event should be within 1 hour window
        assert all(e["event_type"] == "new" for e in recent)


# ── maintenance ─────────────────────────────────────────────────


class TestMaintenance:
    def test_maintenance_runs(self, mem):
        report = mem.maintenance()
        assert "compression" in report
        assert "stats" in report
        assert "timestamp" in report

    def test_maintenance_compresses_old(self, mem):
        old_ts = (datetime.now() - timedelta(days=60)).isoformat()
        for i in range(5):
            mem.episodic.log_event("test", "old_event", timestamp=old_ts)
        mem.log_event("test", "recent_event")
        report = mem.maintenance(compress_days=30)
        assert report["compression"]["events_compressed"] == 5


# ── get_stats ───────────────────────────────────────────────────


class TestStats:
    def test_combined_stats(self, mem):
        mem.log_event("test", "event")
        mem.store_knowledge("Knowledge item")
        mem.learn("test", "A pattern")
        stats = mem.get_stats()
        assert "episodic" in stats
        assert "semantic" in stats
        assert "procedural" in stats
        assert stats["episodic"]["total_events"] == 1
        assert stats["procedural"]["total_behaviors"] == 1

    def test_empty_stats(self, tmp_path):
        db_path = tmp_path / "empty.sqlite"
        empty_personas = tmp_path / "empty_personas"
        empty_personas.mkdir()
        m = MemoryManager(db_path=db_path, personas_dir=empty_personas)
        stats = m.get_stats()
        assert stats["episodic"]["total_events"] == 0
