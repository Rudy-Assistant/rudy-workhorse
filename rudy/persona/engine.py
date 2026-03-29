"""
Persona Engine — Runtime persona enforcement layer between Oracle and agents.

Loads persona definitions from ProceduralMemory and enforces boundaries,
validates actions against persona constraints, detects drift, and builds
system prompts that embed persona identity directly in agent instructions.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from rudy.memory.manager import MemoryManager

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating an action against persona boundaries."""

    allowed: bool
    reason: str
    boundary_violated: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "boundary_violated": self.boundary_violated,
        }


@dataclass
class PersonaContext:
    """Active persona state held in memory during execution."""

    name: str
    identity: Dict[str, str]
    capabilities: Dict[str, str]
    boundaries: List[str]
    escalation_triggers: List[str]
    rules: Dict[str, Any] = field(default_factory=dict)
    loaded_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "identity": self.identity,
            "capabilities": self.capabilities,
            "boundaries": self.boundaries,
            "escalation_triggers": self.escalation_triggers,
            "rules": self.rules,
            "loaded_at": self.loaded_at,
        }


class PersonaEngine:
    """Runtime persona enforcement layer.

    Loads persona definitions from ProceduralMemory, validates actions
    against boundaries, detects drift, and generates persona-aware prompts
    for sub-agents.

    Usage:
        engine = PersonaEngine()
        ctx = engine.activate_persona("rudy")
        result = engine.validate_action("rudy", "send_email", {...})
        prompt = engine.get_system_prompt("rudy", "compose an email")
    """

    def __init__(self, memory_manager: Optional[MemoryManager] = None):
        """Initialize persona engine.

        Args:
            memory_manager: MemoryManager instance (created if not provided)
        """
        self._memory = memory_manager or MemoryManager()
        self._persona_cache: Dict[str, PersonaContext] = {}
        self._enforcement_log: List[Dict[str, Any]] = []

        log.info("PersonaEngine initialized")

    # ── Persona Activation ──────────────────────────────────────────

    def activate_persona(self, name: str) -> PersonaContext:
        """Load and cache a persona from ProceduralMemory.

        Args:
            name: Persona name (e.g., "rudy", "oracle", "sentinel")

        Returns:
            PersonaContext with loaded persona state

        Raises:
            ValueError: If persona not found
        """
        # Check cache first
        if name in self._persona_cache:
            log.debug(f"Using cached persona: {name}")
            return self._persona_cache[name]

        # Load from memory
        try:
            identity = self._memory.get_persona_identity(name) or {}
            rules = self._memory.get_persona_rules(name) or {}
            boundaries = self._memory.get_persona_boundaries(name) or []
            escalation = self._memory.procedural.get_escalation_triggers(name) or []

            # Extract capabilities if present in rules
            capabilities = rules.get("capabilities", {})

            context = PersonaContext(
                name=name,
                identity=identity,
                capabilities=capabilities,
                boundaries=boundaries,
                escalation_triggers=escalation,
                rules=rules,
            )

            # Cache it
            self._persona_cache[name] = context

            log.info(f"Activated persona: {name} ({len(boundaries)} boundaries)")
            return context

        except Exception as e:
            log.error(f"Failed to activate persona {name}: {e}")
            raise ValueError(f"Persona '{name}' not found or failed to load") from e

    def get_cached_persona(self, name: str) -> Optional[PersonaContext]:
        """Retrieve a cached persona without reloading.

        Args:
            name: Persona name

        Returns:
            PersonaContext if cached, None otherwise
        """
        return self._persona_cache.get(name)

    # ── Action Validation ──────────────────────────────────────────

    def validate_action(
        self,
        persona_name: str,
        action_type: str,
        action_details: Dict[str, Any],
    ) -> ValidationResult:
        """Validate an action against persona boundaries.

        Args:
            persona_name: Name of the persona to check
            action_type: Type of action (e.g., "send_email", "delete_file")
            action_details: Dict with action parameters

        Returns:
            ValidationResult with allowed flag and reason
        """
        try:
            context = self.activate_persona(persona_name)
        except ValueError:
            return ValidationResult(
                allowed=False,
                reason=f"Persona '{persona_name}' not found",
            )

        # Check boundaries
        for boundary in context.boundaries:
            if self._boundary_matches_action(boundary, action_type, action_details):
                # Log boundary violation
                self._log_enforcement(
                    persona_name=persona_name,
                    action_type=action_type,
                    allowed=False,
                    boundary_violated=boundary,
                )

                return ValidationResult(
                    allowed=False,
                    reason=f"Action violates boundary: {boundary}",
                    boundary_violated=boundary,
                )

        # Log successful validation
        self._log_enforcement(
            persona_name=persona_name,
            action_type=action_type,
            allowed=True,
        )

        return ValidationResult(
            allowed=True,
            reason=f"Action permitted for {persona_name}",
        )

    def enforce_boundaries(
        self,
        persona_name: str,
        proposed_action: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Enforce boundaries on a proposed action.

        Args:
            persona_name: Name of the persona
            proposed_action: Action dict with 'type' and parameters

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        action_type = proposed_action.get("type", "unknown")
        result = self.validate_action(persona_name, action_type, proposed_action)
        return (result.allowed, result.reason)

    def _boundary_matches_action(
        self,
        boundary: str,
        action_type: str,
        action_details: Dict[str, Any],
    ) -> bool:
        """Check if a boundary rule matches an action.

        Matching is keyword-based and case-insensitive.

        Args:
            boundary: Boundary rule text
            action_type: Action type string
            action_details: Action parameters

        Returns:
            True if boundary matches the action
        """
        boundary_lower = boundary.lower()
        action_lower = action_type.lower()

        # Check action type keywords
        if any(
            keyword in boundary_lower
            for keyword in ["never", "must not", "prohibit", "forbidden"]
        ):
            # Extract what is forbidden
            forbidden_keywords = [
                "send email",
                "delete",
                "share",
                "modify security",
                "impersonate",
                "override",
                "bypass",
                "financial transaction",
                "investment",
                "system settings",
            ]

            for keyword in forbidden_keywords:
                if keyword.lower() in boundary_lower and keyword.lower() in action_lower:
                    return True

        return False

    # ── Drift Detection ─────────────────────────────────────────────

    def check_drift(
        self,
        persona_name: str,
        recent_actions: List[Dict[str, Any]],
    ) -> "DriftReport":  # Forward reference to drift.py
        """Analyze if agent is straying from persona boundaries.

        Args:
            persona_name: Name of the persona
            recent_actions: List of recent action dicts with 'type' key

        Returns:
            DriftReport with drift score and violations
        """
        from rudy.persona.drift import DriftDetector

        detector = DriftDetector()
        return detector.analyze(persona_name, recent_actions)

    # ── System Prompt Generation ────────────────────────────────────

    def get_system_prompt(
        self,
        persona_name: str,
        task_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build a complete system prompt embedding persona identity.

        Args:
            persona_name: Name of the persona
            task_context: Optional context about the current task

        Returns:
            Formatted system prompt string
        """
        from rudy.persona.prompts import build_system_prompt

        try:
            context = self.activate_persona(persona_name)
        except ValueError:
            return f"ERROR: Persona '{persona_name}' not found"

        return build_system_prompt(context, task_context or {})

    # ── Logging & Reporting ────────────────────────────────────────

    def _log_enforcement(
        self,
        persona_name: str,
        action_type: str,
        allowed: bool,
        boundary_violated: Optional[str] = None,
    ) -> None:
        """Log an enforcement decision to memory.

        Args:
            persona_name: Persona name
            action_type: Type of action checked
            allowed: Whether action was allowed
            boundary_violated: Which boundary was violated (if any)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "persona": persona_name,
            "action_type": action_type,
            "allowed": allowed,
            "boundary_violated": boundary_violated,
        }

        self._enforcement_log.append(log_entry)

        # Log to memory if action was denied
        if not allowed and boundary_violated:
            try:
                self._memory.log_event(
                    agent="persona_engine",
                    event_type="boundary_violation",
                    payload={
                        "persona": persona_name,
                        "action_type": action_type,
                        "boundary": boundary_violated,
                    },
                    tags=["boundary", "enforcement"],
                )
            except Exception as e:
                log.debug(f"Failed to log enforcement to memory: {e}")

    def get_enforcement_log(self) -> List[Dict[str, Any]]:
        """Get the enforcement log.

        Returns:
            List of enforcement decisions
        """
        return self._enforcement_log.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics.

        Returns:
            Dict with stats about cached personas and enforcement
        """
        return {
            "cached_personas": len(self._persona_cache),
            "persona_names": list(self._persona_cache.keys()),
            "enforcement_decisions": len(self._enforcement_log),
            "violations": len([e for e in self._enforcement_log if not e["allowed"]]),
        }
