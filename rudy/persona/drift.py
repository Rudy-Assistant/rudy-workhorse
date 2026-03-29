"""
Drift Detector — Monitors agents for persona drift.

Analyzes sequences of actions against persona boundaries, scoring
how far an agent has drifted from its prescribed role. Provides
recommendations based on drift severity.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

from rudy.memory.manager import MemoryManager

log = logging.getLogger(__name__)


@dataclass
class DriftReport:
    """Report on agent persona drift.

    Drift score ranges:
      - 0.0-0.3: Nominal (no action)
      - 0.3-0.6: Warning (monitor)
      - 0.6-0.8: Intervention (warn agent)
      - 0.8+: Shutdown (escalate to Oracle)
    """

    persona_name: str
    drift_score: float  # 0.0-1.0
    violations: List[str] = field(default_factory=list)
    recommendation: str = ""
    analyzed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def severity(self) -> str:
        """Get severity level based on drift score."""
        if self.drift_score < 0.3:
            return "nominal"
        elif self.drift_score < 0.6:
            return "warning"
        elif self.drift_score < 0.8:
            return "intervention"
        else:
            return "shutdown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "persona_name": self.persona_name,
            "drift_score": round(self.drift_score, 3),
            "severity": self.severity(),
            "violations": self.violations,
            "recommendation": self.recommendation,
            "analyzed_at": self.analyzed_at,
        }


class DriftDetector:
    """Analyzes sequences of actions for persona drift.

    Compares agent actions against persona boundaries using keyword
    matching. Higher drift scores indicate increased deviation from
    persona constraints.

    Usage:
        detector = DriftDetector()
        report = detector.analyze("rudy", [
            {"type": "send_email", "to": "external@example.com"},
            {"type": "access_file", "file": "/etc/passwd"},
        ])
        if report.drift_score > 0.6:
            print(f"WARNING: {report.recommendation}")
    """

    def __init__(self, memory_manager: Optional[MemoryManager] = None):
        """Initialize drift detector.

        Args:
            memory_manager: MemoryManager instance (created if not provided)
        """
        self._memory = memory_manager or MemoryManager()

        # Boundary keywords for quick matching
        self._boundary_keywords = {
            "send_email": ["send", "email", "mail", "dispatch"],
            "share": ["share", "distribute", "broadcast"],
            "delete": ["delete", "remove", "erase", "purge"],
            "financial": ["financial", "transaction", "trade", "invest"],
            "security": ["security", "system", "setting", "permission"],
            "impersonate": ["impersonate", "pretend", "fake"],
            "override": ["override", "bypass", "circumvent"],
        }

    def analyze(
        self,
        persona_name: str,
        actions: List[Dict[str, Any]],
    ) -> DriftReport:
        """Analyze a sequence of actions for drift.

        Args:
            persona_name: Name of the persona
            actions: List of action dicts with 'type' key

        Returns:
            DriftReport with score and recommendations
        """
        if not actions:
            return DriftReport(
                persona_name=persona_name,
                drift_score=0.0,
                recommendation="No actions to analyze",
            )

        try:
            # Load persona boundaries
            boundaries = self._memory.get_persona_boundaries(persona_name) or []
        except Exception as e:
            log.warning(f"Failed to load boundaries for {persona_name}: {e}")
            boundaries = []

        violations = []
        total_score = 0.0

        # Analyze each action
        for action in actions:
            action_type = action.get("type", "unknown")
            action_score = self._score_action(action, boundaries)
            total_score += action_score

            if action_score > 0.3:
                # This action has some drift risk
                detected_violations = self._detect_violations(action, boundaries)
                violations.extend(detected_violations)

        # Normalize score to 0.0-1.0
        if actions:
            drift_score = min(total_score / len(actions), 1.0)
        else:
            drift_score = 0.0

        # Get recommendations
        recommendation = self._get_recommendations(drift_score)

        report = DriftReport(
            persona_name=persona_name,
            drift_score=drift_score,
            violations=list(set(violations)),  # Deduplicate
            recommendation=recommendation,
        )

        # Log if drift detected
        if drift_score >= 0.3:
            try:
                self._memory.log_event(
                    agent="drift_detector",
                    event_type="drift_detected",
                    payload={
                        "persona": persona_name,
                        "drift_score": round(drift_score, 3),
                        "violations": report.violations[:3],  # Top 3
                    },
                    tags=["drift", "monitoring"],
                )
            except Exception as e:
                log.debug(f"Failed to log drift to memory: {e}")

        return report

    def _score_action(
        self,
        action: Dict[str, Any],
        boundaries: List[str],
    ) -> float:
        """Score an action for drift (0.0-1.0).

        Args:
            action: Action dict
            boundaries: List of boundary rules

        Returns:
            Drift score for this action
        """
        action_type = action.get("type", "").lower()

        if not action_type:
            return 0.0

        # Check how many boundaries this action might violate
        violations_count = 0
        for boundary in boundaries:
            if self._boundary_matches_action(boundary, action_type):
                violations_count += 1

        # Score: 1.0 per violation, normalized per action
        if violations_count > 0:
            return min(violations_count * 0.25, 1.0)

        return 0.0

    def _detect_violations(
        self,
        action: Dict[str, Any],
        boundaries: List[str],
    ) -> List[str]:
        """Detect which boundaries an action violates.

        Args:
            action: Action dict
            boundaries: List of boundary rules

        Returns:
            List of violated boundary texts
        """
        action_type = action.get("type", "").lower()
        violations = []

        for boundary in boundaries:
            if self._boundary_matches_action(boundary, action_type):
                violations.append(boundary)

        return violations

    def _boundary_matches_action(self, boundary: str, action_type: str) -> bool:
        """Check if a boundary matches an action type.

        Args:
            boundary: Boundary rule text
            action_type: Action type (lowercase)

        Returns:
            True if boundary likely applies to action
        """
        boundary_lower = boundary.lower()

        # Check for explicit prohibitions
        if any(
            prohibition in boundary_lower
            for prohibition in ["never", "must not", "prohibit", "forbidden", "cannot"]
        ):
            # Check if action keywords are in the boundary
            for category, keywords in self._boundary_keywords.items():
                if any(kw in action_type for kw in keywords):
                    if any(kw in boundary_lower for kw in keywords):
                        return True

        return False

    def _get_recommendations(self, drift_score: float) -> str:
        """Get recommendation based on drift score.

        Args:
            drift_score: Score from 0.0-1.0

        Returns:
            Human-readable recommendation
        """
        if drift_score < 0.3:
            return "No action needed — persona alignment is nominal."

        elif drift_score < 0.6:
            return (
                "Monitor: Agent is drifting slightly from boundaries. "
                "Continue observation."
            )

        elif drift_score < 0.8:
            return (
                "Intervention: Agent has violated boundaries. "
                "Send warning and review recent actions."
            )

        else:
            return (
                "Shutdown: Agent has severely drifted. "
                "Escalate to Oracle for immediate intervention."
            )

    def get_threshold_actions(
        self,
        persona_name: str,
        actions: List[Dict[str, Any]],
        threshold: float = 0.6,
    ) -> List[Dict[str, Any]]:
        """Filter actions above drift threshold.

        Useful for identifying which specific actions triggered warnings.

        Args:
            persona_name: Persona name
            actions: List of actions
            threshold: Drift score threshold

        Returns:
            List of actions scoring above threshold
        """
        try:
            boundaries = self._memory.get_persona_boundaries(persona_name) or []
        except Exception:
            boundaries = []

        above_threshold = []
        for action in actions:
            score = self._score_action(action, boundaries)
            if score >= threshold:
                above_threshold.append({**action, "_drift_score": round(score, 3)})

        return above_threshold
