"""Tests for rudy.memory.procedural — Procedural Memory (persona rules)."""

import json
import sqlite3
from pathlib import Path

import pytest

from rudy.memory.procedural import ProceduralMemory, _file_hash


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_memory.sqlite"


@pytest.fixture
def personas_dir(tmp_path):
    d = tmp_path / "personas"
    d.mkdir()
    return d


@pytest.fixture
def proc(db_path, personas_dir):
    return ProceduralMemory(db_path, personas_dir)


def _write_persona_json(personas_dir, name, data):
    """Helper to write a JSON persona file."""
    filepath = personas_dir / f"{name}.json"
    filepath.write_text(json.dumps(data, indent=2))
    return filepath


# ── Initialization ──────────────────────────────────────────────


class TestInit:
    def test_creates_db(self, db_path, personas_dir):
        ProceduralMemory(db_path, personas_dir)
        assert db_path.exists()

    def test_creates_tables(self, db_path, personas_dir):
        ProceduralMemory(db_path, personas_dir)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = [t[0] for t in tables]
        assert "persona_rules" in names
        assert "learned_behaviors" in names
        conn.close()

    def test_no_personas_dir(self, db_path):
        proc = ProceduralMemory(db_path, None)
        assert proc.load_personas() == {}


# ── load_personas ───────────────────────────────────────────────


class TestLoadPersonas:
    def test_load_json_persona(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {
            "identity": {"name": "Rudy", "role": "assistant"},
            "capabilities": {"email": "Send and receive email"},
            "boundaries": ["Never delete files", "Never share secrets"],
        })
        result = proc.load_personas()
        assert "rudy" in result
        assert result["rudy"] > 0

    def test_load_multiple_personas(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {
            "identity": {"name": "Rudy"},
        })
        _write_persona_json(personas_dir, "batman", {
            "identity": {"name": "Batman"},
        })
        result = proc.load_personas()
        assert "rudy" in result
        assert "batman" in result

    def test_skip_non_persona_files(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {"identity": {"name": "Rudy"}})
        (personas_dir / "README.md").write_text("Not a persona")
        (personas_dir / "notes.txt").write_text("Not a persona")
        result = proc.load_personas()
        assert len(result) == 1

    def test_reload_unchanged_file(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {"identity": {"name": "Rudy"}})
        proc.load_personas()
        # Load again — should skip
        result = proc.load_personas()
        assert "rudy" in result

    def test_reload_changed_file(self, proc, personas_dir):
        filepath = _write_persona_json(
            personas_dir, "rudy", {"identity": {"name": "Rudy v1"}}
        )
        proc.load_personas()
        # Change the file
        _write_persona_json(
            personas_dir, "rudy", {"identity": {"name": "Rudy v2"}}
        )
        proc.load_personas()
        rules = proc.get_rules("rudy")
        assert rules["identity"]["name"] == "Rudy v2"

    def test_empty_personas_dir(self, proc, personas_dir):
        result = proc.load_personas()
        assert result == {}

    def test_malformed_json(self, proc, personas_dir):
        (personas_dir / "bad.json").write_text("{invalid json")
        result = proc.load_personas()
        assert result.get("bad", 0) == 0


# ── get_rules ───────────────────────────────────────────────────


class TestGetRules:
    def test_get_all_rules(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {
            "identity": {"name": "Rudy", "role": "assistant"},
            "capabilities": {"email": "Send email"},
        })
        proc.load_personas()
        rules = proc.get_rules("rudy")
        assert "identity" in rules
        assert "capabilities" in rules

    def test_get_rules_by_type(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {
            "identity": {"name": "Rudy"},
            "boundaries": ["Never delete"],
        })
        proc.load_personas()
        rules = proc.get_rules("rudy", rule_type="identity")
        assert "identity" in rules
        assert "boundaries" not in rules

    def test_get_rules_nonexistent_persona(self, proc):
        rules = proc.get_rules("nonexistent")
        assert rules == {}

    def test_nested_dict_values(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {
            "relationships": {
                "chris": {"role": "owner", "preferences": "concise"},
            },
        })
        proc.load_personas()
        rules = proc.get_rules("rudy")
        chris = rules["relationships"]["chris"]
        assert isinstance(chris, dict)
        assert chris["role"] == "owner"

    def test_list_values_stored_as_indexed_keys(self, proc, personas_dir):
        _write_persona_json(personas_dir, "batman", {
            "boundaries": ["No file deletion", "No network modification"],
        })
        proc.load_personas()
        boundaries = proc.get_boundaries("batman")
        assert "No file deletion" in boundaries
        assert "No network modification" in boundaries


# ── get_identity / get_boundaries / get_escalation ──────────────


