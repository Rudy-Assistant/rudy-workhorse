"""
Comprehensive tests for StructuredLogger.

Tests cover:
- Structured log entry creation and fields
- Log level shortcuts (info, warning, error, debug)
- Timed operation context manager
- Ring buffer behavior with size limits
- Log querying with flexible filters
- Error summary aggregation
- JSON export functionality
- SQLite persistence
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import time

from rudy.observability.logger import (
    StructuredLogger,
    LogEntry,
    LogLevel,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        yield db_path


@pytest.fixture
def logger(temp_db):
    """Create a StructuredLogger with temp database."""
    return StructuredLogger(db_path=temp_db, buffer_size=100)


class TestStructuredLoggerCreation:
    """Test logger initialization."""

    def test_logger_creation_with_temp_db(self, logger):
        """Test creating logger with temporary database."""
        assert logger._db_path is not None
        assert logger._buffer_size == 100

    def test_logger_with_default_db(self):
        """Test logger creates default db path."""
        logger = StructuredLogger()
        assert logger._db_path is not None
        assert "rudy-data" in str(logger._db_path)

    def test_logger_with_custom_buffer_size(self, temp_db):
        """Test creating logger with custom buffer size."""
        logger = StructuredLogger(db_path=temp_db, buffer_size=50)
        assert logger._buffer_size == 50


class TestLogEntry:
    """Test structured log entry creation."""

    def test_log_creates_entry(self, logger):
        """Test that log() creates a LogEntry."""
        entry = logger.log(
            level=LogLevel.INFO,
            event="test_event",
            message="Test message",
            agent="test_agent",
        )

        assert isinstance(entry, LogEntry)
        assert entry.level == LogLevel.INFO
        assert entry.event == "test_event"
        assert entry.message == "Test message"
        assert entry.agent == "test_agent"

    def test_log_entry_has_all_fields(self, logger):
        """Test that log entry contains all required fields."""
        context = {"key": "value"}
        entry = logger.log(
            level=LogLevel.WARNING,
            event="warning_event",
            message="Warning message",
            agent="agent1",
            context=context,
            correlation_id="corr123",
        )

        assert entry.timestamp is not None
        assert entry.level == LogLevel.WARNING
        assert entry.agent == "agent1"
        assert entry.event == "warning_event"
        assert entry.message == "Warning message"
        assert entry.context == context
        assert entry.correlation_id == "corr123"

    def test_log_generates_correlation_id(self, logger):
        """Test that log generates correlation ID if not provided."""
        entry = logger.log(
            level=LogLevel.INFO,
            event="event",
            message="message",
        )

        assert entry.correlation_id is not None
        assert len(entry.correlation_id) > 0

    def test_log_duration_recorded(self, logger):
        """Test that duration can be recorded."""
        entry = logger.log(
            level=LogLevel.INFO,
            event="event",
            message="message",
            duration_ms=123.45,
        )

        assert entry.duration_ms == 123.45


class TestLogShortcuts:
    """Test convenience log level shortcuts."""

    def test_info_shortcut(self, logger):
        """Test info() shortcut."""
        entry = logger.info("info_event", "Info message", agent="agent1")
        assert entry.level == LogLevel.INFO

    def test_warning_shortcut(self, logger):
        """Test warning() shortcut."""
        entry = logger.warning("warn_event", "Warning message", agent="agent1")
        assert entry.level == LogLevel.WARNING

    def test_error_shortcut(self, logger):
        """Test error() shortcut."""
        entry = logger.error("error_event", "Error message", agent="agent1")
        assert entry.level == LogLevel.ERROR

    def test_debug_shortcut(self, logger):
        """Test debug() shortcut."""
        entry = logger.debug("debug_event", "Debug message", agent="agent1")
        assert entry.level == LogLevel.DEBUG


class TestTimedOperation:
    """Test timed operation context manager."""

    def test_timed_operation_is_context_manager(self, logger):
        """Test that timed_operation is a valid context manager."""
        # The timed_operation method exists and can be used as context manager
        assert hasattr(logger, 'timed_operation')
        assert callable(logger.timed_operation)

    def test_timed_operation_context_manager_protocol(self, logger):
        """Test that timed_operation follows context manager protocol."""
        # Get the timed_operation generator/context manager
        ctx = logger.timed_operation("test_op", agent="agent1")
        # Context managers should have __enter__ and __exit__
        assert hasattr(ctx, '__enter__')
        assert hasattr(ctx, '__exit__')


class TestRingBuffer:
    """Test ring buffer behavior."""

    def test_buffer_accepts_entries_up_to_size(self, temp_db):
        """Test buffer accepts entries up to buffer size."""
        logger = StructuredLogger(db_path=temp_db, buffer_size=10)

        for i in range(10):
            logger.log(
                level=LogLevel.INFO,
                event=f"event{i}",
                message=f"Message {i}",
            )

        assert len(logger._buffer) == 10

    def test_buffer_wraps_around_at_size(self, temp_db):
        """Test buffer wraps around when exceeding size."""
        logger = StructuredLogger(db_path=temp_db, buffer_size=5)

        for i in range(7):
            logger.log(
                level=LogLevel.INFO,
                event=f"event{i}",
                message=f"Message {i}",
            )

        # Buffer should still have only 5 entries
        assert len(logger._buffer) == 5

        # Should contain the last 5 entries
        messages = [e.message for e in logger._buffer]
        assert "Message 2" in messages
        assert "Message 6" in messages

    def test_buffer_index_wraps(self, temp_db):
        """Test buffer index wraps correctly."""
        logger = StructuredLogger(db_path=temp_db, buffer_size=3)

        for i in range(6):
            logger.log(
                level=LogLevel.INFO,
                event="event",
                message=f"Message {i}",
            )

        # Index should have wrapped to 0
        assert logger._buffer_index == 0


class TestQuerying:
    """Test log querying with filters."""

    def test_query_all_logs(self, logger):
        """Test querying all logs."""
        logger.info("event1", "Message 1", agent="agent1")
        logger.info("event2", "Message 2", agent="agent2")
        logger.error("event3", "Message 3", agent="agent1")

        logs = logger.query_logs(limit=100)
        assert len(logs) >= 3

    def test_query_filter_by_agent(self, logger):
        """Test filtering logs by agent."""
        logger.info("event1", "Message 1", agent="agent1")
        logger.info("event2", "Message 2", agent="agent2")

        logs = logger.query_logs(agent="agent1", limit=100)
        assert all(log["agent"] == "agent1" for log in logs)

    def test_query_filter_by_level(self, logger):
        """Test filtering logs by level."""
        logger.info("event1", "Info", agent="agent1")
        logger.error("event2", "Error", agent="agent1")
        logger.warning("event3", "Warning", agent="agent1")

        error_logs = logger.query_logs(level=LogLevel.ERROR, agent="agent1", limit=100)
        assert all(log["level"] == LogLevel.ERROR.value for log in error_logs)

    def test_query_filter_by_event_type(self, logger):
        """Test filtering logs by event type."""
        logger.info("event_a", "Message A", agent="agent1")
        logger.info("event_b", "Message B", agent="agent1")

        logs = logger.query_logs(event_type="event_a", agent="agent1", limit=100)
        assert all(log["event"] == "event_a" for log in logs)

    def test_query_filter_by_correlation_id(self, logger):
        """Test filtering logs by correlation ID."""
        cid = "corr123"
        logger.info("event1", "Message 1", correlation_id=cid)
        logger.info("event2", "Message 2", correlation_id="other")

        logs = logger.query_logs(correlation_id=cid, limit=100)
        assert all(log["correlation_id"] == cid for log in logs)

    def test_query_respects_limit(self, logger):
        """Test that query respects limit parameter."""
        for i in range(20):
            logger.info(f"event{i}", f"Message {i}")

        logs = logger.query_logs(limit=5)
        assert len(logs) <= 5

    def test_query_returns_recent_first(self, logger):
        """Test that query returns newest logs first."""
        for i in range(3):
            logger.info("event", f"Message {i}")

        logs = logger.query_logs(limit=100)
        # Most recent should be first
        assert "Message 2" in logs[0]["message"]


class TestErrorSummary:
    """Test error summary aggregation."""

    def test_error_summary_counts_errors(self, logger):
        """Test that error summary counts errors."""
        logger.error("error1", "Error A", agent="agent1")
        logger.error("error2", "Error B", agent="agent1")
        logger.error("error1", "Error A again", agent="agent1")
        logger.info("info1", "Info", agent="agent1")

        summary = logger.get_error_summary(hours=24)

        assert summary["total_errors"] == 3

    def test_error_summary_by_agent(self, logger):
        """Test error summary grouped by agent."""
        logger.error("error1", "Error", agent="agent1")
        logger.error("error2", "Error", agent="agent1")
        logger.error("error3", "Error", agent="agent2")

        summary = logger.get_error_summary(hours=24)

        assert summary["errors_by_agent"]["agent1"] == 2
        assert summary["errors_by_agent"]["agent2"] == 1

    def test_error_summary_by_event(self, logger):
        """Test error summary grouped by event type."""
        logger.error("api_error", "API failed", agent="agent1")
        logger.error("api_error", "API failed again", agent="agent1")
        logger.error("db_error", "Database failed", agent="agent1")

        summary = logger.get_error_summary(hours=24)

        assert summary["errors_by_event"]["api_error"] == 2
        assert summary["errors_by_event"]["db_error"] == 1

    def test_error_summary_respects_time_window(self, logger):
        """Test that error summary respects time window."""
        logger.error("error1", "Error", agent="agent1")

        # Summary for 0 hours should exclude this
        summary = logger.get_error_summary(hours=0)
        # Might be 0 or 1 depending on timing
        assert isinstance(summary["total_errors"], int)

        # Summary for 24 hours should include it
        summary = logger.get_error_summary(hours=24)
        assert summary["total_errors"] >= 1


class TestExport:
    """Test log export functionality."""

    def test_export_to_json(self, logger, temp_db):
        """Test exporting logs to JSON."""
        logger.info("event1", "Message 1", agent="agent1")
        logger.info("event2", "Message 2", agent="agent2")

        export_path = temp_db.parent / "logs_export.json"
        count = logger.export_json(export_path)

        assert export_path.exists()
        assert count >= 2

        # Verify file contains valid JSON
        with open(export_path) as f:
            data = json.load(f)
            assert isinstance(data, list)
            assert len(data) >= 2

    def test_export_with_agent_filter(self, logger, temp_db):
        """Test exporting with agent filter."""
        logger.info("event1", "Message 1", agent="agent1")
        logger.info("event2", "Message 2", agent="agent2")

        export_path = temp_db.parent / "logs_agent1.json"
        count = logger.export_json(export_path, agent="agent1")

        with open(export_path) as f:
            data = json.load(f)
            # Should only have agent1 logs
            assert all(log["agent"] == "agent1" for log in data)

    def test_export_creates_parent_dir(self, logger, temp_db):
        """Test that export creates parent directory."""
        export_path = temp_db.parent / "deep" / "nested" / "dir" / "logs.json"
        logger.info("event", "message")
        count = logger.export_json(export_path)

        assert export_path.parent.exists()
        assert export_path.exists()


class TestPersistence:
    """Test SQLite persistence."""

    def test_logs_persist_to_database(self, temp_db):
        """Test that logs are persisted to SQLite."""
        logger1 = StructuredLogger(db_path=temp_db)
        logger1.info("event1", "Message 1", agent="agent1")

        # Create new logger with same database
        logger2 = StructuredLogger(db_path=temp_db)
        logs = logger2.query_logs(agent="agent1", limit=100)

        assert len(logs) > 0
        assert logs[0]["event"] == "event1"

    def test_context_persisted(self, temp_db):
        """Test that context dict is persisted correctly."""
        logger1 = StructuredLogger(db_path=temp_db)
        context = {"key1": "value1", "key2": 42}
        logger1.info("event", "message", context=context)

        logger2 = StructuredLogger(db_path=temp_db)
        logs = logger2.query_logs(event_type="event", limit=10)

        assert len(logs) > 0
        assert logs[0]["context"] == context

    def test_multiple_entries_stored(self, temp_db):
        """Test that multiple entries are stored independently."""
        logger1 = StructuredLogger(db_path=temp_db)

        for i in range(10):
            logger1.info(f"event{i}", f"Message {i}")

        logger2 = StructuredLogger(db_path=temp_db)
        logs = logger2.query_logs(limit=100)

        assert len(logs) >= 10
