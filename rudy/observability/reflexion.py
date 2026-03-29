"""
Reflexion Engine — Self-healing pattern for agent failures.

Pattern: error → hypothesis → restructure → retry → learn

When an agent encounters an error, ReflexionEngine:
1. Analyzes the error to form a hypothesis about root cause
2. Generates a restructured approach based on the hypothesis
3. Attempts retry with the new approach
4. Records the outcome and learns from success/failure

This closes the loop between failure and recovery, enabling agents
to self-correct without human intervention.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import uuid

log = logging.getLogger(__name__)


class ReflexionStatus(str, Enum):
    """Status of a reflection cycle."""
    ATTEMPTING = "attempting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ESCALATED = "escalated"


@dataclass
class ReflexionCycle:
    """A single reflection cycle: analyze error, form hypothesis, restructure, retry."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    agent: str = ""
    error: Dict[str, Any] = field(default_factory=dict)  # {type, message, traceback}
    hypothesis: str = ""
    restructured_approach: str = ""
    retry_count: int = 0
    max_retries: int = 3
    status: ReflexionStatus = ReflexionStatus.ATTEMPTING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: Optional[str] = None
    result: Optional[str] = None  # Result from retry


class ReflexionEngine:
    """Self-healing system: error → hypothesis → restructure → retry → learn."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize Reflexion Engine.

        Args:
            db_path: Path to SQLite database (default: memory.sqlite in Desktop/rudy-data)
        """
        if db_path is None:
            import os
            desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
            db_path = desktop / "rudy-data" / "memory.sqlite"

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory registry of active cycles
        self._active_cycles: Dict[str, ReflexionCycle] = {}

        self._init_db()
        log.info(f"ReflexionEngine initialized with db: {self._db_path}")

    def _init_db(self) -> None:
        """Create reflexion_cycles table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reflexion_cycles (
                    id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    error TEXT,
                    hypothesis TEXT,
                    restructured_approach TEXT,
                    retry_count INTEGER,
                    max_retries INTEGER,
                    status TEXT,
                    created_at TEXT,
                    resolved_at TEXT,
                    result TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_reflexion_agent_status
                ON reflexion_cycles(agent, status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_reflexion_created_at
                ON reflexion_cycles(created_at)
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection with optimal settings."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def begin_cycle(self, agent: str, error_info: Dict[str, Any]) -> ReflexionCycle:
        """Start a new reflection cycle.

        Args:
            agent: Name of the agent that encountered the error
            error_info: Dict with keys: type, message, traceback

        Returns:
            ReflexionCycle initialized and ready for analysis
        """
        cycle = ReflexionCycle(
            agent=agent,
            error=error_info,
            status=ReflexionStatus.ATTEMPTING,
        )

        self._active_cycles[cycle.id] = cycle
        log.info(f"Reflexion cycle {cycle.id} begun for {agent}: {error_info.get('message', 'unknown error')}")

        return cycle

    def generate_hypothesis(self, cycle: ReflexionCycle) -> str:
        """Analyze error and generate hypothesis about root cause.

        Uses pattern matching:
        - timeout → retry with backoff
        - import error → check dependency
        - permission → escalate
        - memory → reduce context
        - network → retry with fallback

        Args:
            cycle: ReflexionCycle to analyze

        Returns:
            Hypothesis string describing the likely root cause
        """
        error_type = cycle.error.get("type", "").lower()
        error_msg = cycle.error.get("message", "").lower()

        # Pattern matching for common errors
        if "timeout" in error_msg or error_type == "timeoutexpired":
            hypothesis = (
                "Timeout detected. Likely causes: external service slow, network latency, "
                "or resource exhaustion. Recommended: retry with exponential backoff, "
                "increase timeout, or reduce payload size."
            )
        elif "import" in error_msg or error_type == "importerror":
            hypothesis = (
                "Import error detected. Likely cause: missing dependency or incorrect version. "
                "Recommended: verify dependencies are installed, check sys.path, or reload module."
            )
        elif "permission" in error_msg or error_type == "permissionerror":
            hypothesis = (
                "Permission error detected. Likely cause: insufficient access rights. "
                "Recommended: escalate to human review or use service account with elevated privileges."
            )
        elif "memory" in error_msg or error_type == "memoryerror":
            hypothesis = (
                "Memory error detected. Likely cause: large dataset or memory leak. "
                "Recommended: reduce context window, paginate results, or reduce batch size."
            )
        elif "connection" in error_msg or "network" in error_msg or error_type == "connectionerror":
            hypothesis = (
                "Network/connection error detected. Likely cause: service unavailable or network latency. "
                "Recommended: retry with exponential backoff, use fallback service, or implement circuit breaker."
            )
        else:
            # Generic fallback
            hypothesis = (
                f"Unknown error type '{error_type}': {error_msg[:100]}. "
                "Recommended: review full traceback, check recent system changes, or escalate."
            )

        cycle.hypothesis = hypothesis
        log.debug(f"Hypothesis for {cycle.id}: {hypothesis}")

        return hypothesis

    def restructure(self, cycle: ReflexionCycle, hypothesis: str = "") -> str:
        """Generate a restructured approach based on hypothesis.

        Args:
            cycle: ReflexionCycle to restructure
            hypothesis: Optional hypothesis (uses cycle.hypothesis if not provided)

        Returns:
            Restructured approach string
        """
        if not hypothesis:
            hypothesis = cycle.hypothesis or self.generate_hypothesis(cycle)

        # Build restructured approach based on hypothesis
        if "retry with backoff" in hypothesis.lower():
            restructured = (
                f"Restructure: Implement exponential backoff with jitter. "
                f"Start with 1s delay, double each retry (up to 32s), add random jitter (0-100ms). "
                f"Max retries: {cycle.max_retries}."
            )
        elif "reduce context" in hypothesis.lower():
            restructured = (
                "Restructure: Reduce context window by 50%. Paginate large datasets. "
                "Process one item at a time instead of batch."
            )
        elif "check dependency" in hypothesis.lower():
            restructured = (
                "Restructure: Verify all imports are available. Use importlib to check. "
                "If missing, escalate with list of required packages."
            )
        elif "fallback service" in hypothesis.lower():
            restructured = (
                "Restructure: Attempt request against backup endpoint. "
                "If primary service unavailable, route to secondary."
            )
        elif "escalate" in hypothesis.lower():
            restructured = (
                "Restructure: Permission error cannot be auto-recovered. "
                "Escalate to human with full error context and access requirements."
            )
        else:
            restructured = (
                "Restructure: Review full error traceback. Check recent system changes. "
                "If unable to determine cause, escalate to human."
            )

        cycle.restructured_approach = restructured
        log.debug(f"Restructured approach for {cycle.id}: {restructured}")

        return restructured

    def attempt_retry(
        self,
        cycle: ReflexionCycle,
        executor_fn: Callable,
    ) -> bool:
        """Execute the restructured approach via retry.

        Args:
            cycle: ReflexionCycle with restructured approach
            executor_fn: Callable that executes the agent task
                        Returns (success: bool, result: Any)

        Returns:
            True if retry succeeded, False otherwise
        """
        if cycle.retry_count >= cycle.max_retries:
            log.warning(f"Cycle {cycle.id}: max retries ({cycle.max_retries}) exceeded")
            return False

        cycle.retry_count += 1
        log.info(f"Retry {cycle.retry_count}/{cycle.max_retries} for {cycle.id}")

        try:
            success, result = executor_fn()
            if success:
                cycle.result = str(result)
                log.info(f"Retry succeeded for {cycle.id}")
                return True
            else:
                log.warning(f"Retry failed for {cycle.id}: {result}")
                return False
        except Exception as e:
            log.error(f"Exception during retry for {cycle.id}: {e}")
            return False

    def record_outcome(
        self,
        cycle: ReflexionCycle,
        success: bool,
        result: Optional[str] = None,
    ) -> None:
        """Record the outcome and learn from it.

        Updates cycle status, logs to database, and records learning
        to episodic memory if available.

        Args:
            cycle: ReflexionCycle to record
            success: Whether the restructured approach succeeded
            result: Optional result string
        """
        cycle.resolved_at = datetime.now().isoformat()
        cycle.status = ReflexionStatus.SUCCEEDED if success else ReflexionStatus.FAILED

        if result:
            cycle.result = result

        # Persist to database
        self._save_cycle(cycle)

        log.info(
            f"Cycle {cycle.id} resolved: status={cycle.status}, "
            f"retries={cycle.retry_count}, agent={cycle.agent}"
        )

        # Try to log to episodic memory if available
        try:
            from rudy.memory.manager import MemoryManager
            mem = MemoryManager()
            mem.log_event(
                agent=cycle.agent,
                event_type="reflexion_resolved",
                payload={
                    "cycle_id": cycle.id,
                    "status": cycle.status.value,
                    "retries": cycle.retry_count,
                    "error_type": cycle.error.get("type"),
                    "success": success,
                },
                tags=["reflexion", "self_healing"],
            )

            # Learn successful patterns
            if success:
                mem.learn(
                    agent=cycle.agent,
                    behavior=f"Handled {cycle.error.get('type', 'unknown')} error using: {cycle.hypothesis}",
                    context={"cycle_id": cycle.id, "restructured": cycle.restructured_approach},
                    success=True,
                )
        except Exception as e:
            log.debug(f"Failed to log reflexion to memory: {e}")

    def get_active_cycles(self) -> List[ReflexionCycle]:
        """Get currently in-progress reflection cycles.

        Returns:
            List of ReflexionCycle objects with status=ATTEMPTING
        """
        return [
            cycle for cycle in self._active_cycles.values()
            if cycle.status == ReflexionStatus.ATTEMPTING
        ]

    def get_history(self, agent: str, limit: int = 50) -> List[ReflexionCycle]:
        """Get past reflection cycles for an agent.

        Args:
            agent: Agent name to filter by
            limit: Maximum number of cycles to return

        Returns:
            List of ReflexionCycle objects, newest first
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM reflexion_cycles
                   WHERE agent = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (agent, limit),
            ).fetchall()

        return [self._row_to_cycle(row) for row in rows]

    def _save_cycle(self, cycle: ReflexionCycle) -> None:
        """Persist a cycle to database."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO reflexion_cycles
                   (id, agent, error, hypothesis, restructured_approach,
                    retry_count, max_retries, status, created_at, resolved_at, result)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cycle.id,
                    cycle.agent,
                    json.dumps(cycle.error),
                    cycle.hypothesis,
                    cycle.restructured_approach,
                    cycle.retry_count,
                    cycle.max_retries,
                    cycle.status.value,
                    cycle.created_at,
                    cycle.resolved_at,
                    cycle.result,
                ),
            )
            conn.commit()

    def _row_to_cycle(self, row: sqlite3.Row) -> ReflexionCycle:
        """Convert database row to ReflexionCycle."""
        error = {}
        if row["error"]:
            try:
                error = json.loads(row["error"])
            except (json.JSONDecodeError, TypeError):
                pass

        return ReflexionCycle(
            id=row["id"],
            agent=row["agent"],
            error=error,
            hypothesis=row["hypothesis"] or "",
            restructured_approach=row["restructured_approach"] or "",
            retry_count=row["retry_count"] or 0,
            max_retries=row["max_retries"] or 3,
            status=ReflexionStatus(row["status"]) if row["status"] else ReflexionStatus.ATTEMPTING,
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            result=row["result"],
        )
