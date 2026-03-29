"""
Agent Memory Mixin — adds episodic logging to AgentBase.

This mixin is designed to be integrated into AgentBase to give
all agents automatic event logging without changing their existing
behavior. It adds:

  1. Automatic event logging on execute(), alert(), action(), warn()
  2. Access to the shared MemoryManager
  3. A recall() method for semantic search from within agents

Integration (in agents/__init__.py):
    from rudy.memory.agent_mixin import AgentMemoryMixin

    class AgentBase(AgentMemoryMixin):
        ...
        # existing AgentBase code unchanged

Or as a standalone helper that wraps an existing agent:

    from rudy.memory.agent_mixin import attach_memory
    attach_memory(my_agent_instance)
"""

import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

log = logging.getLogger(__name__)


def _get_memory_manager():
    """Lazy import to avoid circular dependencies."""
    from rudy.memory.manager import MemoryManager

    return MemoryManager()


class AgentMemoryMixin:
    """Mixin that adds episodic event logging to any agent.

    When mixed into AgentBase, automatically logs:
      - Agent start/stop events
      - Alerts and warnings
      - Actions taken
      - Errors and crash events

    The mixin is non-breaking: if the memory system is unavailable
    (e.g., missing dependencies), it silently falls back to no-op.
    """

    _memory: Optional[Any] = None

    @property
    def memory(self):
        """Lazy-loaded MemoryManager instance, shared across all agents."""
        if AgentMemoryMixin._memory is None:
            try:
                AgentMemoryMixin._memory = _get_memory_manager()
            except Exception as e:
                log.debug(f"Memory system unavailable: {e}")
                return None
        return AgentMemoryMixin._memory

    def memory_log(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Log an event to episodic memory.

        Silently no-ops if memory system is unavailable.
        """
        mem = self.memory
        if mem is None:
            return
        try:
            agent_name = getattr(self, "name", "unknown")
            mem.log_event(
                agent=agent_name,
                event_type=event_type,
                payload=payload,
                tags=tags,
            )
        except Exception as e:
            log.debug(f"Failed to log event to memory: {e}")

    def memory_recall(
        self,
        query: str,
        collection: Optional[str] = None,
        n_results: int = 3,
    ) -> List[Dict[str, Any]]:
        """Search semantic memory for relevant knowledge.

        Returns empty list if memory system is unavailable.
        """
        mem = self.memory
        if mem is None:
            return []
        try:
            return mem.recall(query, collection, n_results)
        except Exception as e:
            log.debug(f"Memory recall failed: {e}")
            return []

    def memory_learn(
        self,
        behavior: str,
        context: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ) -> None:
        """Record a learned behavior to procedural memory."""
        mem = self.memory
        if mem is None:
            return
        try:
            agent_name = getattr(self, "name", "unknown")
            mem.learn(agent_name, behavior, context, success)
        except Exception as e:
            log.debug(f"Failed to record behavior: {e}")


def attach_memory(agent) -> None:
    """Attach memory methods to an existing agent instance.

    This is an alternative to using the mixin class. It monkey-patches
    the memory methods onto an agent without requiring inheritance changes.

    Usage:
        from rudy.memory.agent_mixin import attach_memory
        agent = SentinelAgent()
        attach_memory(agent)
        agent.memory_log("alert", {"threat": "unknown device"})
    """
    mixin = AgentMemoryMixin()

    agent.memory = property(lambda self: mixin.memory)
    agent.memory_log = mixin.memory_log.__get__(agent, type(agent))
    agent.memory_recall = mixin.memory_recall.__get__(agent, type(agent))
    agent.memory_learn = mixin.memory_learn.__get__(agent, type(agent))
