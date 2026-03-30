"""
rudy.workflows.pr_review — Lucius-gated PR review workflow.

Alfred calls this before merging any PR. Lucius reviews the diff and
returns a structured verdict. If HIGH-severity findings exist, the
merge is blocked and findings are reported.

Usage (from Alfred's Cowork session):
    from rudy.workflows.pr_review import review_pr_branch, review_diff_text

    # Option A: Review a branch against main
    result = review_pr_branch("alfred/my-feature")
    if result["verdict"] == "approve":
        # Safe to merge
    else:
        # Report findings to Batman

    # Option B: Review raw diff text (sandbox mode)
    result = review_diff_text(diff_text, branch="alfred/my-feature")

CLI (from Oracle):
    python -m rudy.workflows.pr_review alfred/my-feature
"""

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rudy.paths import REPO_ROOT, RUDY_DATA, GIT_EXE

log = logging.getLogger("rudy.workflows.pr_review")


def review_diff_text(diff_text: str, branch: str = "unknown") -> dict:
    """Run Lucius review_diff on raw diff text.

    Args:
        diff_text: Git diff output (unified format)
        branch: Branch name for the review record

    Returns:
        dict with keys: verdict, findings_count, high_severity, findings, review_id
    """
    from rudy.agents.lucius_fox import LuciusFox

    lucius = LuciusFox()
    record = lucius._review_diff(diff_text, branch=branch)
    return record


def review_pr_branch(branch: str, base: str = "main") -> dict:
    """Review a PR branch by diffing it against base.

    Runs `git diff base...branch` and feeds the output through Lucius.
    Works when called from inside the repo (Oracle or sandbox clone).

    Args:
        branch: Feature branch name (e.g. "alfred/my-feature")
        base: Base branch to diff against (default: "main")

    Returns:
        dict with: verdict, findings_count, high_severity, findings,
                   review_id, branch, base, diff_stats
    """
    log.info(f"Reviewing PR: {branch} -> {base}")

    # Fetch latest to ensure we have both branches
    _run_git("fetch origin", timeout=60)

    # Get the diff
    ok, diff_text = _run_git(f"diff origin/{base}...origin/{branch}")
    if not ok:
        # Fallback: try local branches
        ok, diff_text = _run_git(f"diff {base}...{branch}")
        if not ok:
            return {
                "verdict": "error",
                "error": f"Could not generate diff for {branch} against {base}",
                "findings_count": 0,
                "high_severity": 0,
                "findings": [],
            }

    # Get diff stats for the summary
    _, diff_stats = _run_git(f"diff --stat origin/{base}...origin/{branch}")

    # Run Lucius review
    record = review_diff_text(diff_text, branch=branch)
    record["base"] = base
    record["diff_stats"] = diff_stats or ""

    # Log verdict
    verdict = record.get("verdict", "unknown")
    high = record.get("high_severity", 0)
    total = record.get("findings_count", 0)

    if verdict == "approve":
        log.info(f"APPROVED: {branch} ({total} findings, 0 high)")
    else:
        log.warning(f"CHANGES REQUESTED: {branch} ({total} findings, {high} high)")

    return record


def format_review_report(record: dict) -> str:
    """Format a Lucius review record into a human-readable report.

    Returns a markdown-formatted string suitable for PR comments or
    Alfred's session output.
    """
    verdict = record.get("verdict", "unknown")
    branch = record.get("branch", "unknown")
    review_id = record.get("review_id", "unknown")
    high = record.get("high_severity", 0)
    total = record.get("findings_count", 0)
    findings = record.get("findings", [])

    icon = "APPROVED" if verdict == "approve" else "CHANGES REQUESTED"

    lines = [
        f"## Lucius Review: {icon}",
        f"**Review ID:** {review_id}",
        f"**Branch:** {branch}",
        f"**Findings:** {total} total, {high} high severity",
        "",
    ]

    if findings:
        # Group by severity
        by_severity = {}
        for f in findings:
            sev = f.get("severity", "unknown")
            by_severity.setdefault(sev, []).append(f)

        for sev in ["high", "medium", "low", "info"]:
            if sev in by_severity:
                lines.append(f"### {sev.upper()} ({len(by_severity[sev])})")
                for f in by_severity[sev]:
                    lines.append(f"- **{f.get('title', 'Finding')}**: {f.get('detail', '')}")
                    if f.get("recommendation"):
                        lines.append(f"  _Recommendation:_ {f['recommendation']}")
                lines.append("")

    if record.get("diff_stats"):
        lines.append("### Diff Stats")
        lines.append(f"```\n{record['diff_stats']}\n```")

    return "\n".join(lines)


def _run_git(args: str, timeout: int = 30) -> tuple[bool, str]:
    """Run a git command in the repo root."""
    try:
        cmd = f'"{GIT_EXE}" {args}' if " " in GIT_EXE else f"{GIT_EXE} {args}"
        r = subprocess.run(
            cmd,
            shell=True, capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=timeout
        )
        return r.returncode == 0, r.stdout
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m rudy.workflows.pr_review <branch> [base]")
        print("Example: python -m rudy.workflows.pr_review alfred/my-feature main")
        sys.exit(1)

    branch = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else "main"

    result = review_pr_branch(branch, base)
    report = format_review_report(result)
    print(report)

    # Exit with non-zero if changes requested
    if result.get("verdict") != "approve":
        sys.exit(1)
