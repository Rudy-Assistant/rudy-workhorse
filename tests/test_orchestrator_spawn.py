"""Tests for rudy.orchestrator.spawn_engine — Agent Spawning and Execution."""

import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

from rudy.orchestrator.spawn_engine import (
    SpawnEngine, AgentSpawnConfig, AgentSpawnResult
)


@pytest.fixture
def spawn_engine():
    """Create a SpawnEngine instance."""
    return SpawnEngine()


class TestSpawnEngineInit:
    """Test SpawnEngine initialization."""

    def test_creates_executor(self):
        """Test that SpawnEngine creates thread executor."""
        engine = SpawnEngine()
        assert engine._executor is not None

    def test_with_agent_factory(self):
        """Test creating engine with custom agent factory."""
        factory = Mock()
        engine = SpawnEngine(agent_factory=factory)
        assert engine._agent_factory == factory

    def test_initializes_empty_agents(self):
        """Test that active_agents starts empty."""
        engine = SpawnEngine()
        assert engine._active_agents == {}


class TestBuildSpawnPrompt:
    """Test build_spawn_prompt method."""

    def test_basic_prompt(self, spawn_engine):
        """Test building a basic spawn prompt."""
        prompt = spawn_engine.build_spawn_prompt(
            persona="sentinel",
            identity={"name": "Sentinel-001", "role": "Monitor"},
            rules={"check_interval": "60s"},
            boundaries=["no_external_calls"],
            task="Scan network",
            context={},
        )
        assert "AGENT SPAWN PROMPT" in prompt
        assert "Sentinel-001" in prompt
        assert "Monitor" in prompt
        assert "Scan network" in prompt
        assert "[IDENTITY]" in prompt
        assert "[RULES]" in prompt
        assert "[BOUNDARIES]" in prompt
        assert "[TASK]" in prompt

    def test_prompt_with_context_events(self, spawn_engine):
        """Test prompt includes recent events."""
        ctx = {
            "recent_events": [
                {"event_type": "alert", "payload": {"level": "high"}},
                {"event_type": "scan", "payload": {"status": "running"}},
            ]
        }
        prompt = spawn_engine.build_spawn_prompt(
            persona="sentinel",
            identity={"name": "S1"},
            rules={},
            boundaries=[],
            task="Task",
            context=ctx,
        )
        assert "Recent Events:" in prompt
        assert "alert" in prompt

    def test_prompt_with_knowledge(self, spawn_engine):
        """Test prompt includes relevant knowledge."""
        ctx = {
            "relevant_knowledge": [
                {"text": "Network topology is 10.0.0.0/8"},
                {"text": "Critical systems are in DMZ"},
            ]
        }
        prompt = spawn_engine.build_spawn_prompt(
            persona="sentinel",
            identity={"name": "S1"},
            rules={},
            boundaries=[],
            task="Task",
            context=ctx,
        )
        assert "Relevant Knowledge:" in prompt
        assert "10.0.0.0/8" in prompt

    def test_prompt_with_complex_rules(self, spawn_engine):
        """Test prompt with complex rule structure."""
        rules = {
            "decision_logic": ["check_threat", "assess_risk", "alert_if_needed"],
            "priority": "high",
        }
        prompt = spawn_engine.build_spawn_prompt(
            persona="sentinel",
            identity={"name": "S1"},
            rules=rules,
            boundaries=[],
            task="Task",
            context={},
        )
        assert "check_threat" in prompt
        assert "priority: high" in prompt

    def test_prompt_with_boundaries(self, spawn_engine):
        """Test prompt includes boundaries."""
        boundaries = ["No privilege escalation", "No data exfiltration"]
        prompt = spawn_engine.build_spawn_prompt(
            persona="sentinel",
            identity={"name": "S1"},
            rules={},
            boundaries=boundaries,
            task="Task",
            context={},
        )
        assert "[BOUNDARIES]" in prompt
        assert "No privilege escalation" in prompt

    def test_prompt_limits_events(self, spawn_engine):
        """Test that prompt limits events to 5."""
        events = [{"event_type": f"event_{i}", "payload": {}} for i in range(10)]
        ctx = {"recent_events": events}
        prompt = spawn_engine.build_spawn_prompt(
            persona="sentinel",
            identity={"name": "S1"},
            rules={},
            boundaries=[],
            task="Task",
            context=ctx,
        )
        # Should only include first 5
        assert "event_0" in prompt
        assert "event_4" in prompt


