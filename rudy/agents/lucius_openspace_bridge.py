"""
Lucius ↔ OpenSpace Bridge — Session 27

Translates Lucius Scorer output into OpenSpace ExecutionAnalysis records,
feeding session quality signals into the skill evolution engine.

Flow:
    1. Lucius scores a session → score_result dict (0-100, 6 dimensions)
    2. This bridge converts that into an OpenSpace ExecutionAnalysis
    3. ExecutionAnalysis is persisted via SkillStore.record_analysis()
    4. OpenSpace uses this data to decide AUTO-FIX / AUTO-IMPROVE triggers

Design constraints:
    - Import isolation (C3): All non-stdlib imports inside function bodies.
    - Stateless: Bridge takes inputs, returns outputs. No side effects beyond DB writes.
    - Composable: Can be called from HandoffWriter, CLI, or scheduled tasks.

CLI:
    python -m rudy.agents.lucius_openspace_bridge [bridge|test]
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("lucius.openspace_bridge")


def lucius_to_execution_analysis(
    score_result: Dict[str, Any],
    skill_ids_used: Optional[List[str]] = None,
    task_description: str = "",
    session_number: int = 0,
) -> Dict[str, Any]:
    """Convert a Lucius score_session() result to an OpenSpace ExecutionAnalysis dict.

    The returned dict can be passed to ExecutionAnalysis.from_dict() for
    persistence via SkillStore.record_analysis().

    Args:
        score_result: Output of lucius_scorer.score_session(evidence).
        skill_ids_used: OpenSpace skill_ids that were used in this session.
            Maps to SkillJudgment entries. If None, no per-skill judgments.
        task_description: Human-readable session description for the execution_note.
        session_number: Session number for task_id generation.

    Returns:
        dict compatible with ExecutionAnalysis.from_dict().
    """
    total_score = score_result.get("total_score", 0)
    grade = score_result.get("grade", "F")
    dimensions = score_result.get("dimensions", {})
    evidence = score_result.get("evidence", {})
    scored_at = score_result.get("scored_at", datetime.now(timezone.utc).isoformat())

    # Task completion: grade C or better = completed
    task_completed = total_score >= 70

    # Build execution note from Lucius dimensions
    weak_dims = [
        f"{name} ({d['score']}/{d['max']})"
        for name, d in dimensions.items()
        if d.get("pct", 0) < 50
    ]
    strong_dims = [
        f"{name} ({d['score']}/{d['max']})"
        for name, d in dimensions.items()
        if d.get("pct", 0) >= 80
    ]

    note_parts = [
        f"Session {session_number} scored {total_score}/100 ({grade}).",
    ]
    if task_description:
        note_parts.append(f"Task: {task_description}")
    if strong_dims:
        note_parts.append(f"Strong: {', '.join(strong_dims)}")
    if weak_dims:
        note_parts.append(f"Weak: {', '.join(weak_dims)}")

    execution_note = " ".join(note_parts)

    # Tool issues: map Lucius findings to tool issue keys
    tool_issues = []
    if evidence.get("silent_dismissals", 0) > 0:
        tool_issues.append("silent_dismissals")
    if evidence.get("force_pushed", False):
        tool_issues.append("force_push")
    if not evidence.get("read_claude_md", False):
        tool_issues.append("missed_claude_md")

    # Build per-skill judgments
    skill_judgments = []
    if skill_ids_used:
        _skills_invoked = set(evidence.get("skills_invoked", []))
        _skills_recommended = set(evidence.get("skills_recommended", []))
        skills_utilization_pct = dimensions.get("skills_utilization", {}).get("pct", 0)

        for skill_id in skill_ids_used:
            # Determine if this skill was effectively applied
            # Use skills_utilization score as a proxy
            skill_applied = skills_utilization_pct >= 50

            # Build per-skill note
            skill_note_parts = []
            if skill_applied:
                skill_note_parts.append("Skill applied in session.")
            else:
                skill_note_parts.append("Skill registered but underutilized.")
            skill_note_parts.append(f"Session grade: {grade}")

            skill_judgments.append({
                "skill_id": skill_id,
                "skill_applied": skill_applied,
                "note": " ".join(skill_note_parts),
            })

    # Evolution suggestions based on score
    evolution_suggestions = []
    if total_score < 50:
        # Poor session — suggest FIX for any skills that were used
        for sj in skill_judgments:
            if not sj["skill_applied"]:
                evolution_suggestions.append({
                    "type": "fix",
                    "target_skills": [sj["skill_id"]],
                    "direction": f"Session scored {total_score}/100. Skill was not effectively applied. Review instructions for clarity and completeness.",
                })
    elif total_score >= 90:
        # Excellent session — suggest DERIVED to capture the winning pattern
        if skill_judgments:
            applied_ids = [sj["skill_id"] for sj in skill_judgments if sj["skill_applied"]]
            if applied_ids:
                evolution_suggestions.append({
                    "type": "captured",
                    "target_skills": [],
                    "direction": f"Session scored {total_score}/100 ({grade}). Capture the successful execution pattern for reuse.",
                })

    # Generate a unique task_id
    task_id = f"lucius-session-{session_number}-{uuid.uuid4().hex[:8]}"

    return {
        "task_id": task_id,
        "timestamp": scored_at,
        "task_completed": task_completed,
        "execution_note": execution_note,
        "tool_issues": tool_issues,
        "skill_judgments": skill_judgments,
        "evolution_suggestions": evolution_suggestions,
        "analyzed_by": "lucius_scorer",
        "analyzed_at": scored_at,
    }


async def record_lucius_score(
    score_result: Dict[str, Any],
    skill_ids_used: Optional[List[str]] = None,
    task_description: str = "",
    session_number: int = 0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert and persist a Lucius score into OpenSpace's SkillStore.

    This is the main entry point for the bridge. Call after score_session().

    Args:
        score_result: Output of lucius_scorer.score_session(evidence).
        skill_ids_used: OpenSpace skill_ids used in the session.
        task_description: Human-readable session description.
        session_number: Session number.
        db_path: Optional path to OpenSpace SQLite DB. If None, uses default.

    Returns:
        dict with status, task_id, and any evolution suggestions.
    """
    import os
    os.environ.setdefault("OPENSPACE_WORKSPACE", r"C:\Users\ccimi\OpenSpace")

    from openspace.skill_engine.types import ExecutionAnalysis
    from openspace.skill_engine.store import SkillStore

    # Convert Lucius score to OpenSpace analysis dict
    analysis_dict = lucius_to_execution_analysis(
        score_result=score_result,
        skill_ids_used=skill_ids_used,
        task_description=task_description,
        session_number=session_number,
    )

    # Deserialize into ExecutionAnalysis dataclass
    analysis = ExecutionAnalysis.from_dict(analysis_dict)

    # Persist
    store = SkillStore()
    await store.record_analysis(analysis)

    log.info(
        "Recorded Lucius score for session %d: %s/100 (%s) → task_id=%s",
        session_number,
        score_result.get("total_score", 0),
        score_result.get("grade", "?"),
        analysis.task_id,
    )

    return {
        "status": "recorded",
        "task_id": analysis.task_id,
        "total_score": score_result.get("total_score", 0),
        "grade": score_result.get("grade", "?"),
        "evolution_suggestions": len(analysis.evolution_suggestions),
        "skill_judgments": len(analysis.skill_judgments),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="Lucius ↔ OpenSpace Bridge — feed session scores into skill evolution"
    )
    parser.add_argument(
        "command",
        choices=["bridge", "test"],
        help="bridge: convert score JSON file | test: run with sample data",
    )
    parser.add_argument("--score-file", help="Path to Lucius score JSON (for bridge)")
    parser.add_argument("--skill-ids", nargs="*", help="OpenSpace skill_ids used")
    parser.add_argument("--session", type=int, default=0, help="Session number")
    parser.add_argument("--task", default="", help="Task description")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.command == "test":
        # Import Lucius scorer for a demo run
        from rudy.agents.lucius_scorer import score_session, empty_evidence

        # Simulate a decent session
        evidence = empty_evidence()
        evidence["read_claude_md"] = True
        evidence["ran_session_gate"] = True
        evidence["checked_briefing"] = True
        evidence["checked_capability_manifest"] = True
        evidence["skills_check_called"] = True
        evidence["skills_recommended"] = ["session-start"]
        evidence["skills_invoked"] = ["session-start"]
        evidence["handoff_written"] = True
        evidence["vault_record_written"] = True
        evidence["claude_md_updated"] = True
        evidence["continuation_prompt_included"] = True
        evidence["context_tags_count"] = 8
        evidence["substantive_responses"] = 10
        evidence["used_feature_branch"] = True
        evidence["pr_created"] = True
        evidence["session_number"] = 27

        score_result = score_session(evidence)

        # Convert to OpenSpace analysis
        analysis_dict = lucius_to_execution_analysis(
            score_result=score_result,
            skill_ids_used=["session-start__imp_1b06e320"],
            task_description="Session 27: OpenSpace integration",
            session_number=27,
        )

        if args.json:
            print(json.dumps(analysis_dict, indent=2, default=str))
        else:
            print(f"Score: {score_result['total_score']}/100 ({score_result['grade']})")
            print(f"Task ID: {analysis_dict['task_id']}")
            print(f"Completed: {analysis_dict['task_completed']}")
            print(f"Note: {analysis_dict['execution_note']}")
            print(f"Skill judgments: {len(analysis_dict['skill_judgments'])}")
            print(f"Evolution suggestions: {len(analysis_dict['evolution_suggestions'])}")

        # Also persist to DB
        result = asyncio.run(record_lucius_score(
            score_result=score_result,
            skill_ids_used=["session-start__imp_1b06e320"],
            task_description="Session 27: OpenSpace integration",
            session_number=27,
        ))
        print(f"\nDB Result: {json.dumps(result, indent=2)}")

    elif args.command == "bridge":
        if not args.score_file:
            parser.error("--score-file required for bridge command")

        score_result = json.loads(Path(args.score_file).read_text(encoding="utf-8"))
        result = asyncio.run(record_lucius_score(
            score_result=score_result,
            skill_ids_used=args.skill_ids or [],
            task_description=args.task,
            session_number=args.session,
        ))
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Recorded: {result['task_id']} — {result['total_score']}/100 ({result['grade']})")


if __name__ == "__main__":
    main()
