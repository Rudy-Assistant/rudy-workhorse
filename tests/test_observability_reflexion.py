"""
Comprehensive tests for ReflexionEngine and ReflexionCycle.

Tests cover:
- Cycle creation and field initialization
- Error hypothesis generation for various error types
- Restructure approach generation
- Retry execution and success/failure handling
- Outcome recording and persistence
- Active cycle tracking and history queries
- SQLite persistence and durability
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from rudy.observability.reflexion import (
    ReflexionEngine,
    ReflexionCycle,
    ReflexionStatus,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        yield db_path


@pytest.fixture
def engine(temp_db):
    """Create a ReflexionEngine with temp database."""
    return ReflexionEngine(db_path=temp_db)


class TestReflexionCycle:
    """Test ReflexionCycle data class."""

    def test_cycle_creation_with_defaults(self):
        """Test creating a cycle with default values."""
        cycle = ReflexionCycle()
        assert cycle.agent == ""
        assert cycle.error == {}
        assert cycle.hypothesis == ""
        assert cycle.restructured_approach == ""
        assert cycle.retry_count == 0
        assert cycle.max_retries == 3
        assert cycle.status == ReflexionStatus.ATTEMPTING
        assert cycle.resolved_at is None
        assert cycle.result is None
        assert len(cycle.id) > 0

    def test_cycle_creation_with_values(self):
        """Test creating a cycle with specific values."""
        error_info = {"type": "TimeoutError", "message": "Request timed out"}
        cycle = ReflexionCycle(
            agent="test_agent",
            error=error_info,
            max_retries=5,
        )
        assert cycle.agent == "test_agent"
        assert cycle.error == error_info
        assert cycle.max_retries == 5
        assert cycle.status == ReflexionStatus.ATTEMPTING

    def test_cycle_id_is_unique(self):
        """Test that each cycle gets a unique ID."""
        cycle1 = ReflexionCycle(agent="agent1")
        cycle2 = ReflexionCycle(agent="agent1")
        assert cycle1.id != cycle2.id


class TestReflexionEngine:
    """Test ReflexionEngine core functionality."""

    def test_engine_initialization(self, temp_db):
        """Test engine initializes with database."""
        engine = ReflexionEngine(db_path=temp_db)
        assert engine._db_path == temp_db
        assert temp_db.parent.exists()

    def test_engine_uses_default_db_path(self):
        """Test engine creates default db path if not provided."""
        engine = ReflexionEngine()
        assert engine._db_path is not None
        assert "rudy-data" in str(engine._db_path)

    def test_begin_cycle(self, engine):
        """Test starting a new reflection cycle."""
        error_info = {"type": "TimeoutError", "message": "Request timed out"}
        cycle = engine.begin_cycle("test_agent", error_info)

        assert cycle.agent == "test_agent"
        assert cycle.error == error_info
        assert cycle.status == ReflexionStatus.ATTEMPTING
        assert cycle.id in engine._active_cycles

    def test_begin_cycle_creates_unique_ids(self, engine):
        """Test that each cycle gets a unique ID."""
        error_info = {"type": "Error", "message": "test"}
        cycle1 = engine.begin_cycle("agent1", error_info)
        cycle2 = engine.begin_cycle("agent1", error_info)
        assert cycle1.id != cycle2.id


class TestHypothesisGeneration:
    """Test hypothesis generation for different error types."""

    def test_timeout_error_hypothesis(self, engine):
        """Test hypothesis for timeout errors."""
        error_info = {"type": "TimeoutExpired", "message": "Request timeout"}
        cycle = engine.begin_cycle("agent1", error_info)
        hypothesis = engine.generate_hypothesis(cycle)

        assert "timeout" in hypothesis.lower()
        assert "backoff" in hypothesis.lower()
        assert cycle.hypothesis == hypothesis

    def test_import_error_hypothesis(self, engine):
        """Test hypothesis for import errors."""
        error_info = {"type": "ImportError", "message": "No module named 'xyz'"}
        cycle = engine.begin_cycle("agent1", error_info)
        hypothesis = engine.generate_hypothesis(cycle)

        assert "import" in hypothesis.lower()
        assert "dependency" in hypothesis.lower()

    def test_permission_error_hypothesis(self, engine):
        """Test hypothesis for permission errors."""
        error_info = {"type": "PermissionError", "message": "Access denied"}
        cycle = engine.begin_cycle("agent1", error_info)
        hypothesis = engine.generate_hypothesis(cycle)

        assert "permission" in hypothesis.lower()
        assert "escalate" in hypothesis.lower()

    def test_memory_error_hypothesis(self, engine):
        """Test hypothesis for memory errors."""
        error_info = {"type": "MemoryError", "message": "Cannot allocate memory"}
        cycle = engine.begin_cycle("agent1", error_info)
        hypothesis = engine.generate_hypothesis(cycle)

        assert "memory" in hypothesis.lower()
        assert "reduce" in hypothesis.lower() or "context" in hypothesis.lower()

    def test_network_error_hypothesis(self, engine):
        """Test hypothesis for network errors."""
        error_info = {"type": "ConnectionError", "message": "Network unreachable"}
        cycle = engine.begin_cycle("agent1", error_info)
        hypothesis = engine.generate_hypothesis(cycle)

        assert "network" in hypothesis.lower() or "connection" in hypothesis.lower()
        assert "retry" in hypothesis.lower()

    def test_generic_error_hypothesis(self, engine):
        """Test hypothesis for unknown error types."""
        error_info = {"type": "CustomError", "message": "Something went wrong"}
        cycle = engine.begin_cycle("agent1", error_info)
        hypothesis = engine.generate_hypothesis(cycle)

        assert len(hypothesis) > 0
        assert "CustomError" in hypothesis or "Unknown" in hypothesis


class TestRestructure:
    """Test restructure approach generation."""

    def test_restructure_backoff_approach(self, engine):
        """Test restructure for backoff strategy."""
        error_info = {"type": "TimeoutError", "message": "timeout"}
        cycle = engine.begin_cycle("agent1", error_info)
        hypothesis = engine.generate_hypothesis(cycle)
        approach = engine.restructure(cycle, hypothesis=hypothesis)

        # Timeout hypothesis includes "retry with backoff" which triggers backoff restructure
        assert "backoff" in approach.lower() or "review" in approach.lower()
        assert cycle.restructured_approach == approach

    def test_restructure_reduces_context(self, engine):
        """Test restructure for memory reduction."""
        error_info = {"type": "MemoryError", "message": "memory"}
        cycle = engine.begin_cycle("agent1", error_info)
        engine.generate_hypothesis(cycle)
        approach = engine.restructure(cycle)

        assert "reduce" in approach.lower() or "context" in approach.lower()

    def test_restructure_escalation_approach(self, engine):
        """Test restructure for permission escalation."""
        error_info = {"type": "PermissionError", "message": "permission"}
        cycle = engine.begin_cycle("agent1", error_info)
        engine.generate_hypothesis(cycle)
        approach = engine.restructure(cycle)

        assert "escalate" in approach.lower()

    def test_restructure_with_provided_hypothesis(self, engine):
        """Test restructure using provided hypothesis."""
        error_info = {"type": "Error", "message": "error"}
        cycle = engine.begin_cycle("agent1", error_info)
        custom_hypothesis = "Retry with exponential backoff"
        approach = engine.restructure(cycle, hypothesis=custom_hypothesis)

        assert len(approach) > 0
        assert cycle.restructured_approach == approach


class TestRetry:
    """Test retry attempt execution."""

    def test_attempt_retry_success(self, engine):
        """Test successful retry."""
        error_info = {"type": "Error", "message": "error"}
        cycle = engine.begin_cycle("agent1", error_info)
        engine.generate_hypothesis(cycle)
        engine.restructure(cycle)

        def success_fn():
            return (True, "Success result")

        result = engine.attempt_retry(cycle, success_fn)
        assert result is True
        assert cycle.retry_count == 1
        assert cycle.result == "Success result"

    def test_attempt_retry_failure(self, engine):
        """Test failed retry."""
        error_info = {"type": "Error", "message": "error"}
        cycle = engine.begin_cycle("agent1", error_info)
        engine.generate_hypothesis(cycle)
        engine.restructure(cycle)

        def failure_fn():
            return (False, "Failed result")

        result = engine.attempt_retry(cycle, failure_fn)
        assert result is False
        assert cycle.retry_count == 1

    def test_attempt_retry_exception(self, engine):
        """Test retry with exception."""
        error_info = {"type": "Error", "message": "error"}
        cycle = engine.begin_cycle("agent1", error_info)
        engine.generate_hypothesis(cycle)
        engine.restructure(cycle)

        def error_fn():
            raise ValueError("Execution error")

        result = engine.attempt_retry(cycle, error_fn)
        assert result is False
        assert cycle.retry_count == 1

    def test_attempt_retry_respects_max_retries(self, engine):
        """Test that max_retries limit is enforced."""
        error_info = {"type": "Error", "message": "error"}
        cycle = engine.begin_cycle("agent1", error_info)
        cycle.max_retries = 1
        engine.generate_hypothesis(cycle)
        engine.restructure(cycle)

        def failure_fn():
            return (False, "Failed")

        # First retry
        engine.attempt_retry(cycle, failure_fn)
        assert cycle.retry_count == 1

        # Second retry should be rejected
        result = engine.attempt_retry(cycle, failure_fn)
        assert result is False
        assert cycle.retry_count == 1  # Should not increment


class TestOutcomeRecording:
    """Test outcome recording and learning."""

    def test_record_outcome_success(self, engine):
        """Test recording successful outcome."""
        error_info = {"type": "Error", "message": "error"}
        cycle = engine.begin_cycle("agent1", error_info)
        cycle.retry_count = 2

        engine.record_outcome(cycle, success=True, result="Final result")

        assert cycle.status == ReflexionStatus.SUCCEEDED
        assert cycle.resolved_at is not None
        assert cycle.result == "Final result"

    def test_record_outcome_failure(self, engine):
        """Test recording failed outcome."""
        error_info = {"type": "Error", "message": "error"}
        cycle = engine.begin_cycle("agent1", error_info)

        engine.record_outcome(cycle, success=False)

        assert cycle.status == ReflexionStatus.FAILED
        assert cycle.resolved_at is not None

    def test_record_outcome_persists_to_db(self, engine, temp_db):
        """Test that outcomes are persisted to database."""
        error_info = {"type": "Error", "message": "test error"}
        cycle = engine.begin_cycle("test_agent", error_info)
        cycle.hypothesis = "Test hypothesis"
        cycle.restructured_approach = "Test approach"
        cycle.retry_count = 1

        engine.record_outcome(cycle, success=True)

        # Query the database to verify persistence
        history = engine.get_history("test_agent", limit=1)
        assert len(history) > 0
        assert history[0].id == cycle.id
        assert history[0].status == ReflexionStatus.SUCCEEDED


class TestCycleTracking:
    """Test active cycle and history tracking."""

    def test_get_active_cycles(self, engine):
        """Test retrieving active cycles."""
        error1 = {"type": "Error", "message": "error1"}
        error2 = {"type": "Error", "message": "error2"}

        cycle1 = engine.begin_cycle("agent1", error1)
        cycle2 = engine.begin_cycle("agent2", error2)

        active = engine.get_active_cycles()
        assert len(active) == 2
        assert cycle1 in active
        assert cycle2 in active

    def test_get_active_cycles_excludes_resolved(self, engine):
        """Test that resolved cycles are excluded from active list."""
        error = {"type": "Error", "message": "error"}
        cycle = engine.begin_cycle("agent1", error)

        # Resolve the cycle
        engine.record_outcome(cycle, success=True)

        active = engine.get_active_cycles()
        # The cycle is still in _active_cycles dict but excluded by status check
        assert cycle not in active or cycle.status == ReflexionStatus.ATTEMPTING

    def test_get_history(self, engine):
        """Test retrieving cycle history."""
        for i in range(3):
            error = {"type": "Error", "message": f"error{i}"}
            cycle = engine.begin_cycle("agent1", error)
            engine.record_outcome(cycle, success=(i % 2 == 0))

        history = engine.get_history("agent1", limit=50)
        assert len(history) >= 3

    def test_get_history_filters_by_agent(self, engine):
        """Test that history is filtered by agent name."""
        error = {"type": "Error", "message": "error"}
        cycle1 = engine.begin_cycle("agent1", error)
        cycle2 = engine.begin_cycle("agent2", error)

        engine.record_outcome(cycle1, success=True)
        engine.record_outcome(cycle2, success=False)

        history1 = engine.get_history("agent1", limit=50)
        history2 = engine.get_history("agent2", limit=50)

        assert all(c.agent == "agent1" for c in history1)
        assert all(c.agent == "agent2" for c in history2)

    def test_get_history_respects_limit(self, engine):
        """Test that history respects limit parameter."""
        for i in range(10):
            error = {"type": "Error", "message": f"error{i}"}
            cycle = engine.begin_cycle("agent1", error)
            engine.record_outcome(cycle, success=True)

        history = engine.get_history("agent1", limit=5)
        assert len(history) <= 5


class TestPersistence:
    """Test SQLite persistence and recovery."""

    def test_cycles_persist_to_database(self, temp_db):
        """Test that cycles are persisted to SQLite."""
        engine1 = ReflexionEngine(db_path=temp_db)
        error = {"type": "Error", "message": "test"}
        cycle = engine1.begin_cycle("agent1", error)
        cycle.hypothesis = "Test hypothesis"
        engine1.record_outcome(cycle, success=True)

        # Create new engine with same database
        engine2 = ReflexionEngine(db_path=temp_db)
        history = engine2.get_history("agent1", limit=10)

        assert len(history) > 0
        assert history[0].hypothesis == "Test hypothesis"

    def test_error_json_serialization(self, temp_db):
        """Test that complex error dicts are serialized correctly."""
        engine = ReflexionEngine(db_path=temp_db)
        error_info = {
            "type": "TimeoutError",
            "message": "Request timed out",
            "traceback": "line1\nline2\nline3",
        }
        cycle = engine.begin_cycle("agent1", error_info)
        engine.record_outcome(cycle, success=False)

        history = engine.get_history("agent1", limit=1)
        assert history[0].error == error_info

    def test_multiple_cycles_stored(self, temp_db):
        """Test that multiple cycles are stored independently."""
        engine = ReflexionEngine(db_path=temp_db)

        for i in range(5):
            error = {"type": "Error", "message": f"error{i}"}
            cycle = engine.begin_cycle("agent1", error)
            engine.record_outcome(cycle, success=(i % 2 == 0))

        history = engine.get_history("agent1", limit=50)
        assert len(history) == 5

        # Verify all have different IDs
        ids = [c.id for c in history]
        assert len(set(ids)) == 5
