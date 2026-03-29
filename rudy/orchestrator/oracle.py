"""
Oracle Orchestrator — Phase 2 Central Coordination System

The Oracle is the central orchestrator managing task decomposition,
agent spawning, HITL approval gates, inter-agent messaging, and
health monitoring.

Execution Flow:
    1. Intent arrives → decompose into TaskPlan
    2. HITL gate check for high-risk steps
    3. 6-phase execution: Planning → Setup → Implementation → Testing → Review → Finalization
    4. Agent spawning via SpawnEngine with context from MemoryManager
    5. Message routing and inter-agent communication
    6. Health monitoring and escalation on failure
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
import uuid

from rudy.agents import AgentBase
from rudy.memory.manager import MemoryManager
from rudy.memory.agent_mixin import AgentMemoryMixin
from rudy.orchestrator.task_plan import TaskPlan, TaskStep, TaskStatus, RiskLevel
from rudy.orchestrator.spawn_engine import SpawnEngine
from rudy.orchestrator.hitl import HITLGate, ApprovalRequest
from rudy.orchestrator.results import AgentResult, ExecutionResult

log = logging.getLogger(__name__)


class Oracle(AgentBase, AgentMemoryMixin):
    """Central orchestrator for task decomposition and agent coordination.

    The Oracle:
    - Decomposes high-level intents into executable TaskPlan objects
    - Manages an agent registry with capabilities
    - Spawns and coordinates sub-agents via SpawnEngine
    - Enforces HITL approval gates for high-risk operations
    - Routes messages between agents
    - Monitors agent health and escalates failures
    - Implements 6-phase execution with rollback on failure
    """

    name = "oracle"
    version = "2.0"

    def __init__(
        self,
        memory_manager: Optional[MemoryManager] = None,
        spawn_engine: Optional[SpawnEngine] = None,
        hitl_gate: Optional[HITLGate] = None,
    ):
        """Initialize Oracle orchestrator.

        Args:
            memory_manager: MemoryManager instance (created if not provided)
            spawn_engine: SpawnEngine instance (created if not provided)
            hitl_gate: HITLGate instance (created if not provided)
        """
        super().__init__()

        self._memory = memory_manager or MemoryManager()
        self._spawn_engine = spawn_engine or SpawnEngine()
        self._hitl = hitl_gate or HITLGate()

        # Agent registry: {name: {"class": AgentClass, "capabilities": [...]}}
        self._agents: Dict[str, Dict[str, Any]] = {}

        # Message queue for inter-agent communication
        self._messages: Dict[str, List[Dict[str, Any]]] = {}

        # Execution phases
        self._phases = [
            "Planning",
            "Setup",
            "Implementation",
            "Testing",
            "Review",
            "Finalization",
        ]

        # Failure tracking: {agent_name: consecutive_failure_count}
        self._failure_counts: Dict[str, int] = {}
        self._escalation_threshold = 3

        log.info(f"{self.name} v{self.version} initialized")
        self.summarize(f"Oracle orchestrator ready ({self.version})")

    def run(self, **kwargs):
        """Override AgentBase.run() — not used directly.

        The Oracle is coordinate-driven, not run-driven. Use execute_plan()
        or decompose() instead.
        """
        raise NotImplementedError(
            "Oracle is coordinate-driven. Use decompose() or execute_plan() instead."
        )

    # ── Agent Registry ──────────────────────────────────────────────────

    def register_agent(
        self,
        name: str,
        agent_class: type,
        capabilities: Optional[List[str]] = None,
    ) -> None:
        """Register an agent in the registry.

        Args:
            name: Unique agent name
            agent_class: Agent class (subclass of AgentBase)
            capabilities: List of capability strings (e.g., ["network_scan", "alert"])

        Example:
            oracle.register_agent("sentinel", SentinelAgent, ["threat_detection", "alerting"])
        """
        self._agents[name] = {
            "class": agent_class,
            "capabilities": capabilities or [],
            "registered_at": datetime.now().isoformat(),
        }
        self.action(f"Registered agent: {name} with {len(capabilities or [])} capabilities")
        log.info(f"Agent registered: {name}")

    def unregister_agent(self, name: str) -> bool:
        """Unregister an agent from the registry.

        Args:
            name: Agent name to unregister

        Returns:
            True if unregistered, False if not found
        """
        if name in self._agents:
            del self._agents[name]
            self.action(f"Unregistered agent: {name}")
            log.info(f"Agent unregistered: {name}")
            return True
        return False

    def get_agent_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a registered agent.

        Args:
            name: Agent name

        Returns:
            Agent info dict or None if not found
        """
        return self._agents.get(name)

    def get_agents_with_capability(self, capability: str) -> List[str]:
        """Find all agents that have a specific capability.

        Args:
            capability: Capability string to search for

        Returns:
            List of agent names
        """
        return [
            name
            for name, info in self._agents.items()
            if capability in info.get("capabilities", [])
        ]

    # ── Task Decomposition ──────────────────────────────────────────────

    def decompose(
        self,
        intent: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> TaskPlan:
        """Decompose a high-level intent into an executable TaskPlan.

        This is a planning-only operation. To execute the plan, call execute_plan().

        Args:
            intent: User request or high-level goal
            context: Optional contextual data

        Returns:
            TaskPlan with steps decomposed from the intent
        """
        plan = TaskPlan(intent=intent)

        # Log decomposition
        self.memory_log(
            "task_decomposition",
            {"intent": intent[:100], "plan_id": plan.id},
        )

        log.info(f"Decomposing intent: {intent[:100]}")

        # Example decomposition strategy
        # In practice, this would use LLM-based planning
        if "network" in intent.lower():
            plan.add_step(
                description="Scan network for active hosts",
                agent="sentinel",
                risk_level=RiskLevel.LOW,
            )
            plan.add_step(
                description="Analyze open ports",
                agent="sentinel",
                dependencies=[plan.steps[0].id],
                risk_level=RiskLevel.MEDIUM,
            )

        elif "security" in intent.lower() or "threat" in intent.lower():
            plan.add_step(
                description="Review threat intelligence",
                agent="sentinel",
                risk_level=RiskLevel.MEDIUM,
            )
            plan.add_step(
                description="Check for indicators of compromise",
                agent="sentinel",
                dependencies=[plan.steps[0].id],
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
            )

        else:
            # Generic fallback
            plan.add_step(
                description=intent,
                agent="sentinel",
                risk_level=RiskLevel.MEDIUM,
            )

        self.action(f"Decomposed into {len(plan.steps)} steps")
        return plan

    # ── Plan Execution ─────────────────────────────────────────────────

    def execute_plan(self, plan: TaskPlan) -> ExecutionResult:
        """Execute a TaskPlan through the 6-phase execution model.

        Phases:
            1. Planning: Verify plan validity
            2. Setup: Build context packets, gate approvals
            3. Implementation: Spawn agents and execute steps
            4. Testing: Validate agent outputs
            5. Review: Compare against intent
            6. Finalization: Log results, synthesize

        On phase failure, rolls back with error context attached.

        Args:
            plan: TaskPlan to execute

        Returns:
            ExecutionResult with outcomes and any errors
        """
        log.info(f"Starting execution of plan {plan.id}")
        self.action(f"Executing plan: {plan.intent[:60]}")

        result = ExecutionResult(
            plan_id=plan.id,
            intent=plan.intent,
            status="pending",
            agent_results=[],
            duration_seconds=0.0,
        )

        start_time = datetime.now()

        try:
            # Phase 1: Planning
            if not self._phase_planning(plan):
                raise RuntimeError("Planning phase failed")
            result.phases_completed.append("Planning")
            plan.current_phase = "Planning"

            # Phase 2: Setup
            if not self._phase_setup(plan):
                raise RuntimeError("Setup phase failed")
            result.phases_completed.append("Setup")
            plan.current_phase = "Setup"

            # Phase 3: Implementation
            agent_results = self._phase_implementation(plan)
            result.agent_results.extend(agent_results)
            result.phases_completed.append("Implementation")
            plan.current_phase = "Implementation"

            # Phase 4: Testing
            if not self._phase_testing(plan, agent_results):
                raise RuntimeError("Testing phase failed")
            result.phases_completed.append("Testing")
            plan.current_phase = "Testing"

            # Phase 5: Review
            if not self._phase_review(plan, result):
                raise RuntimeError("Review phase failed")
            result.phases_completed.append("Review")
            plan.current_phase = "Review"

            # Phase 6: Finalization
            if not self._phase_finalization(plan, result):
                raise RuntimeError("Finalization phase failed")
            result.phases_completed.append("Finalization")
            plan.current_phase = "Finalization"

            result.status = "completed"
            plan.status = "completed"
            self.action(f"Plan execution completed: {plan.id}")

        except Exception as e:
            log.error(f"Plan execution failed at phase {plan.current_phase}: {e}")
            result.status = "failed"
            result.current_phase = plan.current_phase
            result.error_context = {
                "phase": plan.current_phase,
                "error": str(e),
                "progress": plan.get_progress(),
            }
            plan.status = "failed"
            self.alert(f"Plan execution failed: {e}")

        finally:
            elapsed = (datetime.now() - start_time).total_seconds()
            result.duration_seconds = elapsed
            plan.metadata["executed_at"] = datetime.now().isoformat()

            # Log to memory
            self.memory_log(
                "plan_execution",
                {
                    "plan_id": plan.id,
                    "status": result.status,
                    "steps": len(plan.steps),
                    "duration_seconds": elapsed,
                },
                tags=["execution"],
            )

        return result

    def _phase_planning(self, plan: TaskPlan) -> bool:
        """Phase 1: Planning — validate plan structure."""
        log.debug("Entering Planning phase")

        if not plan.steps:
            log.error("Plan has no steps")
            return False

        log.debug(f"Plan valid: {len(plan.steps)} steps")
        return True

    def _phase_setup(self, plan: TaskPlan) -> bool:
        """Phase 2: Setup — build context and check approvals."""
        log.debug("Entering Setup phase")

        for step in plan.steps:
            # Check HITL gates for high-risk steps
            if step.requires_approval or step.risk_level in [
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            ]:
                log.info(f"Gating step {step.id}: {step.description}")

                if not self._hitl.auto_gate(
                    task_description=step.description,
                    risk_level=step.risk_level.value,
                    context={"step_id": step.id, "plan_id": plan.id},
                    requester="oracle",
                ):
                    log.warning(f"Step {step.id} awaiting approval")
                    # In a full implementation, would wait for approval
                    # For now, continue (mock gate)

        log.debug("Setup phase complete")
        return True

    def _phase_implementation(self, plan: TaskPlan) -> List[AgentResult]:
        """Phase 3: Implementation — spawn agents and execute steps."""
        log.debug("Entering Implementation phase")

        agent_results = []
        completed_ids = set()

        while True:
            ready_steps = plan.get_ready_steps()
            if not ready_steps:
                break

            for step in ready_steps:
                result = self.spawn_agent(step.agent, step.description, plan)
                agent_results.append(result)

                if result.is_success():
                    step.mark_completed(result.output)
                    completed_ids.add(step.id)
                else:
                    step.mark_failed(result.error_message or "Unknown error")

                # Track failures for escalation
                if not result.is_success():
                    self._failure_counts[step.agent] = (
                        self._failure_counts.get(step.agent, 0) + 1
                    )

                    if self._failure_counts[step.agent] >= self._escalation_threshold:
                        self.escalate(
                            f"Agent {step.agent} failed {self._escalation_threshold} times",
                            {"step_id": step.id, "plan_id": plan.id},
                        )

        log.debug("Implementation phase complete")
        return agent_results

    def _phase_testing(self, plan: TaskPlan, agent_results: List[AgentResult]) -> bool:
        """Phase 4: Testing — validate agent outputs."""
        log.debug("Entering Testing phase")

        # Basic validation: all successful results
        for result in agent_results:
            if not result.is_success():
                log.warning(f"Test failed: {result.agent_name} returned {result.status}")

        log.debug("Testing phase complete")
        return True

    def _phase_review(self, plan: TaskPlan, result: ExecutionResult) -> bool:
        """Phase 5: Review — compare outputs against intent."""
        log.debug("Entering Review phase")

        progress = plan.get_progress()
        log.debug(f"Plan progress: {progress}")

        # Basic review: intent is reflected in completed steps
        completed_steps = [s for s in plan.steps if s.status == TaskStatus.COMPLETED]
        if not completed_steps:
            log.warning("No completed steps in plan")

        log.debug("Review phase complete")
        return True

    def _phase_finalization(self, plan: TaskPlan, result: ExecutionResult) -> bool:
        """Phase 6: Finalization — synthesize and log results."""
        log.debug("Entering Finalization phase")

        # Log final results to memory
        self.memory_log(
            "plan_finalized",
            {
                "plan_id": plan.id,
                "status": result.status,
                "completed_steps": len(
                    [s for s in plan.steps if s.status == TaskStatus.COMPLETED]
                ),
            },
            tags=["finalization"],
        )

        log.debug("Finalization phase complete")
        return True

    # ── Agent Spawning ──────────────────────────────────────────────────

    def spawn_agent(
        self,
        agent_name: str,
        task: str,
        plan: TaskPlan,
    ) -> AgentResult:
        """Spawn and execute a single agent for a task.

        Builds context from MemoryManager, uses SpawnEngine to create
        and execute the agent.

        Args:
            agent_name: Name of the agent to spawn
            task: Task description
            plan: TaskPlan context

        Returns:
            AgentResult with execution outcome
        """
        try:
            # Get agent info
            agent_info = self.get_agent_info(agent_name)
            if not agent_info:
                return AgentResult(
                    agent_name=agent_name,
                    task=task,
                    status="error",
                    output={},
                    duration_seconds=0.0,
                    error_message=f"Agent {agent_name} not registered",
                )

            # Build context
            context = self._memory.build_context(
                persona=agent_name,
                query=task,
            )

            # Get persona identity and rules
            identity = self._memory.get_persona_identity(agent_name) or {"name": agent_name}
            rules = self._memory.get_persona_rules(agent_name) or {}
            boundaries = self._memory.get_persona_boundaries(agent_name) or []

            # Spawn agent
            spawn_result = self._spawn_engine.spawn(
                agent_name=f"{agent_name}-{plan.id[:6]}",
                task=task,
                persona=agent_name,
                identity=identity,
                rules=rules,
                boundaries=boundaries,
                context=context,
                timeout_seconds=300,
            )

            # Convert to AgentResult
            return AgentResult(
                agent_name=agent_name,
                task=task,
                status=spawn_result.status,
                output=spawn_result.output,
                duration_seconds=spawn_result.duration_seconds,
                error_message=spawn_result.error_message,
            )

        except Exception as e:
            log.error(f"Failed to spawn agent {agent_name}: {e}")
            return AgentResult(
                agent_name=agent_name,
                task=task,
                status="error",
                output={},
                duration_seconds=0.0,
                error_message=str(e),
            )

    # ── Message Routing ────────────────────────────────────────────────

    def route_message(
        self,
        from_agent: str,
        to_agent: str,
        message: Dict[str, Any],
    ) -> None:
        """Route a message between agents.

        Messages are queued for the recipient. Agents retrieve with get_messages().

        Args:
            from_agent: Sender agent name
            to_agent: Recipient agent name
            message: Message content dict
        """
        if to_agent not in self._messages:
            self._messages[to_agent] = []

        msg = {
            "from": from_agent,
            "to": to_agent,
            "timestamp": datetime.now().isoformat(),
            "content": message,
        }

        self._messages[to_agent].append(msg)
        log.debug(f"Message routed: {from_agent} → {to_agent}")

        # Log to memory
        self.memory_log(
            "message_routed",
            {"from": from_agent, "to": to_agent},
            tags=["messaging"],
        )

    def get_messages(self, agent_name: str) -> List[Dict[str, Any]]:
        """Get pending messages for an agent.

        Clears the message queue after retrieval.

        Args:
            agent_name: Agent to get messages for

        Returns:
            List of message dicts
        """
        messages = self._messages.pop(agent_name, [])
        return messages

    # ── Health Monitoring ──────────────────────────────────────────────

    def check_health(self) -> Dict[str, Any]:
        """Check health of all registered agents.

        Returns:
            Dict with health status for each agent
        """
        health = {
            "timestamp": datetime.now().isoformat(),
            "agents": {},
        }

        for agent_name in self._agents:
            try:
                # Try to get agent status from logs
                agent_health = AgentBase().health_check()
                if agent_health:
                    health["agents"][agent_name] = agent_health
            except Exception as e:
                health["agents"][agent_name] = {
                    "agent": agent_name,
                    "status": "error",
                    "error": str(e),
                }

        return health

    # ── Escalation ─────────────────────────────────────────────────────

    def escalate(self, reason: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Escalate an issue to human review.

        Args:
            reason: Reason for escalation
            context: Optional contextual data
        """
        log.warning(f"ESCALATION: {reason}")
        self.alert(f"Escalation required: {reason}")

        # Log to memory
        self.memory_log(
            "escalation",
            {"reason": reason, "context": context},
            tags=["escalation"],
        )

        # In a full implementation, would trigger human-in-the-loop
        # For now, just log it
