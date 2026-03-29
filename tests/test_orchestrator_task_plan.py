"""Tests for rudy.orchestrator.task_plan — Task Plan and Step Management."""

import json
import pytest

from rudy.orchestrator.task_plan import (
    TaskStep, TaskPlan, TaskStatus, RiskLevel
)


class TestTaskStep:
    """Test TaskStep creation and methods."""

    def test_basic_creation(self):
        """Test creating a basic TaskStep."""
        step = TaskStep(
            description="Scan network",
            agent="sentinel",
        )
        assert step.description == "Scan network"
        assert step.agent == "sentinel"
        assert step.status == TaskStatus.PENDING
        assert step.dependencies == []
        assert step.risk_level == RiskLevel.LOW

    def test_with_id_generated(self):
        """Test that step gets unique ID."""
        step1 = TaskStep(description="step1", agent="a")
        step2 = TaskStep(description="step2", agent="b")
        assert step1.id != step2.id
        assert len(step1.id) > 0

    def test_with_dependencies(self):
        """Test step with dependencies."""
        step = TaskStep(
            description="Analyze ports",
            agent="sentinel",
            dependencies=["step-1", "step-2"],
        )
        assert step.dependencies == ["step-1", "step-2"]

    def test_with_risk_level(self):
        """Test step with risk level."""
        step = TaskStep(
            description="task",
            agent="a",
            risk_level=RiskLevel.HIGH,
        )
        assert step.risk_level == RiskLevel.HIGH

    def test_requires_approval(self):
        """Test approval requirement."""
        step = TaskStep(
            description="task",
            agent="a",
            requires_approval=True,
        )
        assert step.requires_approval is True

    def test_mark_running(self):
        """Test marking step as running."""
        step = TaskStep(description="task", agent="a")
        step.mark_running()
        assert step.status == TaskStatus.RUNNING
        assert step.started_at is not None

    def test_mark_completed(self):
        """Test marking step as completed."""
        step = TaskStep(description="task", agent="a")
        result = {"success": True, "data": [1, 2, 3]}
        step.mark_completed(result)
        assert step.status == TaskStatus.COMPLETED
        assert step.completed_at is not None
        assert step.result == result

    def test_mark_failed(self):
        """Test marking step as failed."""
        step = TaskStep(description="task", agent="a")
        step.mark_failed("Network timeout")
        assert step.status == TaskStatus.FAILED
        assert step.completed_at is not None
        assert step.error_message == "Network timeout"

    def test_mark_skipped(self):
        """Test marking step as skipped."""
        step = TaskStep(description="task", agent="a")
        step.mark_skipped()
        assert step.status == TaskStatus.SKIPPED
        assert step.completed_at is not None

    def test_is_ready_no_dependencies(self):
        """Test is_ready with no dependencies."""
        step = TaskStep(description="task", agent="a")
        assert step.is_ready(set())

    def test_is_ready_with_satisfied_dependencies(self):
        """Test is_ready with all dependencies completed."""
        step = TaskStep(
            description="task",
            agent="a",
            dependencies=["dep1", "dep2"],
        )
        completed = {"dep1", "dep2"}
        assert step.is_ready(completed)

    def test_is_ready_with_unsatisfied_dependencies(self):
        """Test is_ready returns False with unsatisfied deps."""
        step = TaskStep(
            description="task",
            agent="a",
            dependencies=["dep1", "dep2"],
        )
        completed = {"dep1"}  # Missing dep2
        assert not step.is_ready(completed)

    def test_is_ready_returns_false_when_not_pending(self):
        """Test is_ready returns False when status is not PENDING."""
        step = TaskStep(description="task", agent="a")
        step.mark_completed({"ok": True})
        assert not step.is_ready(set())

    def test_duration_seconds(self):
        """Test duration_seconds calculation."""
        step = TaskStep(description="task", agent="a")
        step.mark_running()
        step.mark_completed({"ok": True})
        duration = step.duration_seconds()
        assert duration is not None
        assert duration >= 0

    def test_duration_seconds_not_started(self):
        """Test duration_seconds when step not started."""
        step = TaskStep(description="task", agent="a")
        assert step.duration_seconds() is None

    def test_to_dict(self):
        """Test converting to dictionary."""
        step = TaskStep(
            description="scan",
            agent="sentinel",
            risk_level=RiskLevel.MEDIUM,
        )
        d = step.to_dict()
        assert d["description"] == "scan"
        assert d["agent"] == "sentinel"
        assert d["status"] == "pending"
        assert d["risk_level"] == "medium"


