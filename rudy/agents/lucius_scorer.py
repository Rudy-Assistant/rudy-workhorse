"""
Lucius Scorer — Phase 3: Capability Maximization (ADR-004 v2.0)

Session compliance scoring on a nuanced 0-100 rubric.
Replaces the binary 100/0 compliance_score with multi-dimensional assessment.

Scoring dimensions:
    1. Start Protocol (20 pts) — Did the session read CLAUDE.md, run gate?
    2. Skills Utilization (20 pts) — Were recommended skills actually invoked?
    3. Handoff Quality (15 pts) — Proper handoff with context, vault write?
    4. Context Evaluation (15 pts) — Context % tracking maintained?
    5. Findings Tracked (15 pts) — Did findings get IDs, not silently dismissed?
    6. Branch Compliance (15 pts) — Feature branch + PR workflow followed?

Design constraints:
    - Import isolation (C3): All non-stdlib imports inside function bodies.
    - Stateless: Scorer takes evidence dict, returns score. No side effects.
    - Composable: Each dimension has its own scorer, combined at the end.

CLI:
    python -m rudy.agents.lucius_scorer [score|rubric]
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("lucius.scorer")


# ---------------------------------------------------------------------------
# Rubric definitions
# ---------------------------------------------------------------------------
RUBRIC = {
    "start_protocol": {
        "max_points": 20,
        "description": "Session start protocol compliance",
        "criteria": {
            "read_claude_md": {
                "points": 8,
                "description": "Read CLAUDE.md before doing any work",
            },
            "ran_session_gate": {
                "points": 6,
                "description": "Lucius session_start_gate() executed",
            },
            "checked_briefing": {
                "points": 3,
                "description": "Read session-briefing.md if available",
            },
            "checked_capability_manifest": {
                "points": 3,
                "description": "Consulted capability-manifest.json before building",
            },
        },
    },
    "skills_utilization": {
        "max_points": 20,
        "description": "Recommended skills actually invoked",
        "criteria": {
            "skills_recommended": {
                "points": 5,
                "description": "recommend_skills() was called with task context",
            },
            "skills_invoked_ratio": {
                "points": 15,
                "description": "Ratio of recommended skills that were actually used",
            },
        },
    },
    "handoff_quality": {
        "max_points": 15,
        "description": "Session handoff completeness",
        "criteria": {
            "handoff_written": {
                "points": 5,
                "description": "HandoffWriter.write() called before session end",
            },
            "vault_record": {
                "points": 4,
                "description": "Session record written to BatcaveVault",
            },
            "claude_md_updated": {
                "points": 3,
                "description": "CLAUDE.md updated with session changes",
            },
            "continuation_prompt": {
                "points": 3,
                "description": "Next-session bootstrap prompt included",
            },
        },
    },
    "context_evaluation": {
        "max_points": 15,
        "description": "Context window management",
        "criteria": {
            "context_tracking": {
                "points": 8,
                "description": "Context % appended to substantive responses",
            },
            "handoff_at_threshold": {
                "points": 7,
                "description": "Handoff initiated before context exhaustion",
            },
        },
    },
    "findings_tracked": {
        "max_points": 15,
        "description": "Finding capture protocol compliance",
        "criteria": {
            "findings_filed": {
                "points": 8,
                "description": "Discovered issues filed with IDs in tracker",
            },
            "no_silent_dismissals": {
                "points": 7,
                "description": "No findings silently ignored or rationalized away",
            },
        },
    },
    "branch_compliance": {
        "max_points": 15,
        "description": "Git workflow compliance",
        "criteria": {
            "feature_branch": {
                "points": 5,
                "description": "Work done on feature branch, not main",
            },
            "pr_workflow": {
                "points": 5,
                "description": "Changes submitted via PR with description",
            },
            "no_force_push": {
                "points": 5,
                "description": "No force pushes to protected branches",
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Evidence structure
# ---------------------------------------------------------------------------
def empty_evidence() -> dict:
    """Return an empty evidence template for session scoring.

    Fill this in during a session, then pass to score_session().
    """
    return {
        # Start protocol
        "read_claude_md": False,
        "ran_session_gate": False,
        "gate_result_passed": False,
        "checked_briefing": False,
        "checked_capability_manifest": False,

        # Skills utilization
        "skills_recommended": [],
        "skills_invoked": [],
        "skills_check_called": False,

        # Handoff quality
        "handoff_written": False,
        "vault_record_written": False,
        "claude_md_updated": False,
        "continuation_prompt_included": False,

        # Context evaluation
        "context_tags_count": 0,
        "substantive_responses": 0,
        "handoff_at_threshold": True,  # Assume true unless proven otherwise

        # Findings tracked
        "findings_discovered": 0,
        "findings_filed": 0,
        "silent_dismissals": 0,

        # Branch compliance
        "used_feature_branch": False,
        "pr_created": False,
        "force_pushed": False,

        # Metadata
        "session_number": 0,
        "session_start": None,
        "session_end": None,
    }


# ---------------------------------------------------------------------------
# Individual dimension scorers
# ---------------------------------------------------------------------------
def _score_start_protocol(evidence: dict) -> tuple[float, list[str]]:
    """Score start protocol compliance. Returns (score, notes)."""
    score = 0.0
    notes = []

    if evidence.get("read_claude_md"):
        score += 8
    else:
        notes.append("CLAUDE.md not read at session start (-8)")

    if evidence.get("ran_session_gate"):
        score += 6
    else:
        notes.append("Session gate not executed (-6)")

    if evidence.get("checked_briefing"):
        score += 3
    else:
        notes.append("Session briefing not checked (-3)")

    if evidence.get("checked_capability_manifest"):
        score += 3
    else:
        notes.append("Capability manifest not consulted (-3)")

    return score, notes


def _score_skills_utilization(evidence: dict) -> tuple[float, list[str]]:
    """Score skills utilization. Returns (score, notes)."""
    score = 0.0
    notes = []

    if evidence.get("skills_check_called"):
        score += 5
    else:
        notes.append("recommend_skills() not called (-5)")

    recommended = evidence.get("skills_recommended", [])
    invoked = evidence.get("skills_invoked", [])

    if recommended:
        ratio = len(set(invoked) & set(recommended)) / len(recommended)
        skill_score = ratio * 15
        score += skill_score
        if ratio < 0.5:
            unused = set(recommended) - set(invoked)
            notes.append(f"Skills recommended but not used: {', '.join(unused)}")
    else:
        # If no skills were recommended, give full credit (nothing to miss)
        score += 15

    return score, notes


def _score_handoff_quality(evidence: dict) -> tuple[float, list[str]]:
    """Score handoff quality. Returns (score, notes)."""
    score = 0.0
    notes = []

    if evidence.get("handoff_written"):
        score += 5
    else:
        notes.append("Handoff not written (-5)")

    if evidence.get("vault_record_written"):
        score += 4
    else:
        notes.append("Vault record not written (-4)")

    if evidence.get("claude_md_updated"):
        score += 3
    else:
        notes.append("CLAUDE.md not updated (-3)")

    if evidence.get("continuation_prompt_included"):
        score += 3
    else:
        notes.append("Continuation prompt missing (-3)")

    return score, notes


def _score_context_evaluation(evidence: dict) -> tuple[float, list[str]]:
    """Score context window management. Returns (score, notes)."""
    score = 0.0
    notes = []

    tags = evidence.get("context_tags_count", 0)
    responses = evidence.get("substantive_responses", 0)

    if responses > 0:
        ratio = tags / responses
        if ratio >= 0.8:
            score += 8
        elif ratio >= 0.5:
            score += 5
            notes.append(f"Context tags on {ratio:.0%} of responses (-3)")
        elif ratio >= 0.2:
            score += 2
            notes.append(f"Context tags on only {ratio:.0%} of responses (-6)")
        else:
            notes.append(f"Context tags rarely used ({tags}/{responses}) (-8)")
    else:
        # New session with no responses yet — no penalty
        score += 8

    if evidence.get("handoff_at_threshold", True):
        score += 7
    else:
        notes.append("Context exhausted before handoff (-7)")

    return score, notes


def _score_findings_tracked(evidence: dict) -> tuple[float, list[str]]:
    """Score findings capture compliance. Returns (score, notes)."""
    score = 0.0
    notes = []

    discovered = evidence.get("findings_discovered", 0)
    filed = evidence.get("findings_filed", 0)

    if discovered == 0:
        # No findings discovered — full credit
        score += 8
    elif filed >= discovered:
        score += 8
    else:
        ratio = filed / discovered if discovered else 0
        score += ratio * 8
        notes.append(f"Only {filed}/{discovered} findings filed (-{8 - ratio * 8:.0f})")

    dismissals = evidence.get("silent_dismissals", 0)
    if dismissals == 0:
        score += 7
    else:
        penalty = min(7, dismissals * 2)
        score += 7 - penalty
        notes.append(f"{dismissals} silent dismissals (-{penalty})")

    return score, notes


def _score_branch_compliance(evidence: dict) -> tuple[float, list[str]]:
    """Score git workflow compliance. Returns (score, notes)."""
    score = 0.0
    notes = []

    if evidence.get("used_feature_branch"):
        score += 5
    else:
        notes.append("Work not on feature branch (-5)")

    if evidence.get("pr_created"):
        score += 5
    else:
        notes.append("No PR created (-5)")

    if not evidence.get("force_pushed"):
        score += 5
    else:
        notes.append("Force push detected (-5)")

    return score, notes


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------
def score_session(evidence: dict) -> dict:
    """Score a session's compliance on the full rubric.

    Args:
        evidence: Dict of session evidence (see empty_evidence()).

    Returns:
        dict with:
            - total_score (0-100)
            - grade (A/B/C/D/F)
            - dimensions: per-dimension scores and notes
            - summary: human-readable one-liner
    """
    scorers = {
        "start_protocol": _score_start_protocol,
        "skills_utilization": _score_skills_utilization,
        "handoff_quality": _score_handoff_quality,
        "context_evaluation": _score_context_evaluation,
        "findings_tracked": _score_findings_tracked,
        "branch_compliance": _score_branch_compliance,
    }

    dimensions = {}
    total = 0.0

    for dim_name, scorer_fn in scorers.items():
        raw_score, notes = scorer_fn(evidence)
        max_pts = RUBRIC[dim_name]["max_points"]
        clamped = max(0, min(max_pts, raw_score))
        total += clamped

        dimensions[dim_name] = {
            "score": round(clamped, 1),
            "max": max_pts,
            "pct": round(clamped / max_pts * 100) if max_pts else 0,
            "notes": notes,
        }

    total = round(total, 1)

    # Grade assignment
    if total >= 90:
        grade = "A"
    elif total >= 80:
        grade = "B"
    elif total >= 70:
        grade = "C"
    elif total >= 60:
        grade = "D"
    else:
        grade = "F"

    # Summary
    weak_dims = [
        name for name, d in dimensions.items()
        if d["pct"] < 50
    ]
    if weak_dims:
        summary = f"Score: {total}/100 ({grade}). Weak areas: {', '.join(weak_dims)}"
    else:
        summary = f"Score: {total}/100 ({grade}). All dimensions healthy."

    return {
        "total_score": total,
        "grade": grade,
        "dimensions": dimensions,
        "summary": summary,
        "evidence": evidence,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


def format_score_report(score_result: dict) -> str:
    """Format a score result as markdown for session briefing or handoff."""
    lines = [
        "## Session Compliance Score",
        "",
        f"**{score_result['total_score']}/100 ({score_result['grade']})**",
        "",
        "| Dimension | Score | Notes |",
        "|-----------|-------|-------|",
    ]

    for dim_name, dim_data in score_result.get("dimensions", {}).items():
        label = RUBRIC[dim_name]["description"]
        notes = "; ".join(dim_data.get("notes", [])) or "✅"
        lines.append(
            f"| {label} | {dim_data['score']}/{dim_data['max']} | {notes} |"
        )

    lines.extend(["", f"*{score_result.get('summary', '')}*", ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Lucius Scorer — session compliance scoring"
    )
    parser.add_argument(
        "command",
        choices=["score", "rubric"],
        help="score: score from evidence JSON file | rubric: show rubric",
    )
    parser.add_argument("--evidence", help="Path to evidence JSON file (for score)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.command == "rubric":
        if args.json:
            print(json.dumps(RUBRIC, indent=2))
        else:
            total_max = sum(d["max_points"] for d in RUBRIC.values())
            print(f"Lucius Session Compliance Rubric ({total_max} points total)\n")
            for dim_name, dim in RUBRIC.items():
                print(f"  {dim['description']} ({dim['max_points']} pts)")
                for crit_name, crit in dim["criteria"].items():
                    print(f"    - {crit['description']} ({crit['points']} pts)")
                print()

    elif args.command == "score":
        if args.evidence:
            evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        else:
            # Demo with empty evidence (worst case)
            evidence = empty_evidence()

        result = score_session(evidence)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(format_score_report(result))


if __name__ == "__main__":
    main()
