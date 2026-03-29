"""
Structured Logger — JSON structured logging for observability.

All log entries are JSON with: timestamp, level, agent, event, message,
context (dict), correlation_id, and duration_ms.

Entries are stored in an in-memory ring buffer + SQLite persistence.
Supports timed operations with automatic duration logging.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, ContextManager
import threading
import uuid
from contextlib import contextmanager
import time

log = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """Log levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class LogEntry:
    """A structured log entry."""
    timestamp: str
    level: LogLevel
    agent: str
    event: str
    message: str
    context: Dict[str, Any]
    correlation_id: str
    duration_ms: Optional[float] = None


class StructuredLogger:
    """JSON structured logging with ring buffer and SQLite persistence."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        buffer_size: int = 1000,
    ):
        """Initialize Structured Logger.

        Args:
            db_path: Path to SQLite database (default: memory.sqlite)
            buffer_size: Ring buffer size for in-memory logs
        """
        if db_path is None:
            import os
            desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
            db_path = desktop / "rudy-data" / "memory.sqlite"

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._buffer_size = buffer_size
        self._buffer: List[LogEntry] = []
        self._buffer_index = 0

        self._lock = threading.Lock()

        self._init_db()
        log.info(f"StructuredLogger initialized with db: {self._db_path}, buffer_size: {buffer_size}")

    def _init_db(self) -> None:
        """Create structured_logs table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS structured_logs (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    level TEXT,
                    agent TEXT,
                    event TEXT,
                    message TEXT,
                    context TEXT,
                    correlation_id TEXT,
                    duration_ms REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_logs_timestamp
                ON structured_logs(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_logs_agent_level
                ON structured_logs(agent, level)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_logs_correlation_id
                ON structured_logs(correlation_id)
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def log(
        self,
        level: LogLevel,
        event: str,
        message: str,
        agent: str = "system",
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> LogEntry:
        """Log a structured entry.

        Args:
            level: Log level
            event: Event type (e.g., "agent_spawned", "api_call")
            message: Human-readable message
            agent: Agent name
            context: Optional context dict
            correlation_id: Optional correlation ID for tracing
            duration_ms: Optional duration in milliseconds

        Returns:
            LogEntry that was logged
        """
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            level=level if isinstance(level, LogLevel) else LogLevel(level),
            agent=agent,
            event=event,
            message=message,
            context=context or {},
            correlation_id=correlation_id or str(uuid.uuid4())[:12],
            duration_ms=duration_ms,
        )

        with self._lock:
            # Add to buffer
            if len(self._buffer) < self._buffer_size:
                self._buffer.append(entry)
            else:
                # Ring buffer: overwrite oldest
                self._buffer[self._buffer_index] = entry
                self._buffer_index = (self._buffer_index + 1) % self._buffer_size

        # Persist to database
        self._save_entry(entry)

        # Log via Python logging too
        log_fn = getattr(log, level.value, log.info)
        log_fn(f"[{entry.agent}] {entry.event}: {entry.message}")

        return entry

    def info(
        self,
        event: str,
        message: str,
        agent: str = "system",
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> LogEntry:
        """Log an info-level entry."""
        return self.log(LogLevel.INFO, event, message, agent, context, correlation_id)

    def warning(
        self,
        event: str,
        message: str,
        agent: str = "system",
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> LogEntry:
        """Log a warning-level entry."""
        return self.log(LogLevel.WARNING, event, message, agent, context, correlation_id)

    def error(
        self,
        event: str,
        message: str,
        agent: str = "system",
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> LogEntry:
        """Log an error-level entry."""
        return self.log(LogLevel.ERROR, event, message, agent, context, correlation_id)

    def debug(
        self,
        event: str,
        message: str,
        agent: str = "system",
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> LogEntry:
        """Log a debug-level entry."""
        return self.log(LogLevel.DEBUG, event, message, agent, context, correlation_id)

    @contextmanager
    def timed_operation(
        self,
        name: str,
        agent: str = "system",
        correlation_id: Optional[str] = None,
    ):
        """Context manager for automatic duration logging.

        Args:
            name: Operation name
            agent: Agent name
            correlation_id: Optional correlation ID

        Yields:
            Correlation ID for this operation

        Example:
            with logger.timed_operation("import_data", agent="loader") as cid:
                # ... operation code ...
                pass  # Duration is automatically logged
        """
        cid = correlation_id or str(uuid.uuid4())[:12]
        start = time.time()

        self.info(
            f"{name}_started",
            f"Operation '{name}' started",
            agent=agent,
            correlation_id=cid,
        )

        try:
            yield cid
        finally:
            duration_ms = (time.time() - start) * 1000
            self.info(
                f"{name}_completed",
                f"Operation '{name}' completed in {duration_ms:.1f}ms",
                agent=agent,
                context={"duration_ms": duration_ms},
                correlation_id=cid,
                duration_ms=duration_ms,
            )

    def query_logs(
        self,
        agent: Optional[str] = None,
        level: Optional[LogLevel] = None,
        since: Optional[str] = None,
        event_type: Optional[str] = None,
        correlation_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query logs with flexible filtering.

        Args:
            agent: Filter by agent name
            level: Filter by log level
            since: Filter by timestamp (ISO format)
            event_type: Filter by event type
            correlation_id: Filter by correlation ID
            limit: Maximum results to return

        Returns:
            List of log entry dicts
        """
        conditions = []
        params = []

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if level:
            conditions.append("level = ?")
            params.append(level.value if isinstance(level, LogLevel) else level)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if event_type:
            conditions.append("event = ?")
            params.append(event_type)
        if correlation_id:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""SELECT * FROM structured_logs {where}
                  ORDER BY timestamp DESC
                  LIMIT ?"""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get summary of errors in the past N hours.

        Args:
            hours: Time window in hours

        Returns:
            Dict with error counts by type
        """
        from datetime import timedelta
        since = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self._connect() as conn:
            # Get error counts by agent and event
            rows = conn.execute(
                """SELECT agent, event, COUNT(*) as count
                   FROM structured_logs
                   WHERE level = 'error' AND timestamp >= ?
                   GROUP BY agent, event
                   ORDER BY count DESC""",
                (since,),
            ).fetchall()

        summary = {
            "time_window_hours": hours,
            "since": since,
            "total_errors": sum(row["count"] for row in rows),
            "errors_by_agent": {},
            "errors_by_event": {},
        }

        for row in rows:
            agent = row["agent"]
            event = row["event"]
            count = row["count"]

            if agent not in summary["errors_by_agent"]:
                summary["errors_by_agent"][agent] = 0
            summary["errors_by_agent"][agent] += count

            if event not in summary["errors_by_event"]:
                summary["errors_by_event"][event] = 0
            summary["errors_by_event"][event] += count

        return summary

    def export_json(
        self,
        filepath: Path,
        since: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> int:
        """Export logs to JSON file.

        Args:
            filepath: Path to write JSON to
            since: Optional start timestamp
            agent: Optional agent filter

        Returns:
            Number of entries exported
        """
        entries = self.query_logs(agent=agent, since=since, limit=10000)

        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)

        log.info(f"Exported {len(entries)} logs to {filepath}")
        return len(entries)

    def _save_entry(self, entry: LogEntry) -> None:
        """Persist a log entry to database."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO structured_logs
                       (id, timestamp, level, agent, event, message, context,
                        correlation_id, duration_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        entry.timestamp,
                        entry.level.value,
                        entry.agent,
                        entry.event,
                        entry.message,
                        json.dumps(entry.context),
                        entry.correlation_id,
                        entry.duration_ms,
                    ),
                )
                conn.commit()
        except Exception as e:
            log.debug(f"Failed to save log entry: {e}")

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert database row to dict."""
        d = dict(row)
        if "context" in d and isinstance(d["context"], str):
            try:
                d["context"] = json.loads(d["context"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
