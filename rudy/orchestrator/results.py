"""
Execution Result Types

Dataclasses for structured result reporting from agents and complete
plan executions.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, List, Optional
import json


@dataclass
class AgentResult:
    """Result from executing a single agent.

    Attributes:
        agent_name: Name of the agent that executed
        task: Task description or ID that was executed
        status: One of "success", "failure", "timeout", "error"
        output: Agent output / result content
        duration_seconds: Execution time in seconds
        error_message: Error details if status is not "success"
        metadata: Optional arbitrary metadata
    """
    agent_name: str
    task: str
    status: str
    output: Any
    duration_seconds: float
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def is_success(self) -> bool:
        """Check if this result represents a successful execution."""
        return self.status == "success"


@dataclass
class ExecutionResult:
    """Result from executing a complete TaskPlan.

    Attributes:
        plan_id: Unique identifier of the TaskPlan that was executed
        intent: Original user intent or request
        status: One of "completed", "partial", "failed"
        agent_results: List of individual AgentResult objects
        duration_seconds: Total execution time
        phases_completed: List of phase names that completed successfully
        current_phase: Phase that failed (if any)
        error_context: Context information if execution failed
    """
    plan_id: str
    intent: str
    status: str
    agent_results: List[AgentResult]
    duration_seconds: float
    phases_completed: List[str] = field(default_factory=list)
    current_phase: Optional[str] = None
    error_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with nested agent results."""
        d = asdict(self)
        d["agent_results"] = [r.to_dict() for r in self.agent_results]
        return d

    def to_json(self) -> str:
        """Serialize to JSON with default handlers for non-serializable types."""
        return json.dumps(self.to_dict(), default=str, indent=2)

    @property
    def success_count(self) -> int:
        """Count of successful agent executions."""
        return sum(1 for r in self.agent_results if r.is_success())

    @property
    def failure_count(self) -> int:
        """Count of failed agent executions."""
        return sum(1 for r in self.agent_results if not r.is_success())

    @property
    def total_steps(self) -> int:
        """Total number of agents executed."""
        return len(self.agent_results)
