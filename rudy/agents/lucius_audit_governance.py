"""
Lucius Fox — Governance Audits (ADR-005 Phase 2b, S74).

Extracted from lucius_fox.py: agent health, documentation, branch governance.
Backward-compat: LuciusFox thin wrappers delegate here.
"""

import subprocess

from datetime import datetime
from pathlib import Path

from rudy.paths import BATCAVE_VAULT


def audit_agent_health(
    known_agents: list,
    read_status_fn,
    log=None,
) -> list:
    """Check status of all known agents.

    Args:
        known_agents: list of agent name strings
        read_status_fn: callable(agent_name) -> dict with status info

    Returns:
        list of finding dicts
    """
    if log:
        log.info("Auditing agent health...")
    findings = []

    for agent_name in known_agents:
        status = read_status_fn(agent_name)
        if status.get("status") == "unknown":
            findings.append({
                "type": "agent_status",
                "severity": "low",
                "title": f"Agent '{agent_name}' has no status file",
                "detail": "Either never run or status file missing",
                "recommendation": "Verify agent is scheduled and functioning",
            })
        elif status.get("status") == "error":
            findings.append({
                "type": "agent_error",
                "severity": "high",
                "title": f"Agent '{agent_name}' in error state",
                "detail": (
                    f"Last run: {status.get('last_run')}. "
                    f"Alerts: {status.get('critical_alerts', [])}"
                ),
                "recommendation": "Investigate crash dumps and fix root cause",
            })
        else:
            last_run = status.get("last_run", "")
            if last_run:
                try:
                    lr = datetime.fromisoformat(last_run)
                    age_hours = (
                        (datetime.now() - lr).total_seconds() / 3600
                    )
                    if age_hours > 24:
                        findings.append({
                            "type": "agent_stale",
                            "severity": "medium",
                            "title": (
                                f"Agent '{agent_name}' stale "
                                f"({age_hours:.0f}h since last run)"
                            ),
                            "detail": f"Last run: {last_run}",
                            "recommendation": (
                                "Check Task Scheduler or trigger manual run"
                            ),
                        })
                except (ValueError, TypeError):
                    pass

    return findings


# Required documentation entries (moved from lucius_fox.py constants)
REQUIRED_DOCS = [
    ("CLAUDE.md", "Institutional memory"),
    ("README.md", "Project README"),
    ("SOLE-SURVIVOR-PROTOCOL.md", "Recovery protocol"),
    ("docs/SESSION-HANDOFF.md", "Session handoff brief"),
]


def audit_documentation(codebase_root: Path, log=None) -> list:
    """Check documentation freshness and completeness.

    Returns:
        list of finding dicts
    """
    if log:
        log.info("Auditing documentation...")
    findings = []

    for rel_path, desc in REQUIRED_DOCS:
        path = codebase_root / rel_path
        if path.exists():
            age_hours = (
                datetime.now()
                - datetime.fromtimestamp(path.stat().st_mtime)
            ).total_seconds() / 3600
            lines = path.read_text(errors="replace").count("\n")
            if age_hours > 168:  # 1 week
                findings.append({
                    "type": "doc_stale",
                    "severity": "medium",
                    "title": (
                        f"{desc} is stale ({age_hours / 24:.0f} days old)"
                    ),
                    "detail": (
                        f"{rel_path}: {lines} lines, "
                        f"last modified {age_hours / 24:.0f}d ago"
                    ),
                    "recommendation": "Review and update documentation",
                })
        else:
            findings.append({
                "type": "doc_missing",
                "severity": "high" if "README" in rel_path else "medium",
                "title": f"Missing documentation: {desc}",
                "detail": f"Expected at {rel_path}",
                "recommendation": "Create this documentation",
            })

    # Also check BatcaveVault
    vault_home = BATCAVE_VAULT / "Home.md"
    if not vault_home.exists():
        findings.append({
            "type": "doc_missing",
            "severity": "medium",
            "title": "BatcaveVault Home.md missing",
            "detail": f"Expected at {vault_home}",
            "recommendation": "Initialize BatcaveVault with Home.md",
        })

    return findings


# Protected branches (shared with lucius_fox.py)
PROTECTED_BRANCHES = frozenset({"main", "master"})


def audit_branches(codebase_root: Path, log=None, warn_fn=None) -> tuple:
    """Audit git branch state -- stale branches and governance.

    Returns:
        (result_dict, findings_list)
    """
    if log:
        log.info("Auditing branch governance...")
    result = {"branches": [], "warnings": []}
    findings = []

    try:
        git_result = subprocess.run(
            [
                "git", "branch", "-a",
                "--format=%(refname:short) %(committerdate:iso8601)",
            ],
            capture_output=True, text=True,
            cwd=str(codebase_root),
            timeout=30, encoding="utf-8", errors="replace",
        )
        if git_result.returncode != 0:
            if warn_fn:
                warn_fn(f"git branch failed: {git_result.stderr}")
            return result, findings

        for line in git_result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip().split(" ", 1)
            branch_name = parts[0]
            result["branches"].append(branch_name)
            date_str = parts[1] if len(parts) > 1 else ""
            if date_str and branch_name not in PROTECTED_BRANCHES:
                try:
                    branch_date = datetime.fromisoformat(
                        date_str.strip().replace(" ", "T")[:19]
                    )
                    age_days = (datetime.now() - branch_date).days
                    if age_days > 7:
                        findings.append({
                            "type": "stale_branch",
                            "severity": "low",
                            "title": (
                                f"Stale branch: {branch_name} "
                                f"({age_days}d old)"
                            ),
                            "detail": f"Last commit: {date_str}",
                            "recommendation": (
                                "Merge or delete if no longer needed"
                            ),
                        })
                except (ValueError, TypeError):
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        if warn_fn:
            warn_fn(f"Git not available for branch audit: {e}")

    return result, findings
