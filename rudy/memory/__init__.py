"""
Tripartite Memory System — persistent state for the Oracle agentic mesh.

Three memory tiers:
  1. Episodic:   Timestamped event log (what happened and when)
  2. Semantic:   Vector similarity search (what do we know about X?)
  3. Procedural: Persona rules and learned behaviors (how should we act?)

All tiers use SQLite for zero-ops, single-file persistence on the local
NVMe drive. No external services required.

Usage:
    from rudy.memory import MemoryManager

    mem = MemoryManager()
    mem.log_event("sentinel", "alert", {"threat": "unknown MAC on network"})
    mem.store_knowledge("Security scan found open port 8080", source="sentinel")
    rules = mem.get_persona_rules("rudy")
    results = mem.recall("network security threats this week")
"""

from rudy.memory.manager import MemoryManager
from rudy.memory.episodic import EpisodicMemory
from rudy.memory.semantic import SemanticMemory
from rudy.memory.procedural import ProceduralMemory

__all__ = ["MemoryManager", "EpisodicMemory", "SemanticMemory", "ProceduralMemory"]
