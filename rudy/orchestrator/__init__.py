"""
Oracle Orchestrator — Phase 2 Coordination System

Central orchestration layer for task decomposition, agent spawning,
HITL approval gates, and cross-agent message routing.

Exports:
    - Oracle: The central orchestrator
    - TaskPlan: Task decomposition and execution plan
    - TaskStep: Individual step within a plan
    - HITLGate: Human-in-the-loop approval system
    - ApprovalRequest: Single approval request record
    - SpawnEngine: Agent instantiation and lifecycle
    - AgentResult: Single agent execution result
    - ExecutionResult: Complete plan execution result
"""

from rudy.orchestrator.oracle import Oracle
from rudy.orchestrator.task_plan import TaskPlan, TaskStep
from rudy.orchestrator.hitl import HITLGate, ApprovalRequest
from rudy.orchestrator.spawn_engine import SpawnEngine
from rudy.orchestrator.results import AgentResult, ExecutionResult

__all__ = [
    "Oracle",
    "TaskPlan",
    "TaskStep",
    "HITLGate",
    "ApprovalRequest",
    "SpawnEngine",
    "AgentResult",
    "ExecutionResult",
]
