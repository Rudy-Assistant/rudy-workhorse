"""
Spawn Engine — Agent Instantiation and Lifecycle Management

Responsible for creating agent instances, building spawn prompts from
context, executing agents, collecting results, and managing timeouts.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
import uuid

log = logging.getLogger(__name__)


class AgentSpawnConfig:
    """Configuration for spawning an agent."""

    def __init__(
        self,
        name: str,
        persona: str,
        identity: Dict[str, str],
        rules: Dict[str, Any],
        boundaries: List[str],
        task: str,
        context: Dict[str, Any],
        timeout_seconds: int = 300,
    ):
        """Initialize spawn configuration.

        Args:
            name: Agent instance name
            persona: Persona type (e.g., "oracle", "sentinel")
            identity: Identity metadata from persona
            rules: Rules from persona
            boundaries: Boundary rules from persona
            task: Specific task to execute
            context: Context packet from MemoryManager.build_context()
            timeout_seconds: Execution timeout
        """
        self.name = name
        self.persona = persona
        self.identity = identity
        self.rules = rules
        self.boundaries = boundaries
        self.task = task
        self.context = context
        self.timeout_seconds = timeout_seconds


class SpawnEngine:
    """Manages agent spawning, execution, and result collection.

    The spawn engine is responsible for:
    - Building spawn prompts from persona + context
    - Creating agent instances (mock in this impl)
    - Executing with timeout management
    - Collecting structured results
    - Supporting parallel spawns for independent tasks
    """

    def __init__(self, agent_factory: Optional[Callable] = None):
        """Initialize spawn engine.

        Args:
            agent_factory: Optional callable to create agent instances.
                          If not provided, mock agents are created.
        """
        self._agent_factory = agent_factory
        self._executor = ThreadPoolExecutor(max_workers=10)
        self._active_agents: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def build_spawn_prompt(
        self,
        persona: str,
        identity: Dict[str, str],
        rules: Dict[str, Any],
        boundaries: List[str],
        task: str,
        context: Dict[str, Any],
    ) -> str:
        """Build a complete spawn prompt for an agent.

        Format:
            [IDENTITY] — agent name, role, archetype, tone
            [RULES] — procedural rules from persona
            [BOUNDARIES] — hard constraints
            [CONTEXT] — relevant events, knowledge, recent activity
            [TASK] — specific task to execute

        Args:
            persona: Persona name
            identity: Identity metadata
            rules: Procedural rules dict
            boundaries: List of boundary rules
            task: Specific task description
            context: Context from MemoryManager

        Returns:
            Formatted spawn prompt string
        """
        lines = []

        # Identity section
        lines.append("=" * 60)
        lines.append("AGENT SPAWN PROMPT")
        lines.append("=" * 60)
        lines.append("")

        lines.append("[IDENTITY]")
        lines.append(f"Name: {identity.get('name', 'Unnamed')}")
        lines.append(f"Role: {identity.get('role', 'Agent')}")
        lines.append(f"Archetype: {identity.get('archetype', 'Unknown')}")
        lines.append(f"Tone: {identity.get('tone', 'Professional')}")
        lines.append(f"Formality: {identity.get('formality', 'Standard')}")
        lines.append("")

        # Rules section
        if rules:
            lines.append("[RULES]")
            if isinstance(rules, dict):
                for key, value in rules.items():
                    if isinstance(value, list):
                        lines.append(f"{key}:")
                        for item in value:
                            lines.append(f"  - {item}")
                    else:
                        lines.append(f"{key}: {value}")
            lines.append("")

        # Boundaries section
        if boundaries:
            lines.append("[BOUNDARIES]")
            for boundary in boundaries:
                lines.append(f"- {boundary}")
            lines.append("")

        # Context section
        if context:
            lines.append("[CONTEXT]")
            if context.get("recent_events"):
                lines.append("Recent Events:")
                for event in context["recent_events"][:5]:  # Limit to 5
                    if isinstance(event, dict):
                        lines.append(
                            f"  - {event.get('event_type', 'event')}: "
                            f"{event.get('payload', {})}"
                        )
                    else:
                        lines.append(f"  - {event}")
                lines.append("")

            if context.get("relevant_knowledge"):
                lines.append("Relevant Knowledge:")
                for item in context["relevant_knowledge"][:3]:  # Limit to 3
                    if isinstance(item, dict):
                        lines.append(f"  - {item.get('text', item)}")
                    else:
                        lines.append(f"  - {item}")
                lines.append("")

        # Task section
        lines.append("[TASK]")
        lines.append(task)
        lines.append("")

        lines.append("=" * 60)
        lines.append("Begin execution. Report results in structured JSON format.")
        lines.append("=" * 60)

        return "\n".join(lines)

    def spawn(
        self,
        agent_name: str,
        task: str,
        persona: str,
        identity: Dict[str, str],
        rules: Dict[str, Any],
        boundaries: List[str],
        context: Dict[str, Any],
        timeout_seconds: int = 300,
    ) -> "AgentSpawnResult":
        """Spawn and execute a single agent.

        Args:
            agent_name: Name for this agent instance
            task: Task to execute
            persona: Persona type
            identity: Identity metadata
            rules: Procedural rules
            boundaries: Boundary constraints
            context: Context packet
            timeout_seconds: Execution timeout

        Returns:
            AgentSpawnResult with execution outcome
        """
        start_time = datetime.now()

        try:
            # Build spawn prompt
            prompt = self.build_spawn_prompt(
                persona=persona,
                identity=identity,
                rules=rules,
                boundaries=boundaries,
                task=task,
                context=context,
            )

            # Log to memory if available
            try:
                from rudy.memory.manager import MemoryManager
                mem = MemoryManager()
                mem.log_event(
                    "oracle",
                    "agent_spawn",
                    {"agent": agent_name, "task": task[:100]},
                    tags=["spawn"],
                )
            except Exception as e:
                log.debug(f"Failed to log spawn to memory: {e}")

            # Create agent instance (mock implementation)
            agent = self._create_agent(agent_name, persona)

            # Execute agent with timeout
            log.info(f"Spawning agent: {agent_name} (timeout: {timeout_seconds}s)")

            result = self._execute_with_timeout(
                agent=agent,
                prompt=prompt,
                task=task,
                timeout_seconds=timeout_seconds,
            )

            elapsed = (datetime.now() - start_time).total_seconds()

            return AgentSpawnResult(
                agent_name=agent_name,
                task=task,
                status=result.get("status", "success"),
                output=result.get("output", {}),
                duration_seconds=elapsed,
                error_message=result.get("error", None),
            )

        except TimeoutError as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            log.error(f"Agent {agent_name} timed out after {elapsed}s")
            return AgentSpawnResult(
                agent_name=agent_name,
                task=task,
                status="timeout",
                output={},
                duration_seconds=elapsed,
                error_message=f"Timeout after {timeout_seconds}s",
            )

        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            log.error(f"Agent spawn failed: {e}", exc_info=True)
            return AgentSpawnResult(
                agent_name=agent_name,
                task=task,
                status="error",
                output={},
                duration_seconds=elapsed,
                error_message=str(e),
            )

    def spawn_parallel(
        self,
        tasks: List[Dict[str, Any]],
        timeout_seconds: int = 300,
    ) -> List["AgentSpawnResult"]:
        """Spawn and execute multiple agents in parallel.

        Args:
            tasks: List of spawn task dicts, each with:
                   agent_name, task, persona, identity, rules, boundaries, context
            timeout_seconds: Timeout per agent

        Returns:
            List of AgentSpawnResult objects (order may differ from input)
        """
        futures = []

        for task_spec in tasks:
            future = self._executor.submit(
                self.spawn,
                agent_name=task_spec["agent_name"],
                task=task_spec["task"],
                persona=task_spec["persona"],
                identity=task_spec["identity"],
                rules=task_spec["rules"],
                boundaries=task_spec["boundaries"],
                context=task_spec["context"],
                timeout_seconds=timeout_seconds,
            )
            futures.append((task_spec["agent_name"], future))

        results = []
        for agent_name, future in futures:
            try:
                result = future.result(timeout=timeout_seconds + 5)
                results.append(result)
            except TimeoutError:
                log.error(f"Parallel spawn timed out: {agent_name}")
                results.append(
                    AgentSpawnResult(
                        agent_name=agent_name,
                        task="parallel_task",
                        status="timeout",
                        output={},
                        duration_seconds=timeout_seconds,
                        error_message="Timeout in parallel spawn",
                    )
                )
            except Exception as e:
                log.error(f"Parallel spawn error for {agent_name}: {e}")
                results.append(
                    AgentSpawnResult(
                        agent_name=agent_name,
                        task="parallel_task",
                        status="error",
                        output={},
                        duration_seconds=0,
                        error_message=str(e),
                    )
                )

        return results

    def _create_agent(self, name: str, persona: str) -> Any:
        """Create an agent instance.

        Uses agent_factory if provided, otherwise creates a mock agent.

        Args:
            name: Agent instance name
            persona: Persona type

        Returns:
            Agent instance
        """
        if self._agent_factory:
            return self._agent_factory(name, persona)

        # Mock agent
        class MockAgent:
            def __init__(self, agent_name, agent_persona):
                self.name = agent_name
                self.persona = agent_persona

            def execute(self, prompt: str, task: str) -> Dict[str, Any]:
                """Mock execution."""
                return {
                    "status": "success",
                    "output": {
                        "agent": self.name,
                        "task": task,
                        "result": "mock execution completed",
                    },
                }

        return MockAgent(name, persona)

    def _execute_with_timeout(
        self,
        agent: Any,
        prompt: str,
        task: str,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """Execute agent with timeout protection.

        Args:
            agent: Agent instance
            prompt: Spawn prompt
            task: Task description
            timeout_seconds: Timeout in seconds

        Returns:
            Result dict with status, output, error keys
        """
        try:
            # Execute agent (assumes agent.execute() method)
            if hasattr(agent, "execute"):
                result = agent.execute(prompt, task)
            else:
                # Fallback: treat as callable
                result = agent(prompt, task)

            return {
                "status": "success",
                "output": result,
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "output": {},
            }

    def collect_result(self, agent_name: str) -> Optional["AgentSpawnResult"]:
        """Collect result from a spawned agent (placeholder for async).

        In a full implementation, this would retrieve results from
        an async queue or monitoring system. For now, it's a placeholder.

        Args:
            agent_name: Name of agent to collect from

        Returns:
            AgentSpawnResult or None if not found
        """
        with self._lock:
            return self._active_agents.get(agent_name)


class AgentSpawnResult:
    """Result from spawning and executing a single agent."""

    def __init__(
        self,
        agent_name: str,
        task: str,
        status: str,
        output: Any,
        duration_seconds: float,
        error_message: Optional[str] = None,
    ):
        """Initialize spawn result.

        Args:
            agent_name: Name of the agent
            task: Task that was executed
            status: Result status (success/failure/timeout/error)
            output: Agent output data
            duration_seconds: Execution time
            error_message: Error details if applicable
        """
        self.agent_name = agent_name
        self.task = task
        self.status = status
        self.output = output
        self.duration_seconds = duration_seconds
        self.error_message = error_message

    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == "success"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "agent_name": self.agent_name,
            "task": self.task,
            "status": self.status,
            "output": self.output,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
        }