class TestTaskPlan:
    """Test TaskPlan creation and methods."""

    def test_basic_creation(self):
        """Test creating a basic TaskPlan."""
        plan = TaskPlan(intent="Scan network for threats")
        assert plan.intent == "Scan network for threats"
        assert plan.steps == []
        assert plan.status == "pending"
        assert len(plan.id) > 0

    def test_add_step(self):
        """Test adding a step to plan."""
        plan = TaskPlan(intent="test")
        step = plan.add_step(
            description="Step 1",
            agent="sentinel",
        )
        assert len(plan.steps) == 1
        assert step.description == "Step 1"
        assert step.agent == "sentinel"

    def test_add_multiple_steps(self):
        """Test adding multiple steps."""
        plan = TaskPlan(intent="test")
        step1 = plan.add_step("Step 1", "sentinel")
        step2 = plan.add_step("Step 2", "sentinel")
        assert len(plan.steps) == 2
        assert plan.steps[0].id == step1.id
        assert plan.steps[1].id == step2.id

    def test_add_step_with_dependencies(self):
        """Test adding step with dependencies."""
        plan = TaskPlan(intent="test")
        step1 = plan.add_step("Step 1", "sentinel")
        step2 = plan.add_step("Step 2", "sentinel", dependencies=[step1.id])
        assert step2.dependencies == [step1.id]

    def test_add_step_with_risk_and_approval(self):
        """Test adding step with risk level and approval."""
        plan = TaskPlan(intent="test")
        step = plan.add_step(
            description="High-risk task",
            agent="sentinel",
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
        )
        assert step.risk_level == RiskLevel.HIGH
        assert step.requires_approval is True

    def test_add_step_with_metadata(self):
        """Test adding step with metadata."""
        plan = TaskPlan(intent="test")
        meta = {"retry": 3, "timeout": 300}
        step = plan.add_step(
            description="task",
            agent="sentinel",
            metadata=meta,
        )
        assert step.metadata == meta

    def test_get_step(self):
        """Test getting a step by ID."""
        plan = TaskPlan(intent="test")
        step1 = plan.add_step("Step 1", "sentinel")
        step2 = plan.add_step("Step 2", "sentinel")
        retrieved = plan.get_step(step1.id)
        assert retrieved.id == step1.id
        assert retrieved.description == "Step 1"

    def test_get_step_not_found(self):
        """Test get_step returns None for unknown ID."""
        plan = TaskPlan(intent="test")
        plan.add_step("Step", "sentinel")
        assert plan.get_step("unknown-id") is None

    def test_get_ready_steps_no_dependencies(self):
        """Test get_ready_steps with no dependencies."""
        plan = TaskPlan(intent="test")
        plan.add_step("Step 1", "sentinel")
        plan.add_step("Step 2", "sentinel")
        ready = plan.get_ready_steps()
        assert len(ready) == 2

    def test_get_ready_steps_with_dependencies(self):
        """Test get_ready_steps respects dependencies."""
        plan = TaskPlan(intent="test")
        step1 = plan.add_step("Step 1", "sentinel")
        step2 = plan.add_step("Step 2", "sentinel", dependencies=[step1.id])

        # Initially both pending, only step1 is ready
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == step1.id

        # After completing step1, step2 becomes ready
        step1.mark_completed({"ok": True})
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == step2.id

    def test_get_ready_steps_excludes_non_pending(self):
        """Test get_ready_steps excludes non-pending steps."""
        plan = TaskPlan(intent="test")
        step1 = plan.add_step("Step 1", "sentinel")
        step2 = plan.add_step("Step 2", "sentinel")
        step1.mark_completed({"ok": True})
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == step2.id

    def test_mark_step_completed(self):
        """Test marking a step as completed via plan."""
        plan = TaskPlan(intent="test")
        step = plan.add_step("task", "sentinel")
        plan.mark_step_completed(step.id, {"result": "ok"})
        assert step.status == TaskStatus.COMPLETED
        assert step.result == {"result": "ok"}

    def test_mark_step_failed(self):
        """Test marking a step as failed via plan."""
        plan = TaskPlan(intent="test")
        step = plan.add_step("task", "sentinel")
        plan.mark_step_failed(step.id, "Network error")
        assert step.status == TaskStatus.FAILED
        assert step.error_message == "Network error"

    def test_get_progress(self):
        """Test get_progress method."""
        plan = TaskPlan(intent="test")
        step1 = plan.add_step("Step 1", "sentinel")
        step2 = plan.add_step("Step 2", "sentinel")
        step3 = plan.add_step("Step 3", "sentinel")

        progress = plan.get_progress()
        assert progress["pending"] == 3
        assert progress["completed"] == 0
        assert progress["total"] == 3

        step1.mark_completed({"ok": True})
        progress = plan.get_progress()
        assert progress["pending"] == 2
        assert progress["completed"] == 1

        step2.mark_failed("error")
        progress = plan.get_progress()
        assert progress["pending"] == 1
        assert progress["completed"] == 1
        assert progress["failed"] == 1

    def test_phases_completed(self):
        """Test phases_completed tracking."""
        plan = TaskPlan(intent="test", phases_completed=["Planning"])
        assert "Planning" in plan.phases_completed
        plan.phases_completed.append("Setup")
        assert len(plan.phases_completed) == 2

    def test_to_dict(self):
        """Test converting to dictionary."""
        plan = TaskPlan(intent="test intent")
        step = plan.add_step("Step 1", "sentinel", risk_level=RiskLevel.HIGH)
        d = plan.to_dict()
        assert d["intent"] == "test intent"
        assert d["status"] == "pending"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["description"] == "Step 1"

    def test_to_json(self):
        """Test JSON serialization."""
        plan = TaskPlan(intent="test")
        plan.add_step("Step", "sentinel")
        json_str = plan.to_json()
        parsed = json.loads(json_str)
        assert parsed["intent"] == "test"
        assert len(parsed["steps"]) == 1

    def test_duration_seconds(self):
        """Test plan duration calculation."""
        plan = TaskPlan(intent="test")
        step1 = plan.add_step("Step 1", "sentinel")
        step2 = plan.add_step("Step 2", "sentinel")

        step1.mark_running()
        step2.mark_running()
        step1.mark_completed({"ok": True})
        step2.mark_completed({"ok": True})

        duration = plan.duration_seconds()
        assert duration is not None
        assert duration >= 0

    def test_duration_seconds_no_steps_started(self):
        """Test duration_seconds when no steps started."""
        plan = TaskPlan(intent="test")
        plan.add_step("Step", "sentinel")
        assert plan.duration_seconds() is None

    def test_complex_dependency_chain(self):
        """Test complex dependency chain."""
        plan = TaskPlan(intent="test")
        s1 = plan.add_step("Step 1", "sentinel")
        s2 = plan.add_step("Step 2", "sentinel", dependencies=[s1.id])
        s3 = plan.add_step("Step 3", "sentinel", dependencies=[s2.id])

        # Only s1 should be ready
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == s1.id

        # Complete s1, s2 becomes ready
        s1.mark_completed({})
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == s2.id

        # Complete s2, s3 becomes ready
        s2.mark_completed({})
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == s3.id

    def test_parallel_steps(self):
        """Test parallel steps (same dependency, independent)."""
        plan = TaskPlan(intent="test")
        s1 = plan.add_step("Step 1", "sentinel")
        s2 = plan.add_step("Step 2", "sentinel", dependencies=[s1.id])
        s3 = plan.add_step("Step 3", "sentinel", dependencies=[s1.id])

        # s2 and s3 can run in parallel after s1
        s1.mark_completed({})
        ready = plan.get_ready_steps()
        ready_ids = {s.id for s in ready}
        assert s2.id in ready_ids
        assert s3.id in ready_ids
