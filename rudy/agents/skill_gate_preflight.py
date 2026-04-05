"""
Skill Gate Preflight -- Structural enforcement for S41/S104 skill invocation.

Problem: Alfred consistently fails to identify and invoke skills before
starting work. This has been documented as a systemic failure across
multiple sessions (S104, S108).

Solution: A preflight module that:
1. Reads the latest handoff file to extract session priorities
2. Maps priorities to matching Cowork/plugin skills using keyword matching
3. Writes the result to a coordination file that Alfred MUST reference
4. Integrates with session_start_gate() as an additional check

The coordination file (skill-gate-s{N}.json) serves as proof that
skill identification happened. The Lucius scorer already penalizes
sessions where skills_check_called is False.

Usage:
    from rudy.agents.skill_gate_preflight import run_skill_gate
    result = run_skill_gate(session_number=109)
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("lucius.skill_gate")

# Keyword-to-skill mapping. Each key is a pattern (case-insensitive)
# that maps to one or more skill names from Cowork/plugins.
SKILL_KEYWORD_MAP: dict[str, list[str]] = {
    r"pr|pull.request|merge|ci|lint": [
        "engineering:code-review",
    ],
    r"architect|adr|design|system.design": [
        "engineering:architecture",
        "engineering:system-design",
    ],
    r"debug|error|stack.trace|traceback": [
        "engineering:debug",
    ],
    r"test|e2e|validation|verify": [
        "engineering:testing-strategy",
    ],
    r"deploy|release|ship": [
        "engineering:deploy-checklist",
    ],
    r"doc|readme|runbook|documentation": [
        "engineering:documentation",
    ],
    r"standup|update|status": [
        "engineering:standup",
        "operations:status-report",
    ],
    r"incident|outage|production.down": [
        "engineering:incident-response",
    ],
    r"robin|stall|recovery|nightwatch": [
        "engineering:debug",
        "engineering:testing-strategy",
    ],
    r"skill|evolution|openspace|r.006": [
        "engineering:architecture",
        "engineering:testing-strategy",
    ],
    r"cleanup|stale|delete|prune": [
        "operations:process-optimization",
    ],
}


def _get_latest_handoff(session_number: int) -> Path | None:
    """Find the handoff file for the previous session."""
    from rudy.paths import REPO_ROOT
    handoff_dir = REPO_ROOT / "vault" / "Handoffs"
    # Look for the previous session's handoff
    prev = session_number - 1
    candidate = handoff_dir / f"Session-{prev}-Handoff.md"
    if candidate.exists():
        return candidate
    return None


def _extract_priorities(handoff_path: Path) -> list[str]:
    """Extract priority items from handoff markdown."""
    text = handoff_path.read_text(encoding="utf-8")
    priorities: list[str] = []
    in_priority = False
    for line in text.splitlines():
        if "priority" in line.lower() and "next session" in line.lower():
            in_priority = True
            continue
        if in_priority:
            if line.startswith("#") or (line.strip() == "" and priorities):
                if priorities:
                    break
            stripped = line.strip()
            if stripped and (stripped[0].isdigit() or stripped.startswith("-")):
                priorities.append(stripped)
    return priorities


def match_skills(priorities: list[str]) -> dict[str, list[str]]:
    """Match priority text against skill keyword map.

    Returns dict mapping each priority to a list of matched skill names.
    """
    results: dict[str, list[str]] = {}
    for priority in priorities:
        matched: list[str] = []
        priority_lower = priority.lower()
        for pattern, skills in SKILL_KEYWORD_MAP.items():
            if re.search(pattern, priority_lower):
                for s in skills:
                    if s not in matched:
                        matched.append(s)
        results[priority] = matched
    return results


def _coordination_path(session_number: int) -> Path:
    """Return path for skill gate coordination file."""
    from rudy.paths import RUDY_DATA
    return RUDY_DATA / "coordination" / f"skill-gate-s{session_number}.json"


def run_skill_gate(
    session_number: int,
    extra_context: str = "",
) -> dict[str, Any]:
    """Run the skill gate preflight.

    1. Read previous handoff to extract priorities
    2. Match priorities to skills
    3. Write coordination file
    4. Return result for Alfred to act on

    Args:
        session_number: Current session number.
        extra_context: Additional text to match skills against.

    Returns:
        dict with matched skills, priorities, and file path.
    """
    handoff = _get_latest_handoff(session_number)
    priorities: list[str] = []
    if handoff:
        priorities = _extract_priorities(handoff)
        log.info("Extracted %d priorities from %s", len(priorities), handoff.name)
    else:
        log.warning("No handoff found for session %d", session_number - 1)

    # Add extra context as a virtual priority for matching
    if extra_context:
        priorities.append(extra_context)

    skill_matches = match_skills(priorities)

    # Flatten unique skills
    all_skills: list[str] = []
    for skills in skill_matches.values():
        for s in skills:
            if s not in all_skills:
                all_skills.append(s)

    # Top 3 recommendations
    top_skills = all_skills[:3]

    result = {
        "session_number": session_number,
        "priorities_found": len(priorities),
        "priorities": priorities,
        "skill_matches": skill_matches,
        "top_skills": top_skills,
        "all_matched_skills": all_skills,
        "gate_passed": len(top_skills) > 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instruction": (
            "Alfred MUST invoke at least one of top_skills before "
            "starting work. Log which skills were actually invoked "
            "in the session handoff under 'Skill Invocation Log'."
        ),
    }

    # Write coordination file
    coord_path = _coordination_path(session_number)
    coord_path.parent.mkdir(parents=True, exist_ok=True)
    coord_path.write_text(
        json.dumps(result, indent=2, default=str),
        encoding="utf-8",
    )
    log.info(
        "Skill gate wrote %d recommendations to %s",
        len(top_skills), coord_path.name,
    )

    return result