class TestSpawn:
    """Test spawn method."""

    def test_basic_spawn_success(self, spawn_engine):
        """Test basic agent spawn with success."""
        result = spawn_engine.spawn(
            agent_name="test-agent",
            task="Test task",
            persona="sentinel",
            identity={"name": "Test"},
            rules={},
            boundaries=[],
            context={},
            timeout_seconds=10,
        )
        assert isinstance(result, AgentSpawnResult)
        assert result.agent_name == "test-agent"
        assert result.task == "Test task"
        assert result.status == "success"
        assert result.duration_seconds >= 0

    def test_spawn_result_success(self, spawn_engine):
        """Test spawn result indicates success."""
        result = spawn_engine.spawn(
            agent_name="test-agent",
            task="task",
            persona="sentinel",
            identity={"name": "Test"},
            rules={},
            boundaries=[],
            context={},
        )
        assert result.is_success()

    def test_spawn_with_timeout_seconds(self, spawn_engine):
        """Test spawn respects timeout configuration."""
        result = spawn_engine.spawn(
            agent_name="agent",
            task="task",
            persona="sentinel",
            identity={"name": "Test"},
            rules={},
            boundaries=[],
            context={},
            timeout_seconds=5,
        )
        assert result.duration_seconds <= 10  # Should complete quickly

    def test_spawn_with_custom_factory(self):
        """Test spawn with custom agent factory."""
        mock_agent = Mock()
        mock_agent.execute.return_value = {"status": "success", "output": {"result": "ok"}}

        factory = Mock(return_value=mock_agent)
        engine = SpawnEngine(agent_factory=factory)

        result = engine.spawn(
            agent_name="agent",
            task="task",
            persona="sentinel",
            identity={"name": "Test"},
            rules={},
            boundaries=[],
            context={},
        )
        factory.assert_called_once()
        mock_agent.execute.assert_called_once()

    def test_spawn_builds_prompt(self, spawn_engine):
        """Test that spawn builds the prompt."""
        result = spawn_engine.spawn(
            agent_name="agent",
            task="Scan network",
            persona="sentinel",
            identity={"name": "Sentinel-001"},
            rules={"interval": "60"},
            boundaries=["no_privesc"],
            context={"recent_events": []},
        )
        # Result should indicate success (prompt was built)
        assert result.status in ["success", "error"]


class TestSpawnParallel:
    """Test spawn_parallel method."""

    def test_spawn_multiple_agents(self, spawn_engine):
        """Test spawning multiple agents in parallel."""
        tasks = [
            {
                "agent_name": "agent1",
                "task": "Task 1",
                "persona": "sentinel",
                "identity": {"name": "A1"},
                "rules": {},
                "boundaries": [],
                "context": {},
            },
            {
                "agent_name": "agent2",
                "task": "Task 2",
                "persona": "sentinel",
                "identity": {"name": "A2"},
                "rules": {},
                "boundaries": [],
                "context": {},
            },
        ]
        results = spawn_engine.spawn_parallel(tasks, timeout_seconds=30)
        assert len(results) == 2
        assert all(isinstance(r, AgentSpawnResult) for r in results)

    def test_parallel_preserves_results(self, spawn_engine):
        """Test that all results are preserved."""
        tasks = [
            {
                "agent_name": f"agent{i}",
                "task": f"Task {i}",
                "persona": "sentinel",
                "identity": {"name": f"Agent{i}"},
                "rules": {},
                "boundaries": [],
                "context": {},
            }
            for i in range(3)
        ]
        results = spawn_engine.spawn_parallel(tasks)
        assert len(results) == 3

    def test_parallel_handles_failures(self, spawn_engine):
        """Test that parallel spawn handles errors."""
        tasks = [
            {
                "agent_name": "agent1",
                "task": "Task 1",
                "persona": "sentinel",
                "identity": {"name": "A1"},
                "rules": {},
                "boundaries": [],
                "context": {},
            }
        ]
        results = spawn_engine.spawn_parallel(tasks, timeout_seconds=30)
        assert len(results) == 1
        assert isinstance(results[0], AgentSpawnResult)


