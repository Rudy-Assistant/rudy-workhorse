#!/usr/bin/env python3
"""
First Delegation Batch — 10 tasks Alfred delegates to Robin.

These are tasks Alfred currently handles that Robin can own,
using the skills created in the P2 mentorship sprint.

Usage:
    python delegation_batch.py list          # Show all delegation candidates
    python delegation_batch.py send          # Send batch via peers_delegation
    python delegation_batch.py dry-run       # Show what would be sent
"""

import json
import sys
from datetime import datetime, timezone

# The First Ten — tasks moving from Alfred to Robin
DELEGATION_BATCH = [
    {
        "id": "D001",
        "title": "Nightly system health check",
        "task_type": "health_check",
        "skill": "system-health-check",
        "priority": "high",
        "description": (
            "Run system vitals every 4 hours: CPU, RAM, disk, "
            "critical services (sshd, Ollama, Task Scheduler), "
            "uptime, and network connectivity. Log to vault."
        ),
        "schedule": "every 4 hours",
        "alfred_was": "Checking system state at session start",
        "robin_advantage": "Persistent local presence, no token cost",
    },
    {
        "id": "D002",
        "title": "Service recovery — auto-restart critical services",
        "task_type": "health_check",
        "skill": "service-monitor",
        "priority": "critical",
        "description": (
            "Monitor sshd, Ollama, and peers broker. If any go down, "
            "attempt auto-restart. Log recovery to sentinel immune memory. "
            "Escalate to Alfred only if restart fails twice."
        ),
        "schedule": "every 5 minutes",
        "alfred_was": "Discovering services down at session start",
        "robin_advantage": "Immediate detection + recovery, no internet needed",
    },
    {
        "id": "D003",
        "title": "Git branch cleanup",
        "task_type": "git",
        "skill": "git-operations",
        "priority": "low",
        "description": (
            "List merged branches, delete local branches that have been "
            "merged to main. Keep alfred/* branches for 7 days after merge. "
            "Run weekly."
        ),
        "schedule": "weekly (Sunday 2 AM)",
        "alfred_was": "Manual branch cleanup during sessions",
        "robin_advantage": "Runs automatically, no session needed",
    },
]
DELEGATION_BATCH += [
    {
        "id": "D004",
        "title": "Code quality gate — pre-PR lint check",
        "task_type": "code_quality",
        "skill": "code-lint",
        "priority": "medium",
        "description": (
            "Before any PR is created, run ruff check + ruff format --check "
            "on all changed files. Auto-fix safe issues (F841, F401, E501). "
            "Report findings to Alfred via peers-mcp."
        ),
        "schedule": "on-demand (triggered by Alfred)",
        "alfred_was": "Running lint manually, sometimes forgetting",
        "robin_advantage": "Consistent, never forgets, instant feedback",
    },
    {
        "id": "D005",
        "title": "Security sweep — daily scan",
        "task_type": "security_scan",
        "skill": "security-sweep",
        "priority": "high",
        "description": (
            "Daily security audit: open ports, Defender status, firewall rules, "
            "failed login attempts, suspicious processes, autostart programs, "
            "Tailscale mesh. Escalate any HIGH or CRITICAL findings immediately."
        ),
        "schedule": "daily (4 AM)",
        "alfred_was": "Sporadic security checks when remembered",
        "robin_advantage": "Consistent daily cadence, immediate escalation",
    },
    {
        "id": "D006",
        "title": "Registry snapshot verification",
        "task_type": "audit",
        "skill": "system-audit",
        "priority": "medium",
        "description": (
            "After nightly registry snapshot (3 AM), verify the snapshot "
            "completed successfully. Check registry.json freshness, compare "
            "module count against previous snapshot. Alert on regressions."
        ),
        "schedule": "daily (3:15 AM, after snapshot task)",
        "alfred_was": "Checking registry.json manually at session start",
        "robin_advantage": "Automated verification, catches issues overnight",
    },
    {
        "id": "D007",
        "title": "PR creation from staged commits",
        "task_type": "git",
        "skill": "git-operations",
        "priority": "medium",
        "description": (
            "When Alfred pushes a branch, Robin creates the PR using gh CLI. "
            "Uses standard PR template with summary, test plan, and co-author tag. "
            "This is the exact task that burned tokens in Session 27."
        ),
        "schedule": "on-demand (triggered by Alfred via peers-mcp)",
        "alfred_was": "Fighting with gh CLI quoting on Windows",
        "robin_advantage": "Local execution, no quoting issues, instant",
    },
]
DELEGATION_BATCH += [
    {
        "id": "D008",
        "title": "Daily briefing preparation",
        "task_type": "report",
        "skill": "generate-report",
        "priority": "medium",
        "description": (
            "Before Batman's expected wake time, compile a daily briefing: "
            "overnight health status, security findings, task queue state, "
            "Alfred session summary (if any), and pending items. "
            "Save to vault/reports/."
        ),
        "schedule": "daily (7 AM)",
        "alfred_was": "Generating reports ad-hoc during sessions",
        "robin_advantage": "Ready before Batman wakes, proactive",
    },
    {
        "id": "D009",
        "title": "Email triage — read and categorize inbox",
        "task_type": "browse",
        "skill": "bruce-proxy",
        "priority": "medium",
        "description": (
            "Open Gmail via browser, read subject lines and senders, "
            "categorize as: urgent, actionable, informational, spam. "
            "Use human simulation for convincing browser interaction. "
            "Do NOT reply or send — read-only triage. Report to Alfred."
        ),
        "schedule": "every 2 hours during business hours",
        "alfred_was": "Using Gmail MCP (cloud-dependent, costs tokens)",
        "robin_advantage": "Human-convincing GUI, no API tokens, local",
    },
    {
        "id": "D010",
        "title": "Obsidian vault maintenance",
        "task_type": "shell",
        "skill": "powershell-execute",
        "priority": "low",
        "description": (
            "Ensure vault/ structure is healthy: check for orphaned files, "
            "verify session records exist for all completed sessions, "
            "update vault/README.md if directory structure changed. "
            "Run weekly."
        ),
        "schedule": "weekly (Sunday 3 AM)",
        "alfred_was": "Occasional vault checks during sessions",
        "robin_advantage": "Systematic, never skipped, runs automatically",
    },
]


