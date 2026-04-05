"""
Lucius Directive Consumer -- R-006 Priority 3 (Session 106).

Reads lucius-directives.json and executes AUTO-FIX and AUTO-IMPROVE
actions. Generates actionable recommendations for Alfred sessions.

Design: Lucius recommends, Alfred acts. The consumer produces
structured action plans rather than directly modifying files.

Entry point: consume_directives()
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("lucius.directive_consumer")


def _get_directives_path() -> Path:
    """Return canonical path to lucius-directives.json."""
    from rudy.paths import RUDY_DATA
    return Path(RUDY_DATA) / "coordination" / "lucius-directives.json"


def _get_actions_path() -> Path:
    """Return canonical path to lucius-actions.json (output)."""
    from rudy.paths import RUDY_DATA
    return Path(RUDY_DATA) / "coordination" / "lucius-actions.json"


def load_active_directives(
    directives_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Load directives with status 'active' from lucius-directives.json."""
    path = directives_path or _get_directives_path()
    if not path.exists():
        log.info("No directives file at %s", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [d for d in data.get("directives", [])
                if d.get("status") == "active"]
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to read directives: %s", e)
        return []


def _handle_auto_fix(directive: dict[str, Any]) -> dict[str, Any]:
    """Generate action plan for AUTO-FIX directive.

    AUTO-FIX fires when skill utilization is low. The action plan
    identifies which skills to review and suggests improvements.
    """
    sessions = directive.get("sessions_analyzed", [])
    pct = directive.get("score_pct", 0)
    return {
        "directive_id": directive["id"],
        "action_type": "skill_review",
        "priority": "high" if pct < 25 else "medium",
        "recommendations": [
            "Review skill trigger descriptions for clarity",
            "Check if skill names match common task vocabulary",
            "Consider consolidating overlapping skills",
            "Verify skill instructions are actionable (not just descriptive)",
            "Add examples to skill descriptions for better matching",
        ],
        "context": {
            "utilization_pct": pct,
            "sessions_analyzed": sessions,
            "dimension": directive.get("dimension", "unknown"),
        },
        "apply_to": "CLAUDE.md skill invocation gate + .claude/skills/",
    }


def _handle_auto_improve(directive: dict[str, Any]) -> dict[str, Any]:
    """Generate action plan for AUTO-IMPROVE directive.

    AUTO-IMPROVE fires when multiple sessions score 90+. The action
    plan captures what made those sessions successful.
    """
    strong_dims = directive.get("strong_dimensions", [])
    high_sessions = directive.get("high_scoring_sessions", [])
    return {
        "directive_id": directive["id"],
        "action_type": "pattern_capture",
        "priority": "low",
        "recommendations": [
            f"Document winning patterns from sessions {high_sessions}",
            f"Strong dimensions to preserve: {', '.join(strong_dims)}",
            "Add successful patterns to CLAUDE.md engineering principles",
            "Create skill templates from high-scoring session workflows",
            "Update boot protocol with newly validated practices",
        ],
        "context": {
            "high_scoring_sessions": high_sessions,
            "strong_dimensions": strong_dims,
            "score_pct": directive.get("score_pct", 0),
        },
        "apply_to": "CLAUDE.md engineering principles + vault/Protocols/",
    }


def _handle_standard(directive: dict[str, Any]) -> dict[str, Any]:
    """Generate action plan for standard directives (targeted_fix, etc)."""
    severity = directive.get("severity", "advisory")
    return {
        "directive_id": directive["id"],
        "action_type": "session_recommendation",
        "priority": "critical" if severity == "critical" else "medium",
        "recommendations": [
            directive.get("directive", "Review this dimension"),
        ],
        "context": {
            "severity": severity,
            "dimension": directive.get("dimension", "unknown"),
            "score_pct": directive.get("score_pct", 0),
            "session": directive.get("session", 0),
        },
        "apply_to": "next Alfred session priorities",
    }


HANDLERS = {
    "auto_fix": _handle_auto_fix,
    "auto_improve": _handle_auto_improve,
}


def _mark_consumed(
    directives_path: Path,
    consumed_ids: list[str],
) -> None:
    """Mark directives as consumed in lucius-directives.json."""
    if not directives_path.exists():
        return
    try:
        data = json.loads(directives_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    now = datetime.now(timezone.utc).isoformat()
    for d in data.get("directives", []):
        if d.get("id") in consumed_ids:
            d["status"] = "consumed"
            d["consumed_at"] = now
    data["last_updated"] = now
    directives_path.write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )
    log.info("Marked %d directives as consumed", len(consumed_ids))


def consume_directives(
    directives_path: Optional[Path] = None,
    actions_path: Optional[Path] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Main entry point: read active directives and produce action plans.

    Args:
        directives_path: Override for lucius-directives.json location.
        actions_path: Override for lucius-actions.json output.
        dry_run: If True, don't mark directives as consumed.

    Returns:
        Consumption report with action plans and summary.
    """
    d_path = directives_path or _get_directives_path()
    a_path = actions_path or _get_actions_path()

    active = load_active_directives(d_path)
    if not active:
        log.info("No active directives to consume")
        return {"consumed": 0, "actions": [], "status": "idle"}

    actions = []
    consumed_ids = []

    for directive in active:
        trigger = directive.get("trigger", directive.get("type", "unknown"))
        handler = HANDLERS.get(trigger, _handle_standard)
        try:
            action = handler(directive)
            action["consumed_from"] = directive["id"]
            action["created_at"] = datetime.now(timezone.utc).isoformat()
            actions.append(action)
            consumed_ids.append(directive["id"])
        except Exception as e:
            log.warning("Failed to consume directive %s: %s",
                        directive.get("id"), e)

    # Write action plans
    report = {
        "consumed": len(consumed_ids),
        "actions": actions,
        "status": "actions_generated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(d_path),
    }

    a_path.parent.mkdir(parents=True, exist_ok=True)
    a_path.write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    log.info("Wrote %d actions to %s", len(actions), a_path)


    # Mark consumed (unless dry run)
    if not dry_run and consumed_ids:
        _mark_consumed(d_path, consumed_ids)

    return report