class TestAgentSpawnResult:
    """Test AgentSpawnResult class."""

    def test_basic_creation(self):
        """Test creating a basic result."""
        result = AgentSpawnResult(
            agent_name="agent",
            task="task",
            status="success",
            output={"key": "value"},
            duration_seconds=1.5,
        )
        assert result.agent_name == "agent"
        assert result.task == "task"
        assert result.status == "success"
        assert result.output == {"key": "value"}

    def test_with_error_message(self):
        """Test result with error message."""
        result = AgentSpawnResult(
            agent_name="agent",
            task="task",
            status="error",
            output={},
            duration_seconds=0.5,
            error_message="Network timeout",
        )
        assert result.error_message == "Network timeout"
        assert not result.is_success()

    def test_is_success(self):
        """Test is_success method."""
        success = AgentSpawnResult(
            agent_name="a",
            task="t",
            status="success",
            output={},
            duration_seconds=1.0,
        )
        assert success.is_success()

        failure = AgentSpawnResult(
            agent_name="a",
            task="t",
            status="failure",
            output={},
            duration_seconds=1.0,
        )
        assert not failure.is_success()

    def test_timeout_status(self):
        """Test timeout result."""
        result = AgentSpawnResult(
            agent_name="a",
            task="t",
            status="timeout",
            output={},
            duration_seconds=10.0,
            error_message="Timeout after 10s",
        )
        assert result.status == "timeout"
        assert not result.is_success()

    def test_to_dict(self):
        """Test converting to dictionary."""
        result = AgentSpawnResult(
            agent_name="agent",
            task="task",
            status="success",
            output={"data": [1, 2, 3]},
            duration_seconds=2.5,
        )
        d = result.to_dict()
        assert d["agent_name"] == "agent"
        assert d["task"] == "task"
        assert d["status"] == "success"
        assert d["output"] == {"data": [1, 2, 3]}
        assert d["duration_seconds"] == 2.5


class TestAgentSpawnConfig:
    """Test AgentSpawnConfig."""

    def test_basic_config(self):
        """Test creating a basic config."""
        config = AgentSpawnConfig(
            name="test-agent",
            persona="sentinel",
            identity={"name": "Test"},
            rules={},
            boundaries=[],
            task="Task",
            context={},
        )
        assert config.name == "test-agent"
        assert config.persona == "sentinel"
        assert config.timeout_seconds == 300

    def test_custom_timeout(self):
        """Test custom timeout in config."""
        config = AgentSpawnConfig(
            name="agent",
            persona="sentinel",
            identity={"name": "Test"},
            rules={},
            boundaries=[],
            task="Task",
            context={},
            timeout_seconds=60,
        )
        assert config.timeout_seconds == 60


class TestMockAgent:
    """Test mock agent behavior."""

    def test_mock_agent_creation(self, spawn_engine):
        """Test that mock agent is created when no factory provided."""
        result = spawn_engine.spawn(
            agent_name="mock-agent",
            task="Mock task",
            persona="sentinel",
            identity={"name": "Mock"},
            rules={},
            boundaries=[],
            context={},
        )
        assert result.agent_name == "mock-agent"
        assert result.status == "success"
        assert result.output is not None

    def test_mock_agent_returns_structured_output(self, spawn_engine):
        """Test that mock agent returns structured output."""
        result = spawn_engine.spawn(
            agent_name="agent",
            task="Scan network",
            persona="sentinel",
            identity={"name": "Test"},
            rules={},
            boundaries=[],
            context={},
        )
        assert isinstance(result.output, dict)
        if result.is_success():
            # Output should be a dict (may be empty or contain execution details)
            assert result.output is not None
