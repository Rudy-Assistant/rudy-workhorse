"""Tests for rudy.orchestrator.results — Execution Result Types."""

import json
import pytest

from rudy.orchestrator.results import AgentResult, ExecutionResult


class TestAgentResult:
    """Test AgentResult creation and methods."""

    def test_basic_creation(self):
        """Test creating a basic AgentResult."""
        result = AgentResult(
            agent_name="sentinel",
            task="scan network",
            status="success",
            output={"hosts": [1, 2, 3]},
            duration_seconds=5.2,
        )
        assert result.agent_name == "sentinel"
        assert result.task == "scan network"
        assert result.status == "success"
        assert result.duration_seconds == 5.2
        assert result.error_message is None

    def test_with_error_message(self):
        """Test creating a result with error."""
        result = AgentResult(
            agent_name="sentinel",
            task="scan network",
            status="error",
            output={},
            duration_seconds=1.0,
            error_message="Network timeout",
        )
        assert result.error_message == "Network timeout"
        assert not result.is_success()

    def test_with_metadata(self):
        """Test creating a result with metadata."""
        meta = {"retry_count": 3, "timeout": 300}
        result = AgentResult(
            agent_name="sentinel",
            task="task",
            status="success",
            output={},
            duration_seconds=1.0,
            metadata=meta,
        )
        assert result.metadata == meta

    def test_is_success(self):
        """Test is_success() method."""
        success_result = AgentResult(
            agent_name="test",
            task="task",
            status="success",
            output={},
            duration_seconds=1.0,
        )
        assert success_result.is_success()

        failure_result = AgentResult(
            agent_name="test",
            task="task",
            status="failure",
            output={},
            duration_seconds=1.0,
        )
        assert not failure_result.is_success()

    def test_to_dict(self):
        """Test converting to dictionary."""
        result = AgentResult(
            agent_name="sentinel",
            task="scan",
            status="success",
            output={"result": "ok"},
            duration_seconds=2.5,
        )
        d = result.to_dict()
        assert d["agent_name"] == "sentinel"
        assert d["task"] == "scan"
        assert d["status"] == "success"
        assert d["output"] == {"result": "ok"}
        assert d["duration_seconds"] == 2.5


class TestExecutionResult:
    """Test ExecutionResult creation and methods."""

    def test_basic_creation(self):
        """Test creating a basic ExecutionResult."""
        result = ExecutionResult(
            plan_id="plan-123",
            intent="scan network",
            status="completed",
            agent_results=[],
            duration_seconds=10.0,
        )
        assert result.plan_id == "plan-123"
        assert result.intent == "scan network"
        assert result.status == "completed"
        assert result.agent_results == []
        assert result.duration_seconds == 10.0

    def test_add_agent_results(self):
        """Test adding agent results."""
        agent_res1 = AgentResult(
            agent_name="sentinel",
            task="task1",
            status="success",
            output={"data": 1},
            duration_seconds=1.0,
        )
        agent_res2 = AgentResult(
            agent_name="sentinel",
            task="task2",
            status="success",
            output={"data": 2},
            duration_seconds=1.0,
        )

        result = ExecutionResult(
            plan_id="plan-123",
            intent="test",
            status="completed",
            agent_results=[agent_res1, agent_res2],
            duration_seconds=2.0,
        )
        assert len(result.agent_results) == 2
        assert result.success_count == 2
        assert result.failure_count == 0

    def test_success_count(self):
        """Test success_count property."""
        agent_res1 = AgentResult(
            agent_name="a", task="t", status="success", output={}, duration_seconds=1.0
        )
        agent_res2 = AgentResult(
            agent_name="b", task="t", status="failure", output={}, duration_seconds=1.0
        )
        result = ExecutionResult(
            plan_id="p", intent="i", status="partial",
            agent_results=[agent_res1, agent_res2], duration_seconds=2.0
        )
        assert result.success_count == 1
        assert result.failure_count == 1
        assert result.total_steps == 2

    def test_phases_completed(self):
        """Test phases_completed tracking."""
        result = ExecutionResult(
            plan_id="p", intent="i", status="completed",
            agent_results=[], duration_seconds=1.0,
            phases_completed=["Planning", "Setup", "Implementation"],
        )
        assert len(result.phases_completed) == 3
        assert "Planning" in result.phases_completed

    def test_error_context(self):
        """Test error context storage."""
        error_ctx = {"phase": "Setup", "error": "Network unavailable"}
        result = ExecutionResult(
            plan_id="p", intent="i", status="failed",
            agent_results=[], duration_seconds=1.0,
            error_context=error_ctx,
        )
        assert result.error_context == error_ctx
        assert result.current_phase is None

    def test_to_dict(self):
        """Test converting to dictionary."""
        agent_res = AgentResult(
            agent_name="test",
            task="task",
            status="success",
            output={"k": "v"},
            duration_seconds=1.0,
        )
        result = ExecutionResult(
            plan_id="plan-1",
            intent="intent",
            status="completed",
            agent_results=[agent_res],
            duration_seconds=1.0,
        )
        d = result.to_dict()
        assert d["plan_id"] == "plan-1"
        assert d["intent"] == "intent"
        assert d["status"] == "completed"
        assert len(d["agent_results"]) == 1
        assert d["agent_results"][0]["agent_name"] == "test"

    def test_to_json(self):
        """Test JSON serialization."""
        agent_res = AgentResult(
            agent_name="test",
            task="task",
            status="success",
            output={"key": "value"},
            duration_seconds=1.5,
        )
        result = ExecutionResult(
            plan_id="plan-1",
            intent="intent",
            status="completed",
            agent_results=[agent_res],
            duration_seconds=1.5,
        )
        json_str = result.to_json()
        parsed = json.loads(json_str)
        assert parsed["plan_id"] == "plan-1"
        assert len(parsed["agent_results"]) == 1
        assert parsed["agent_results"][0]["task"] == "task"

    def test_total_steps_property(self):
        """Test total_steps property."""
        results = [
            AgentResult("a", "t1", "success", {}, 1.0),
            AgentResult("b", "t2", "failure", {}, 1.0),
            AgentResult("c", "t3", "success", {}, 1.0),
        ]
        exec_result = ExecutionResult(
            plan_id="p", intent="i", status="partial",
            agent_results=results, duration_seconds=3.0
        )
        assert exec_result.total_steps == 3
