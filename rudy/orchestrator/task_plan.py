"""
Task Plan and Task Step Management

Models for decomposing high-level intents into executable task plans,
with dependency tracking and phase management.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from enum import Enum
import uuid
import json


class TaskStatus(str, Enum):
    """Status of a task step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RiskLevel(str, Enum):
    """Risk classification for approval gating."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TaskStep:
    """A single step within a task plan.

    Attributes:
        id: Unique step identifier
        description: Human-readable description of the step
        agent: Agent name responsible for executing this step
        dependencies: List of step IDs that must complete before this one
        status: Current status (pending/running/completed/failed/skipped)
        result: Result data from execution
        risk_level: Risk classification for approval purposes
        requires_approval: Whether this step needs HITL approval
        created_at: Timestamp when step was created
        started_at: Timestamp when execution started (if any)
        completed_at: Timestamp when execution completed (if any)
        error_message: Error details if step failed
        metadata: Optional arbitrary metadata
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    agent: str = ""
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["status"] = self.status.value
        d["risk_level"] = self.risk_level.value
        return d

    def mark_running(self) -> None:
        """Mark step as currently running."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now().isoformat()

    def mark_completed(self, result: Any) -> None:
        """Mark step as completed with result."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now().isoformat()
        self.result = result

    def mark_failed(self, error: str) -> None:
        """Mark step as failed with error."""
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now().isoformat()
        self.error_message = error

    def mark_skipped(self) -> None:
        """Mark step as skipped."""
        self.status = TaskStatus.SKIPPED
        self.completed_at = datetime.now().isoformat()

    def is_ready(self, completed_steps: Set[str]) -> bool:
        """Check if all dependencies are satisfied.

        Args:
            completed_steps: Set of step IDs that have been completed

        Returns:
            True if all dependencies are in completed_steps
        """
        if self.status != TaskStatus.PENDING:
            return False
        return all(dep_id in completed_steps for dep_id in self.dependencies)

    def duration_seconds(self) -> Optional[float]:
        """Get execution duration if step has completed."""
        if not self.started_at or not self.completed_at:
            return None
        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.completed_at)
            return (end - start).total_seconds()
        except (ValueError, TypeError):
            return None


@dataclass
class TaskPlan:
    """High-level execution plan decomposed from user intent.

    Attributes:
        id: Unique plan identifier
        intent: Original user request/intent
        steps: List of TaskStep objects
        created_at: Timestamp when plan was created
        status: Overall plan status (pending/running/completed/failed/partial)
        current_phase: Current execution phase
        phases_completed: List of phases that completed successfully
        metadata: Optional arbitrary metadata
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    intent: str = ""
    steps: List[TaskStep] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "pending"
    current_phase: Optional[str] = None
    phases_completed: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(
        self,
        description: str,
        agent: str,
        dependencies: Optional[List[str]] = None,
        risk_level: RiskLevel = RiskLevel.LOW,
        requires_approval: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskStep:
        """Add a new step to this plan.

        Args:
            description: Human-readable description
            agent: Agent responsible for execution
            dependencies: List of step IDs that must complete first
            risk_level: Risk classification
            requires_approval: Whether HITL approval is required
            metadata: Optional metadata

        Returns:
            The newly created TaskStep
        """
        step = TaskStep(
            description=description,
            agent=agent,
            dependencies=dependencies or [],
            risk_level=risk_level,
            requires_approval=requires_approval,
            metadata=metadata or {},
        )
        self.steps.append(step)
        return step

    def get_step(self, step_id: str) -> Optional[TaskStep]:
        """Get a step by ID."""
        return next((s for s in self.steps if s.id == step_id), None)

    def get_ready_steps(self) -> List[TaskStep]:
        """Get all steps ready to execute (dependencies satisfied).

        Returns:
            List of TaskStep objects with all dependencies completed
        """
        completed_ids = {
            s.id for s in self.steps
            if s.status == TaskStatus.COMPLETED
        }
        return [s for s in self.steps if s.is_ready(completed_ids)]

    def mark_step_completed(self, step_id: str, result: Any) -> None:
        """Mark a specific step as completed."""
        step = self.get_step(step_id)
        if step:
            step.mark_completed(result)

    def mark_step_failed(self, step_id: str, error: str) -> None:
        """Mark a specific step as failed."""
        step = self.get_step(step_id)
        if step:
            step.mark_failed(error)

    def get_progress(self) -> Dict[str, int]:
        """Get execution progress counts.

        Returns:
            Dict with counts: pending, running, completed, failed, skipped
        """
        return {
            "pending": sum(1 for s in self.steps if s.status == TaskStatus.PENDING),
            "running": sum(1 for s in self.steps if s.status == TaskStatus.RUNNING),
            "completed": sum(1 for s in self.steps if s.status == TaskStatus.COMPLETED),
            "failed": sum(1 for s in self.steps if s.status == TaskStatus.FAILED),
            "skipped": sum(1 for s in self.steps if s.status == TaskStatus.SKIPPED),
            "total": len(self.steps),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with nested steps."""
        d = asdict(self)
        d["steps"] = [s.to_dict() for s in self.steps]
        d["phases_completed"] = self.phases_completed
        return d

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), default=str, indent=2)

    def duration_seconds(self) -> Optional[float]:
        """Get total plan execution duration if completed."""
        if not any(s.started_at for s in self.steps):
            return None

        starts = [
            datetime.fromisoformat(s.started_at)
            for s in self.steps
            if s.started_at
        ]
        ends = [
            datetime.fromisoformat(s.completed_at)
            for s in self.steps
            if s.completed_at
        ]

        if not starts or not ends:
            return None

        try:
            min_start = min(starts)
            max_end = max(ends)
            return (max_end - min_start).total_seconds()
        except (ValueError, TypeError):
            return None
