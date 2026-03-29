"""
Procedural Memory — persona rules and learned behaviors.

Loads persona definitions from YAML files in rudy/personas/ and
caches them in SQLite for fast retrieval. Also stores learned
behaviors — patterns that agents discover during operation.

Persona files define:
  - identity: name, role, tone, archetype
  - capabilities: what this persona can do
  - boundaries: what this persona must never do
  - escalation: when to hand off to Oracle or request HITL approval
  - relationships: how to interact with specific contacts

Learned behaviors capture:
  - Successful recovery patterns (from Reflexion loops)
  - User preference adaptations
  - Environmental baselines
"""

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any

from rudy.memory.schema import PROCEDURAL_SCHEMA

log = logging.getLogger(__name__)

# Try to import yaml; fall back to json-only mode
try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    log.info("PyYAML not installed — persona files must use JSON format")


def _file_hash(filepath: Path) -> str:
    """SHA-256 hash of file content for tamper detection."""
    h = hashlib.sha256()
    try:
        h.update(filepath.read_bytes())
    except OSError:
        h.update(b"missing")
    return h.hexdigest()[:32]


class ProceduralMemory:
    """Persona rules and learned behaviors backed by SQLite.

    Loads persona YAML/JSON files from a directory and caches the
    parsed rules in SQLite for fast, structured retrieval.

    Usage:
        proc = ProceduralMemory(db_path, personas_dir)
        proc.load_personas()  # parse YAML files into SQLite
        rules = proc.get_rules("rudy")
        boundaries = proc.get_boundaries("batman")
    """

    def __init__(self, db_path: Path, personas_dir: Optional[Path] = None):
        self._db_path = db_path
        self._personas_dir = personas_dir
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(PROCEDURAL_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def load_personas(self) -> Dict[str, int]:
        """Load all persona files from the personas directory.

        Scans for .yaml, .yml, and .json files. Each file defines
        one persona. Only reloads files that have changed.

        Returns:
            Dict mapping persona name to count of rules loaded.
        """
        if self._personas_dir is None or not self._personas_dir.exists():
            log.debug(f"Personas directory not found: {self._personas_dir}")
            return {}

        results = {}
        for filepath in sorted(self._personas_dir.iterdir()):
            if filepath.suffix not in (".yaml", ".yml", ".json"):
                continue
            persona_name = filepath.stem
            count = self._load_persona_file(filepath, persona_name)
            results[persona_name] = count

        return results

    def _load_persona_file(self, filepath: Path, persona_name: str) -> int:
        """Load a single persona file into SQLite.

        Skips if file hasn't changed since last load.

        Returns:
            Count of rules loaded.
        """
        current_hash = _file_hash(filepath)

        with self._connect() as conn:
            existing = conn.execute(
                """SELECT file_hash FROM persona_rules
                   WHERE persona = ? AND source_file = ? LIMIT 1""",
                (persona_name, str(filepath)),
            ).fetchone()

        if existing and existing[0] == current_hash:
            count = self._count_rules(persona_name)
            return count

        # Parse the file
        data = self._parse_persona_file(filepath)
        if not data:
            return 0

        # Clear old rules for this persona from this file
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM persona_rules WHERE persona = ? AND source_file = ?",
                (persona_name, str(filepath)),
            )

        # Insert new rules
        rules_count = 0
        with self._connect() as conn:
            for rule_type, rules in data.items():
                if isinstance(rules, dict):
                    for key, value in rules.items():
                        value_json = (
                            json.dumps(value, default=str)
                            if not isinstance(value, str)
                            else value
                        )
                        conn.execute(
                            """INSERT OR REPLACE INTO persona_rules
                               (persona, rule_type, rule_key, rule_value,
                                source_file, file_hash)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (
                                persona_name,
                                rule_type,
                                key,
                                value_json,
                                str(filepath),
                                current_hash,
                            ),
                        )
                        rules_count += 1
                elif isinstance(rules, list):
                    for i, item in enumerate(rules):
                        value_json = (
                            json.dumps(item, default=str)
                            if not isinstance(item, str)
                            else item
                        )
                        conn.execute(
                            """INSERT OR REPLACE INTO persona_rules
                               (persona, rule_type, rule_key, rule_value,
                                source_file, file_hash)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (
                                persona_name,
                                rule_type,
                                f"{rule_type}_{i}",
                                value_json,
                                str(filepath),
                                current_hash,
                            ),
                        )
                        rules_count += 1
                elif isinstance(rules, str):
                    conn.execute(
                        """INSERT OR REPLACE INTO persona_rules
                           (persona, rule_type, rule_key, rule_value,
                            source_file, file_hash)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            persona_name,
                            "meta",
                            rule_type,
                            rules,
                            str(filepath),
                            current_hash,
                        ),
                    )
                    rules_count += 1

        return rules_count

    def _parse_persona_file(self, filepath: Path) -> Optional[Dict]:
        """Parse a YAML or JSON persona file."""
        try:
            content = filepath.read_text(encoding="utf-8")
            if filepath.suffix == ".json":
                return json.loads(content)
            elif HAS_YAML:
                return yaml.safe_load(content)
            else:
                log.warning(
                    f"Cannot parse {filepath.name} — PyYAML not installed"
                )
                return None
        except Exception as e:
            log.debug(f"Error parsing persona file {filepath}: {e}")
            return None

    def _count_rules(self, persona: str) -> int:
        """Count rules for a persona."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM persona_rules WHERE persona = ?",
                (persona,),
            ).fetchone()[0]

    def get_rules(
        self,
        persona: str,
        rule_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all rules for a persona, optionally filtered by type.

        Returns:
            Dict organized by rule_type, then rule_key -> rule_value.
        """
        with self._connect() as conn:
            if rule_type:
                rows = conn.execute(
                    """SELECT rule_type, rule_key, rule_value
                       FROM persona_rules
                       WHERE persona = ? AND rule_type = ?
                       ORDER BY priority DESC, rule_key""",
                    (persona, rule_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT rule_type, rule_key, rule_value
                       FROM persona_rules
                       WHERE persona = ?
                       ORDER BY rule_type, priority DESC, rule_key""",
                    (persona,),
                ).fetchall()

        result: Dict[str, Any] = {}
        for row in rows:
            rt = row[0]
            rk = row[1]
            rv = row[2]
            # Try to parse JSON values
            try:
                rv = json.loads(rv)
            except (json.JSONDecodeError, TypeError):
                pass

            if rt not in result:
                result[rt] = {}
            result[rt][rk] = rv

        return result

    def get_boundaries(self, persona: str) -> List[str]:
        """Get the boundary rules (things persona must not do).

        Returns:
            List of boundary strings.
        """
        rules = self.get_rules(persona, rule_type="boundaries")
        boundaries = rules.get("boundaries", {})
        return list(boundaries.values())

    def get_identity(self, persona: str) -> Dict[str, str]:
        """Get identity metadata for a persona.

        Returns:
            Dict with name, role, tone, archetype, etc.
        """
        rules = self.get_rules(persona, rule_type="identity")
        return rules.get("identity", {})

    def get_escalation_triggers(self, persona: str) -> List[str]:
        """Get conditions under which this persona escalates to Oracle."""
        rules = self.get_rules(persona, rule_type="escalation")
        triggers = rules.get("escalation", {})
        return list(triggers.values())

    def record_behavior(
        self,
        agent: str,
        behavior: str,
        context: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ) -> int:
        """Record a learned behavior.

        When an agent successfully recovers from an error or adapts
        to a new pattern, it records the behavior here so it (and
        other agents) can reference it in the future.

        Returns:
            The row ID of the inserted behavior.
        """
        context_json = json.dumps(context or {}, default=str)
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO learned_behaviors (agent, behavior, context, success)
                   VALUES (?, ?, ?, ?)""",
                (agent, behavior, context_json, 1 if success else 0),
            )
            return cursor.lastrowid

    def get_behaviors(
        self,
        agent: Optional[str] = None,
        success_only: bool = True,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve learned behaviors.

        Args:
            agent: Filter by agent name (None for all).
            success_only: Only return successful patterns.
            limit: Max results.

        Returns:
            List of behavior dicts.
        """
        conditions = []
        params = []

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if success_only:
            conditions.append("success = 1")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""SELECT agent, behavior, context, success, learned_at
                  FROM learned_behaviors {where}
                  ORDER BY learned_at DESC LIMIT ?"""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            ctx = row[2]
            try:
                ctx = json.loads(ctx)
            except (json.JSONDecodeError, TypeError):
                pass
            results.append({
                "agent": row[0],
                "behavior": row[1],
                "context": ctx,
                "success": bool(row[3]),
                "learned_at": row[4],
            })
        return results

    def verify_integrity(self, persona: str) -> Dict[str, Any]:
        """Verify that persona rules haven't been tampered with.

        Recomputes file hashes and compares against stored hashes.
        Returns integrity report.
        """
        if self._personas_dir is None:
            return {"status": "no_personas_dir"}

        results = {"persona": persona, "files_checked": 0, "tampered": []}

        with self._connect() as conn:
            stored = conn.execute(
                """SELECT DISTINCT source_file, file_hash
                   FROM persona_rules WHERE persona = ?""",
                (persona,),
            ).fetchall()

        for row in stored:
            filepath = Path(row[0])
            stored_hash = row[1]
            results["files_checked"] += 1

            if not filepath.exists():
                results["tampered"].append({
                    "file": str(filepath),
                    "issue": "file_missing",
                })
                continue

            current_hash = _file_hash(filepath)
            if current_hash != stored_hash:
                results["tampered"].append({
                    "file": str(filepath),
                    "issue": "hash_mismatch",
                    "stored": stored_hash,
                    "current": current_hash,
                })

        results["status"] = "clean" if not results["tampered"] else "tampered"
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get procedural memory statistics."""
        with self._connect() as conn:
            personas = conn.execute(
                """SELECT persona, COUNT(*) as cnt
                   FROM persona_rules GROUP BY persona"""
            ).fetchall()
            behaviors = conn.execute(
                "SELECT COUNT(*) FROM learned_behaviors"
            ).fetchone()[0]

        return {
            "personas": {row[0]: row[1] for row in personas},
            "total_behaviors": behaviors,
            "yaml_support": HAS_YAML,
        }