class TestConvenienceMethods:
    @pytest.fixture(autouse=True)
    def setup_persona(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {
            "identity": {"name": "Rudy", "role": "assistant", "tone": "warm"},
            "boundaries": ["Never delete files", "Never share secrets"],
            "escalation": ["Unknown sender", "Financial request"],
        })
        proc.load_personas()

    def test_get_identity(self, proc):
        identity = proc.get_identity("rudy")
        assert identity["name"] == "Rudy"
        assert identity["tone"] == "warm"

    def test_get_boundaries(self, proc):
        boundaries = proc.get_boundaries("rudy")
        assert len(boundaries) == 2
        assert "Never delete files" in boundaries

    def test_get_escalation_triggers(self, proc):
        triggers = proc.get_escalation_triggers("rudy")
        assert len(triggers) == 2
        assert "Unknown sender" in triggers

    def test_empty_identity(self, proc):
        identity = proc.get_identity("nonexistent")
        assert identity == {}


# ── record_behavior / get_behaviors ─────────────────────────────


class TestLearnedBehaviors:
    def test_record_behavior(self, proc):
        row_id = proc.record_behavior("sentinel", "ARP storms from printer are normal")
        assert row_id > 0

    def test_record_with_context(self, proc):
        proc.record_behavior(
            "sentinel",
            "Port 8080 is the dev server",
            context={"ip": "192.168.7.42", "port": 8080},
        )
        behaviors = proc.get_behaviors(agent="sentinel")
        assert len(behaviors) == 1
        assert behaviors[0]["context"]["port"] == 8080

    def test_record_failure(self, proc):
        proc.record_behavior("rudy", "Wrong email template used", success=False)
        all_behaviors = proc.get_behaviors(success_only=False)
        failures = [b for b in all_behaviors if not b["success"]]
        assert len(failures) == 1

    def test_get_success_only(self, proc):
        proc.record_behavior("test", "Good pattern", success=True)
        proc.record_behavior("test", "Bad pattern", success=False)
        successes = proc.get_behaviors(success_only=True)
        assert all(b["success"] for b in successes)

    def test_get_behaviors_by_agent(self, proc):
        proc.record_behavior("sentinel", "Pattern A")
        proc.record_behavior("rudy", "Pattern B")
        sentinel_b = proc.get_behaviors(agent="sentinel")
        assert len(sentinel_b) == 1
        assert sentinel_b[0]["agent"] == "sentinel"

    def test_behaviors_ordered_newest_first(self, proc):
        proc.record_behavior("test", "First")
        proc.record_behavior("test", "Second")
        behaviors = proc.get_behaviors()
        assert behaviors[0]["behavior"] == "Second"

    def test_behavior_limit(self, proc):
        for i in range(20):
            proc.record_behavior("test", f"Pattern {i}")
        behaviors = proc.get_behaviors(limit=5)
        assert len(behaviors) == 5


# ── verify_integrity ────────────────────────────────────────────


class TestIntegrity:
    def test_clean_integrity(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {"identity": {"name": "Rudy"}})
        proc.load_personas()
        result = proc.verify_integrity("rudy")
        assert result["status"] == "clean"
        assert result["files_checked"] == 1

    def test_tampered_file(self, proc, personas_dir):
        filepath = _write_persona_json(
            personas_dir, "rudy", {"identity": {"name": "Rudy"}}
        )
        proc.load_personas()
        # Tamper with the file
        filepath.write_text(json.dumps({"identity": {"name": "HACKED"}}))
        result = proc.verify_integrity("rudy")
        assert result["status"] == "tampered"
        assert len(result["tampered"]) == 1

    def test_missing_file(self, proc, personas_dir):
        filepath = _write_persona_json(
            personas_dir, "rudy", {"identity": {"name": "Rudy"}}
        )
        proc.load_personas()
        filepath.unlink()
        result = proc.verify_integrity("rudy")
        assert result["status"] == "tampered"
        assert result["tampered"][0]["issue"] == "file_missing"

    def test_no_personas_dir(self, db_path):
        proc = ProceduralMemory(db_path, None)
        result = proc.verify_integrity("rudy")
        assert result["status"] == "no_personas_dir"


# ── get_stats ───────────────────────────────────────────────────


class TestStats:
    def test_empty_stats(self, proc):
        stats = proc.get_stats()
        assert stats["personas"] == {}
        assert stats["total_behaviors"] == 0

    def test_stats_after_loading(self, proc, personas_dir):
        _write_persona_json(personas_dir, "rudy", {
            "identity": {"name": "Rudy"},
            "boundaries": ["No deletion"],
        })
        proc.load_personas()
        proc.record_behavior("test", "A pattern")
        stats = proc.get_stats()
        assert "rudy" in stats["personas"]
        assert stats["total_behaviors"] == 1


# ── File Hash ───────────────────────────────────────────────────


class TestFileHash:
    def test_consistent_hash(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}')
        h1 = _file_hash(f)
        h2 = _file_hash(f)
        assert h1 == h2

    def test_different_content(self, tmp_path):
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text('{"key": "a"}')
        f2.write_text('{"key": "b"}')
        assert _file_hash(f1) != _file_hash(f2)
