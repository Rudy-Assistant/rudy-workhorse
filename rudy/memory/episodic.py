"""
Episodic Memory — timestamped event log for the Oracle system.

Records every significant event: tool invocations, user commands,
agent-to-agent messages, security alerts, and system health changes.

Answers questions like:
  "What happened yesterday?"
  "When did sentinel last detect a threat?"
  "Show me all actions taken by rudy in the last hour"

Automatic maintenance:
  - Events older than 30 days are compressed into daily_summaries
  - Summaries preserve key facts while reducing storage
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from rudy.memory.schema import EPISODIC_SCHEMA, SUMMARY_SCHEMA

log = logging.getLogger(__name__)


class EpisodicMemory:
    """Timestamped event store backed by SQLite."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(EPISODIC_SCHEMA)
            conn.executescript(SUMMARY_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection with optimal settings."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def log_event(
        self,
        agent: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """Record an event.

        Args:
            agent: Name of the agent that generated the event.
            event_type: Category (e.g. "alert", "action", "tool_call",
                        "user_command", "message", "health", "error").
            payload: Arbitrary JSON-serializable data.
            session_id: Optional Cowork session identifier.
            tags: Optional list of string tags for filtering.
            timestamp: Optional ISO timestamp (defaults to now).

        Returns:
            The row ID of the inserted event.
        """
        payload_json = json.dumps(payload or {}, default=str)
        tags_json = json.dumps(tags) if tags else None
        ts = timestamp or datetime.now().isoformat()

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO events (timestamp, agent, event_type, payload, session_id, tags)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, agent, event_type, payload_json, session_id, tags_json),
            )
            return cursor.lastrowid

    def query(
        self,
        agent: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query events with flexible filtering.

        All filters are optional and combined with AND.

        Returns:
            List of event dicts, newest first.
        """
        conditions = []
        params = []

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if tags:
            for tag in tags:
                conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""SELECT id, timestamp, agent, event_type, payload, session_id, tags
                  FROM events {where}
                  ORDER BY timestamp DESC
                  LIMIT ? OFFSET ?"""
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def count(
        self,
        agent: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
    ) -> int:
        """Count events matching filters."""
        conditions = []
        params = []

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT COUNT(*) FROM events {where}"

        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()[0]

    def get_recent(self, agent: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get the most recent events for a specific agent."""
        return self.query(agent=agent, limit=limit)

    def get_timeline(
        self,
        since: str,
        until: Optional[str] = None,
        agents: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get a chronological timeline of events.

        Args:
            since: ISO timestamp for start of range.
            until: ISO timestamp for end of range (default: now).
            agents: Optional list of agent names to filter.

        Returns:
            List of events in chronological order (oldest first).
        """
        until = until or datetime.now().isoformat()
        conditions = ["timestamp >= ?", "timestamp <= ?"]
        params = [since, until]

        if agents:
            placeholders = ",".join("?" * len(agents))
            conditions.append(f"agent IN ({placeholders})")
            params.extend(agents)

        where = f"WHERE {' AND '.join(conditions)}"
        sql = f"""SELECT id, timestamp, agent, event_type, payload, session_id, tags
                  FROM events {where}
                  ORDER BY timestamp ASC"""

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def compress_old_events(self, days_threshold: int = 30) -> Dict[str, int]:
        """Compress events older than threshold into daily summaries.

        This preserves the key facts while reducing storage. Original
        events are deleted after summarization.

        Returns:
            Dict with counts of events compressed and summaries created.
        """
        cutoff = (datetime.now() - timedelta(days=days_threshold)).strftime("%Y-%m-%d")
        events_compressed = 0
        summaries_created = 0

        with self._connect() as conn:
            # Find dates that need compression
            dates = conn.execute(
                """SELECT DISTINCT date(timestamp) as d
                   FROM events
                   WHERE date(timestamp) < ?
                   ORDER BY d""",
                (cutoff,),
            ).fetchall()

            for (date_str,) in dates:
                # Check if already summarized
                existing = conn.execute(
                    "SELECT id FROM daily_summaries WHERE date = ?",
                    (date_str,),
                ).fetchone()
                if existing:
                    continue

                # Get events for this date
                events = conn.execute(
                    """SELECT agent, event_type, payload
                       FROM events
                       WHERE date(timestamp) = ?
                       ORDER BY timestamp""",
                    (date_str,),
                ).fetchall()

                if not events:
                    continue

                # Build summary
                event_count = len(events)
                agents_active = set()
                type_counts = {}
                key_events = []

                for row in events:
                    agents_active.add(row[0])
                    t = row[1]
                    type_counts[t] = type_counts.get(t, 0) + 1
                    if t in ("alert", "error", "user_command"):
                        try:
                            payload = json.loads(row[2])
                        except (json.JSONDecodeError, TypeError):
                            payload = {"raw": row[2]}
                        key_events.append({
                            "agent": row[0],
                            "type": t,
                            "payload": payload,
                        })

                summary_text = json.dumps({
                    "agents_active": sorted(agents_active),
                    "event_types": type_counts,
                    "total_events": event_count,
                    "key_events": key_events[:50],
                }, default=str)

                conn.execute(
                    """INSERT OR REPLACE INTO daily_summaries (date, summary, event_count)
                       VALUES (?, ?, ?)""",
                    (date_str, summary_text, event_count),
                )
                summaries_created += 1

                # Delete compressed events
                deleted = conn.execute(
                    "DELETE FROM events WHERE date(timestamp) = ?",
                    (date_str,),
                ).rowcount
                events_compressed += deleted

        return {
            "events_compressed": events_compressed,
            "summaries_created": summaries_created,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        with self._connect() as conn:
            total_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            total_summaries = conn.execute(
                "SELECT COUNT(*) FROM daily_summaries"
            ).fetchone()[0]

            agents = conn.execute(
                "SELECT DISTINCT agent FROM events"
            ).fetchall()
            agent_names = [row[0] for row in agents]

            oldest = conn.execute(
                "SELECT MIN(timestamp) FROM events"
            ).fetchone()[0]
            newest = conn.execute(
                "SELECT MAX(timestamp) FROM events"
            ).fetchone()[0]

        return {
            "total_events": total_events,
            "total_summaries": total_summaries,
            "active_agents": agent_names,
            "oldest_event": oldest,
            "newest_event": newest,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row to a plain dict with parsed JSON."""
        d = dict(row)
        if "payload" in d and isinstance(d["payload"], str):
            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                pass
        if "tags" in d and isinstance(d["tags"], str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
