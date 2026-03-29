"""
Circuit Breaker — Prevents cascading failures across agent boundaries.

States:
    CLOSED (normal operation, calls pass through)
    OPEN (too many failures, calls rejected immediately)
    HALF_OPEN (testing recovery, limited calls allowed)

When too many failures occur, the circuit opens and rejects further calls
for a timeout period. After recovery_timeout, moves to HALF_OPEN to test
if the service is healthy. If tests succeed, returns to CLOSED.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
import threading
import uuid

log = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker state."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerStats:
    """Statistics for a circuit breaker."""
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_time: Optional[str]
    last_failure_error: Optional[str]
    state_changed_at: str
    total_calls: int
    rejection_count: int


class CircuitBreaker:
    """Prevents cascading failures by rejecting calls when service is down."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max: int = 3,
    ):
        """Initialize Circuit Breaker.

        Args:
            name: Name of this breaker (e.g., "sentinel_service")
            failure_threshold: Number of failures before opening
            recovery_timeout: Seconds to wait before trying HALF_OPEN
            half_open_max: Number of test calls allowed in HALF_OPEN state
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._last_failure_error: Optional[str] = None
        self._state_changed_at = datetime.now()
        self._total_calls = 0
        self._rejection_count = 0

        self._lock = threading.Lock()

        log.info(
            f"Circuit breaker '{name}' initialized: "
            f"threshold={failure_threshold}, timeout={recovery_timeout}s"
        )

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        """Execute a function call protected by the circuit breaker.

        Args:
            fn: Function to call
            *args, **kwargs: Arguments to pass to fn

        Returns:
            Result of fn if call is allowed

        Raises:
            RuntimeError: If circuit is OPEN (service unavailable)
        """
        with self._lock:
            if not self.can_execute():
                self._rejection_count += 1
                raise RuntimeError(
                    f"Circuit breaker '{self.name}' is {self._state.value}: "
                    f"service unavailable. Last error: {self._last_failure_error}"
                )

            self._total_calls += 1

        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure(str(e))
            raise

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self._success_count += 1

            # If in HALF_OPEN, increment test count
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_count += 1

                # After half_open_max successes, close the circuit
                if self._half_open_count >= self.half_open_max:
                    self._close()

            # If in CLOSED, reset failure count
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

            log.debug(f"Circuit '{self.name}': success recorded (total: {self._total_calls})")

    def record_failure(self, error: str) -> None:
        """Record a failed call.

        Args:
            error: Error message
        """
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()
            self._last_failure_error = error

            # If in HALF_OPEN, any failure sends back to OPEN
            if self._state == CircuitState.HALF_OPEN:
                self._open()

            # If in CLOSED and threshold exceeded, open circuit
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._open()

            log.warning(
                f"Circuit '{self.name}': failure {self._failure_count}/{self.failure_threshold} "
                f"({error[:50]})"
            )

    def can_execute(self) -> bool:
        """Check if a call is allowed.

        Returns:
            True if call should be allowed, False if should be rejected
        """
        with self._lock:
            # If CLOSED, always allow
            if self._state == CircuitState.CLOSED:
                return True

            # If OPEN, check if timeout has elapsed
            if self._state == CircuitState.OPEN:
                if self._last_failure_time:
                    elapsed = (datetime.now() - self._last_failure_time).total_seconds()
                    if elapsed > self.recovery_timeout:
                        self._half_open()
                        return True
                return False

            # If HALF_OPEN, allow up to half_open_max calls
            if self._state == CircuitState.HALF_OPEN:
                return self._half_open_count < self.half_open_max

            return False

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            # Auto-transition from OPEN to HALF_OPEN if timeout elapsed
            if self._state == CircuitState.OPEN and self._last_failure_time:
                elapsed = (datetime.now() - self._last_failure_time).total_seconds()
                if elapsed > self.recovery_timeout:
                    self._half_open()
            return self._state

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        with self._lock:
            self._close()
            log.info(f"Circuit '{self.name}' manually reset")

    def get_stats(self) -> CircuitBreakerStats:
        """Get current statistics.

        Returns:
            CircuitBreakerStats object with current metrics
        """
        with self._lock:
            return CircuitBreakerStats(
                state=self._state,
                failure_count=self._failure_count,
                success_count=self._success_count,
                last_failure_time=self._last_failure_time.isoformat() if self._last_failure_time else None,
                last_failure_error=self._last_failure_error,
                state_changed_at=self._state_changed_at.isoformat(),
                total_calls=self._total_calls,
                rejection_count=self._rejection_count,
            )

    def _close(self) -> None:
        """Transition to CLOSED state."""
        if self._state != CircuitState.CLOSED:
            log.info(f"Circuit '{self.name}' closing")
            self._state = CircuitState.CLOSED
            self._state_changed_at = datetime.now()
            self._failure_count = 0
            self._success_count = 0
            self._half_open_count = 0

    def _open(self) -> None:
        """Transition to OPEN state."""
        if self._state != CircuitState.OPEN:
            log.warning(f"Circuit '{self.name}' opening due to failures")
            self._state = CircuitState.OPEN
            self._state_changed_at = datetime.now()
            self._half_open_count = 0

    def _half_open(self) -> None:
        """Transition to HALF_OPEN state."""
        if self._state != CircuitState.HALF_OPEN:
            log.info(f"Circuit '{self.name}' transitioning to HALF_OPEN")
            self._state = CircuitState.HALF_OPEN
            self._state_changed_at = datetime.now()
            self._failure_count = 0
            self._success_count = 0
            self._half_open_count = 0


class CircuitBreakerRegistry:
    """Manages multiple circuit breakers."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize registry.

        Args:
            db_path: Path to SQLite database for persistence
        """
        if db_path is None:
            import os
            desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
            db_path = desktop / "rudy-data" / "memory.sqlite"

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

        self._init_db()
        log.info(f"CircuitBreakerRegistry initialized with db: {self._db_path}")

    def _init_db(self) -> None:
        """Create circuit_breakers table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS circuit_breakers (
                    name TEXT PRIMARY KEY,
                    state TEXT,
                    failure_count INTEGER,
                    success_count INTEGER,
                    last_failure_time TEXT,
                    last_failure_error TEXT,
                    state_changed_at TEXT,
                    total_calls INTEGER,
                    rejection_count INTEGER,
                    updated_at TEXT
                )
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max: int = 3,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker by name.

        Args:
            name: Breaker name
            failure_threshold: Failures before opening
            recovery_timeout: Seconds before trying recovery
            half_open_max: Test calls in HALF_OPEN

        Returns:
            CircuitBreaker instance
        """
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    half_open_max=half_open_max,
                )
            return self._breakers[name]

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats for all registered breakers.

        Returns:
            Dict mapping breaker name to stats dict
        """
        with self._lock:
            stats = {}
            for name, breaker in self._breakers.items():
                s = breaker.get_stats()
                stats[name] = {
                    "state": s.state.value,
                    "failures": s.failure_count,
                    "successes": s.success_count,
                    "total_calls": s.total_calls,
                    "rejections": s.rejection_count,
                    "last_failure": s.last_failure_time,
                    "last_error": s.last_failure_error,
                }
                self._save_stats(name, s)

            return stats

    def get_open_circuits(self) -> List[str]:
        """Get names of all OPEN circuit breakers.

        Returns:
            List of breaker names with state=OPEN
        """
        with self._lock:
            return [
                name for name, breaker in self._breakers.items()
                if breaker.state == CircuitState.OPEN
            ]

    def _save_stats(self, name: str, stats: CircuitBreakerStats) -> None:
        """Persist stats to database."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO circuit_breakers
                       (name, state, failure_count, success_count, last_failure_time,
                        last_failure_error, state_changed_at, total_calls, rejection_count,
                        updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        name,
                        stats.state.value,
                        stats.failure_count,
                        stats.success_count,
                        stats.last_failure_time,
                        stats.last_failure_error,
                        stats.state_changed_at,
                        stats.total_calls,
                        stats.rejection_count,
                        datetime.now().isoformat(),
                    ),
                )
                conn.commit()
        except Exception as e:
            log.error(f"Failed to save circuit breaker stats: {e}")
