"""
Skill Evolution Triggers — Session 104 (R-006 Priority 2).

Scans historical bridge results in coordination/ to detect patterns
that warrant AUTO-FIX or AUTO-IMPROVE actions on skills.

Triggers:
    AUTO-FIX:    Skill <50% utilization across 3+ sessions.
    AUTO-IMPROVE: Capture winning patterns from 90+ scoring sessions.

Called from full_feedback_loop() in lucius_openspace_bridge.py.

Design constraints:
    - Import isolation (C3): Non-stdlib imports inside functions.
    - Reads from JSON files in coordination/ (no SkillStore query needed).
    - Results appended to lucius-directives.json.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("lucius.evolution_triggers")


# Thresholds (configurable)
AUTO_FIX_SESSIONS = 3       # Sessions of underutilization before fix
AUTO_FIX_UTIL_PCT = 50      # Below this % = underutilized
AUTO_IMPROVE_SCORE = 90     # Score threshold for pattern capture
AUTO_IMPROVE_MIN_SESSIONS = 2  # Min 90+ sessions to trigger


def _load_bridge_results(coord_dir: Path) -> list[dict[str, Any]]:
    """Load all openspace-bridge-s*.json results, sorted by session."""
    results = []
    for f in sorted(coord_dir.glob("openspace-bridge-s*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to read %s: %s", f.name, e)
    return results


def _load_score_files(coord_dir: Path) -> list[dict[str, Any]]:
    """Load all score JSON files for dimension analysis."""
    scores = []
    for f in sorted(coord_dir.glob("*-score-s*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            scores.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return scores


def check_auto_fix(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect skills needing AUTO-FIX.

    Trigger: skill utilization < AUTO_FIX_UTIL_PCT across
    AUTO_FIX_SESSIONS consecutive sessions.

    Returns list of fix directives.
    """
    if len(scores) < AUTO_FIX_SESSIONS:
        return []

    directives = []
    # Check the last N sessions for skill utilization dimension
    recent = scores[-AUTO_FIX_SESSIONS:]
    low_util_streak = 0

    for score in recent:
        dims = score.get("dimensions", {})
        skill_dim = dims.get("skills_utilization", {})
        pct = skill_dim.get("pct", 100)  # Default high if missing
        if pct < AUTO_FIX_UTIL_PCT:
            low_util_streak += 1

    if low_util_streak >= AUTO_FIX_SESSIONS:
        last_session = recent[-1].get("evidence", {}).get(
            "session_number", 0
        )
        directives.append({
            "id": f"EVO-AUTOFIX-S{last_session}",
            "type": "auto_fix",
            "severity": "warning",
            "dimension": "skills_utilization",
            "score_pct": pct,
            "directive": (
                f"AUTO-FIX: Skill utilization below {AUTO_FIX_UTIL_PCT}% "
                f"for {AUTO_FIX_SESSIONS}+ consecutive sessions. "
                f"Review skill instructions for clarity. Consider: "
                f"(a) Are skill triggers matching actual tasks? "
                f"(b) Are instructions actionable? "
                f"(c) Should skills be consolidated or split?"
            ),
            "trigger": "auto_fix",
            "sessions_analyzed": [
                s.get("evidence", {}).get("session_number", 0)
                for s in recent
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        })

    return directives


def check_auto_improve(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect sessions warranting AUTO-IMPROVE pattern capture.

    Trigger: AUTO_IMPROVE_MIN_SESSIONS sessions scored 90+.
    Action: Generate directive to capture the winning execution
    pattern as a reusable skill template.

    Returns list of improve directives.
    """
    high_sessions = [
        s for s in scores
        if s.get("total_score", 0) >= AUTO_IMPROVE_SCORE
    ]

    if len(high_sessions) < AUTO_IMPROVE_MIN_SESSIONS:
        return []

    directives = []
    # Extract common patterns from high-scoring sessions
    strong_dims: dict[str, int] = {}
    for s in high_sessions:
        for name, d in s.get("dimensions", {}).items():
            if d.get("pct", 0) >= 80:
                strong_dims[name] = strong_dims.get(name, 0) + 1

    # Find consistently strong dimensions
    consistent = [
        name for name, count in strong_dims.items()
        if count >= AUTO_IMPROVE_MIN_SESSIONS
    ]

    last_session = high_sessions[-1].get("evidence", {}).get(
        "session_number", 0
    )
    directives.append({
        "id": f"EVO-IMPROVE-S{last_session}",
        "type": "auto_improve",
        "severity": "healthy",
        "dimension": "overall",
        "score_pct": high_sessions[-1].get("total_score", 0),
        "directive": (
            f"AUTO-IMPROVE: {len(high_sessions)} sessions scored 90+. "
            f"Consistently strong dimensions: "
            f"{', '.join(consistent) if consistent else 'varied'}. "
            f"Action: Capture the execution patterns from these "
            f"sessions as reusable skill templates or CLAUDE.md "
            f"amendments. Extract what made these sessions successful."
        ),
        "trigger": "auto_improve",
        "high_scoring_sessions": [
            s.get("evidence", {}).get("session_number", 0)
            for s in high_sessions
        ],
        "strong_dimensions": consistent,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    })

    return directives


def evaluate_evolution_triggers(
    coord_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Main entry point: scan coordination/ and return evolution directives.

    Called from full_feedback_loop() in lucius_openspace_bridge.py.

    Args:
        coord_dir: Path to coordination directory. Uses default if None.

    Returns:
        List of evolution directive dicts (AUTO-FIX and AUTO-IMPROVE).
    """
    if coord_dir is None:
        from rudy.paths import RUDY_DATA
        coord_dir = Path(RUDY_DATA) / "coordination"
    else:
        coord_dir = Path(coord_dir)

    if not coord_dir.exists():
        log.info("Coordination dir not found: %s", coord_dir)
        return []

    scores = _load_score_files(coord_dir)
    if not scores:
        log.info("No score files found in %s", coord_dir)
        return []

    log.info("Evaluating evolution triggers across %d scores", len(scores))

    directives = []
    directives.extend(check_auto_fix(scores))
    directives.extend(check_auto_improve(scores))

    if directives:
        log.info(
            "Evolution triggers fired: %d directives",
            len(directives),
        )
    else:
        log.info("No evolution triggers fired.")

    return directives