def format_batch():
    """Format the delegation batch for display."""
    lines = []
    lines.append(f"DELEGATION BATCH: {len(DELEGATION_BATCH)} tasks")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    for d in DELEGATION_BATCH:
        lines.append(f"  [{d['id']}] {d['title']}")
        lines.append(f"         type={d['task_type']}  skill={d['skill']}  priority={d['priority']}")
        lines.append(f"         schedule: {d['schedule']}")
        lines.append(f"         Alfred was: {d['alfred_was']}")
        lines.append(f"         Robin advantage: {d['robin_advantage']}")
        lines.append("")
    return "\n".join(lines)


def create_delegation_messages():
    """Create peers_delegation messages for the batch."""
    try:
        from rudy.peers_delegation import create_delegation_message
    except ImportError:
        from peers_delegation import create_delegation_message

    messages = []
    priority_map = {"critical": 10, "high": 30, "medium": 50, "low": 70}
    for d in DELEGATION_BATCH:
        msg = create_delegation_message(
            task_type=d["task_type"],
            title=d["title"],
            description=d["description"],
            priority=priority_map.get(d["priority"], 50),
            skill_id=d["skill"],
            context={
                "schedule": d["schedule"],
                "delegation_id": d["id"],
                "robin_advantage": d["robin_advantage"],
            },
        )
        messages.append(msg)
    return messages


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "list":
        print(format_batch())

    elif cmd == "dry-run":
        msgs = create_delegation_messages()
        print(f"Would send {len(msgs)} delegation messages:")
        for m_str in msgs:
            m = json.loads(m_str)
            t = m["task"]
            print(f"  [{t['type']}] {t['title']} -> robin (priority: {t['priority']})")

    elif cmd == "send":
        try:
            from rudy.peers_delegation import send_to_peer
        except ImportError:
            from peers_delegation import send_to_peer

        msgs = create_delegation_messages()
        print(f"Sending {len(msgs)} delegations to Robin...")
        for m_str in msgs:
            m = json.loads(m_str)
            t = m["task"]
            try:
                result = send_to_peer("alfred", "robin", m_str)
                print(f"  [{t['type']}] {t['title']} -> sent")
            except Exception as e:
                print(f"  [{t['type']}] {t['title']} -> FAILED: {e}")

    else:
        print(f"Usage: {sys.argv[0]} [list|dry-run|send]")
