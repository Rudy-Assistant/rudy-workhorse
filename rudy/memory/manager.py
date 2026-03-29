"""
Memory Manager — unified interface to all three memory tiers.

This is the primary API that agents and Oracle use to interact
with the memory system. It wraps episodic, semantic, and procedural
memory behind a single, coherent interface.

Usage:
    from rudy.memory import MemoryManager

    mem = MemoryManager()

    # Episodic
    mem.log_event("sentinel", "alert", {"threat": "unknown MAC"})
    events = mem.get_timeline("2026-03-27T00:00:00")

    # Semantic
    mem.store_knowledge("Port 8080 found open on 192.168.7.42", source="nmap")
    results = mem.recall("open ports on the network")

    # Procedural
    rules = mem.get_persona_rules("rudy")
    mem.learn("sentinel", "ARP storms from 192.168.7.99 are the printer")

    # Cross-tier
    context = mem.build_context("rudy", query="email from VIP client")
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from rudy.memory.episodic import EpisodicMemory
from rudy.memory.semantic import SemanticMemory
from rudy.memory.procedural import ProceduralMemory

log = logging.getLogger(__name__)

# Default paths — follow rudy/paths.py conventions
DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
DEFAULT_DB_PATH = DESKTOP / "rudy-data" / "memory.sqlite"
DEFAULT_PERSONAS_DIR = Path(__file__).parent.parent / "personas"


class MemoryManager:
    """Unified interface to the tripartite memory system.

    Combines episodic, semantic, and procedural memory behind
    a single API. Agents interact with this class, not the
    individual memory stores.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        personas_dir: Optional[Path] = None,
    ):
        self._db_path = db_path or DEFAULT_DB_PATH
        self._personas_dir = personas_dir or DEFAULT_PERSONAS_DIR

        self.episodic = EpisodicMemory(self._db_path)
        self.semantic = SemanticMemory(self._db_path)
        self.procedural = ProceduralMemory(self._db_path, self._personas_dir)

        # Auto-load personas if directory exists
        if self._personas_dir.exists():
            try:
                self.procedural.load_personas()
            except Exception as e:
                log.debug(f"Auto-load personas failed: {e}")

    # ── Episodic Shortcuts ──────────────────────────────────────

    def log_event(
        self,
        agent: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> int:
        """Record an event to episodic memory.

        Standard event types:
          - alert: Security or system alert
          - action: Agent took an action
          - tool_call: External tool invocation
          - user_command: Direct user instruction
          - message: Inter-agent communication
          - health: Health check result
          - error: Error or failure
        """
        return self.episodic.log_event(
            agent=agent,
            event_type=event_type,
            payload=payload,
            session_id=session_id,
            tags=tags,
        )

    def get_timeline(
        self,
        since: str,
        until: Optional[str] = None,
        agents: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get chronological event timeline."""
        return self.episodic.get_timeline(since, until, agents)

    def get_recent_events(
        self,
        agent: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get recent events for a specific agent."""
        return self.episodic.get_recent(agent, limit)

    # ── Semantic Shortcuts ──────────────────────────────────────

    def store_knowledge(
        self,
        text: str,
        collection: str = "general",
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Store knowledge in semantic memory for later retrieval."""
        return self.semantic.add_text(text, collection, source, metadata)

    def recall(
        self,
        query: str,
        collection: Optional[str] = None,
        n_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search semantic memory for relevant knowledge."""
        return self.semantic.search(query, collection, n_results)

    def index_file(
        self,
        filepath: Path,
        collection: str = "documents",
    ) -> Dict[str, Any]:
        """Index a file into semantic memory."""
        return self.semantic.index_file(filepath, collection)

    # ── Procedural Shortcuts ────────────────────────────────────

    def get_persona_rules(
        self,
        persona: str,
        rule_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get rules for a persona."""
        return self.procedural.get_rules(persona, rule_type)

    def get_persona_identity(self, persona: str) -> Dict[str, str]:
        """Get identity metadata for a persona."""
        return self.procedural.get_identity(persona)

    def get_persona_boundaries(self, persona: str) -> List[str]:
        """Get boundary rules for a persona."""
        return self.procedural.get_boundaries(persona)

    def learn(
        self,
        agent: str,
        behavior: str,
        context: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ) -> int:
        """Record a learned behavior to procedural memory."""
        return self.procedural.record_behavior(agent, behavior, context, success)

    def reload_personas(self) -> Dict[str, int]:
        """Force-reload all persona files."""
        return self.procedural.load_personas()

    # ── Cross-Tier Operations ───────────────────────────────────

    def build_context(
        self,
        persona: str,
        query: Optional[str] = None,
        include_recent_events: bool = True,
        include_knowledge: bool = True,
        include_rules: bool = True,
        event_hours: int = 24,
        knowledge_results: int = 3,
    ) -> Dict[str, Any]:
        """Build a rich context packet for an agent spawn prompt.

        This is the key Oracle integration point. When Oracle spawns
        a sub-agent, it calls build_context() to assemble the minimal,
        focused context the agent needs — without overwhelming it with
        the full conversation history.

        Args:
            persona: Which persona's rules to include.
            query: Optional semantic query to find relevant knowledge.
            include_recent_events: Include recent episodic events.
            include_knowledge: Include semantic search results.
            include_rules: Include procedural persona rules.
            event_hours: How many hours of events to include.
            knowledge_results: How many semantic results to include.

        Returns:
            Context dict with three sections: events, knowledge, rules.
        """
        context: Dict[str, Any] = {
            "persona": persona,
            "built_at": datetime.now().isoformat(),
        }

        if include_rules:
            context["rules"] = self.procedural.get_rules(persona)
            context["boundaries"] = self.procedural.get_boundaries(persona)

        if include_recent_events:
            since = (
                datetime.now() - timedelta(hours=event_hours)
            ).isoformat()
            context["recent_events"] = self.episodic.query(
                since=since, limit=50
            )

        if include_knowledge and query:
            context["relevant_knowledge"] = self.semantic.search(
                query, n_results=knowledge_results
            )

        return context

    def maintenance(self, compress_days: int = 30) -> Dict[str, Any]:
        """Run maintenance tasks across all memory tiers.

        - Compress old episodic events into daily summaries
        - Report statistics

        Returns:
            Maintenance report dict.
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "compression": self.episodic.compress_old_events(compress_days),
            "stats": self.get_stats(),
        }
        return report

    def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics from all memory tiers."""
        return {
            "episodic": self.episodic.get_stats(),
            "semantic": self.semantic.get_stats(),
            "procedural": self.procedural.get_stats(),
            "db_path": str(self._db_path),
            "personas_dir": str(self._personas_dir),
        }
