"""
Lucius Findings Tracker — Persistent cross-session finding management.

Every finding gets a unique ID (e.g., LF-2026-0330-001).
Findings persist in rudy-data/lucius-findings.json across sessions.
TTL: findings unresolved after 3 sessions escalate to HIGH.
Deduplication: same finding across sessions is tracked, not duplicated.

Design constraints:
    - Import isolation (C3): All non-stdlib imports inside function bodies.
    - Append-only by default: new findings are added, resolved ones are marked.
    - Thread-safe file writes via atomic rename.

CLI:
    python -m rudy.agents.lucius_findings [list|add|resolve|escalate|stats]
"""

import json
import hashlib
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("lucius.findings")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ESCALATION_THRESHOLD = 3  # Sessions before escalation to HIGH
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


# ---------------------------------------------------------------------------
# Safe import of paths
# ---------------------------------------------------------------------------
def _get_data_dir() -> Path:
    try:
        from rudy.paths import RUDY_DATA
        return RUDY_DATA
    except ImportError:
        return Path(__file__).resolve().parent.parent.parent.parent / "rudy-data"


def _findings_path() -> Path:
    data_dir = _get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "lucius-findings.json"


# ---------------------------------------------------------------------------
# Finding ID generation
# ---------------------------------------------------------------------------
def _generate_finding_id(date_str: Optional[str] = None) -> str:
    """Generate a unique finding ID: LF-YYYY-MMDD-NNN.

    The NNN suffix is based on the count of findings created today.
    """
    now = datetime.now(timezone.utc)
    date_part = date_str or now.strftime("%Y-%m%d")

    # Load existing to count today's findings
    store = load_findings()
    today_count = sum(
        1 for f in store.get("findings", [])
        if f.get("id", "").startswith(f"LF-{date_part}")
    )

    return f"LF-{date_part}-{today_count + 1:03d}"


def _fingerprint(finding: dict) -> str:
    """Generate a deduplication fingerprint for a finding.

    Based on: file + line + category + first 100 chars of message.
    Two findings with the same fingerprint across sessions are the same finding.
    """
    key = (
        f"{finding.get('file', '')}"
        f":{finding.get('line', 0)}"
        f":{finding.get('category', '')}"
        f":{finding.get('message', '')[:100]}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Store operations
# ---------------------------------------------------------------------------
def load_findings(path: Optional[Path] = None) -> dict:
    """Load the findings store from disk."""
    fp = path or _findings_path()
    if not fp.exists():
        return {
            "version": "1.0.0",
            "findings": [],
            "stats": {
                "total_filed": 0,
                "total_resolved": 0,
                "total_escalated": 0,
            },
        }
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Findings store corrupt, starting fresh: {e}")
        return {
            "version": "1.0.0",
            "findings": [],
            "stats": {"total_filed": 0, "total_resolved": 0, "total_escalated": 0},
        }


def save_findings(store: dict, path: Optional[Path] = None) -> None:
    """Atomically write the findings store."""
    fp = path or _findings_path()
    fp.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to temp file, then rename
    fd, tmp = tempfile.mkstemp(
        dir=str(fp.parent), suffix=".tmp", prefix="findings-"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, default=str)
        os.replace(tmp, str(fp))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------
def add_finding(
    severity: str,
    category: str,
    message: str,
    file: str = "",
    line: int = 0,
    session: int = 0,
    source: str = "lucius",
    metadata: Optional[dict] = None,
) -> dict:
    """Add a new finding or update an existing one if deduplicated.

    Args:
        severity: CRITICAL, HIGH, MEDIUM, LOW, or INFO
        category: Category tag (e.g., "hardcoded_path", "import_failure")
        message: Human-readable description
        file: File path where finding was observed
        line: Line number
        session: Session number when filed
        source: Who filed it (lucius, alfred, robin, sentinel)
        metadata: Optional additional context dict

    Returns:
        The finding dict (new or updated).
    """
    store = load_findings()

    # Build finding
    finding = {
        "severity": severity.upper(),
        "category": category,
        "message": message,
        "file": file,
        "line": line,
        "source": source,
        "session_filed": session,
        "metadata": metadata or {},
    }
    fp = _fingerprint(finding)

    # Check for existing finding with same fingerprint
    for existing in store["findings"]:
        if existing.get("fingerprint") == fp and existing.get("status") != "resolved":
            # Update: bump sessions_seen, keep original ID
            existing.setdefault("sessions_seen", [])
            if session and session not in existing["sessions_seen"]:
                existing["sessions_seen"].append(session)
            existing["last_seen_session"] = session
            existing["last_seen_at"] = datetime.now(timezone.utc).isoformat()
            log.info(f"Finding {existing['id']} seen again in session {session}")
            save_findings(store)
            return existing

    # New finding
    finding["id"] = _generate_finding_id()
    finding["fingerprint"] = fp
    finding["status"] = "open"
    finding["filed_at"] = datetime.now(timezone.utc).isoformat()
    finding["last_seen_at"] = finding["filed_at"]
    finding["last_seen_session"] = session
    finding["sessions_seen"] = [session] if session else []
    finding["escalated"] = False
    finding["resolved_at"] = None
    finding["resolution"] = None

    store["findings"].append(finding)
    store["stats"]["total_filed"] = store["stats"].get("total_filed", 0) + 1
    save_findings(store)

    log.info(f"New finding {finding['id']}: [{severity}] {message[:80]}")
    return finding


def resolve_finding(
    finding_id: str,
    resolution: str = "fixed",
    session: int = 0,
) -> Optional[dict]:
    """Mark a finding as resolved.

    Args:
        finding_id: The LF-YYYY-MMDD-NNN identifier
        resolution: How it was resolved (fixed, wontfix, duplicate, obsolete)
        session: Session number when resolved

    Returns:
        The updated finding, or None if not found.
    """
    store = load_findings()

    for finding in store["findings"]:
        if finding.get("id") == finding_id:
            finding["status"] = "resolved"
            finding["resolved_at"] = datetime.now(timezone.utc).isoformat()
            finding["resolution"] = resolution
            finding["resolved_in_session"] = session
            store["stats"]["total_resolved"] = store["stats"].get("total_resolved", 0) + 1
            save_findings(store)
            log.info(f"Resolved {finding_id}: {resolution}")
            return finding

    log.warning(f"Finding {finding_id} not found")
    return None


def escalate_stale_findings(current_session: int = 0) -> list[dict]:
    """Escalate findings that have been open for >= ESCALATION_THRESHOLD sessions.

    Findings escalate from their current severity to HIGH (unless already
    CRITICAL or HIGH).

    Returns list of findings that were escalated.
    """
    store = load_findings()
    escalated = []

    for finding in store["findings"]:
        if finding.get("status") == "resolved":
            continue
        if finding.get("escalated"):
            continue

        sessions_seen = finding.get("sessions_seen", [])
        first_session = finding.get("session_filed", 0)

        # Calculate session span
        if current_session and first_session:
            span = current_session - first_session
        else:
            span = len(sessions_seen)

        if span >= ESCALATION_THRESHOLD:
            old_severity = finding.get("severity", "MEDIUM")
            if SEVERITY_ORDER.get(old_severity, 2) > SEVERITY_ORDER["HIGH"]:
                finding["severity"] = "HIGH"
                finding["escalated"] = True
                finding["escalation_reason"] = (
                    f"Unresolved for {span} sessions "
                    f"(threshold: {ESCALATION_THRESHOLD}). "
                    f"Escalated from {old_severity} to HIGH."
                )
                finding["escalated_at"] = datetime.now(timezone.utc).isoformat()
                store["stats"]["total_escalated"] = (
                    store["stats"].get("total_escalated", 0) + 1
                )
                escalated.append(finding)
                log.warning(
                    f"Escalated {finding['id']}: {old_severity} → HIGH "
                    f"(open {span} sessions)"
                )

    if escalated:
        save_findings(store)
    return escalated


def get_open_findings(
    severity: Optional[str] = None,
    category: Optional[str] = None,
) -> list[dict]:
    """Get all open (unresolved) findings, optionally filtered.

    Returns findings sorted by severity (CRITICAL first).
    """
    store = load_findings()
    findings = [
        f for f in store["findings"]
        if f.get("status") != "resolved"
    ]

    if severity:
        findings = [f for f in findings if f.get("severity") == severity.upper()]
    if category:
        findings = [f for f in findings if f.get("category") == category]

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f.get("severity", "INFO"), 99))
    return findings


def get_finding_stats() -> dict:
    """Get summary statistics for the findings store."""
    store = load_findings()
    findings = store.get("findings", [])

    open_findings = [f for f in findings if f.get("status") != "resolved"]
    resolved = [f for f in findings if f.get("status") == "resolved"]

    by_severity = {}
    for f in open_findings:
        sev = f.get("severity", "UNKNOWN")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    by_category = {}
    for f in open_findings:
        cat = f.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "total": len(findings),
        "open": len(open_findings),
        "resolved": len(resolved),
        "escalated": sum(1 for f in open_findings if f.get("escalated")),
        "by_severity": by_severity,
        "by_category": by_category,
    }


def format_findings_briefing(max_findings: int = 20) -> str:
    """Format open findings as a markdown section for session briefings."""
    findings = get_open_findings()
    stats = get_finding_stats()

    if not findings:
        return (
            "## Open Findings\n\n"
            "No open findings. The Batcave is clean.\n"
        )

    lines = [
        "## Open Findings",
        "",
        f"**{stats['open']} open** ({stats['resolved']} resolved, "
        f"{stats['escalated']} escalated)",
        "",
    ]

    # Show severity breakdown
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        count = stats["by_severity"].get(sev, 0)
        if count:
            icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}.get(sev, "")
            lines.append(f"- {icon} **{sev}**: {count}")

    lines.append("")

    # List findings (up to max)
    for f in findings[:max_findings]:
        icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}.get(
            f.get("severity", ""), ""
        )
        esc = " ⬆️ESCALATED" if f.get("escalated") else ""
        loc = f.get("file", "")
        if f.get("line"):
            loc += f":{f['line']}"
        lines.append(
            f"- {icon} **{f['id']}** [{f.get('severity', '?')}]{esc}: "
            f"{f.get('message', '')[:100]}"
            + (f" (`{loc}`)" if loc else "")
        )

    if len(findings) > max_findings:
        lines.append(f"\n*...and {len(findings) - max_findings} more*")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bulk import: convert Lucius audit findings to tracked findings
# ---------------------------------------------------------------------------
def import_from_audit(
    audit_findings: list[dict],
    session: int = 0,
    source: str = "lucius_audit",
) -> int:
    """Import findings from a Lucius audit run.

    Each audit finding should have: severity, message, and optionally
    file, line, category.

    Returns count of new findings added (deduped against existing).
    """
    added = 0
    for af in audit_findings:
        result = add_finding(
            severity=af.get("severity", "INFO"),
            category=af.get("category", af.get("type", "audit")),
            message=af.get("message", af.get("detail", str(af))),
            file=af.get("file", af.get("path", "")),
            line=af.get("line", 0),
            session=session,
            source=source,
            metadata=af.get("metadata"),
        )
        if result and "filed_at" in result:
            # Check if this was newly created (filed_at == last_seen_at)
            if result.get("filed_at") == result.get("last_seen_at"):
                added += 1
    return added


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Lucius Findings Tracker — persistent finding management"
    )
    parser.add_argument(
        "command",
        choices=["list", "add", "resolve", "escalate", "stats", "briefing"],
        help="Command to execute",
    )
    parser.add_argument("--id", help="Finding ID (for resolve)")
    parser.add_argument("--severity", "-s", help="Severity filter or new finding severity")
    parser.add_argument("--category", "-c", help="Category filter or new finding category")
    parser.add_argument("--message", "-m", help="Finding message (for add)")
    parser.add_argument("--file", "-f", help="File path (for add)")
    parser.add_argument("--line", "-l", type=int, default=0, help="Line number (for add)")
    parser.add_argument("--session", type=int, default=0, help="Session number")
    parser.add_argument("--resolution", default="fixed", help="Resolution type (for resolve)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.command == "list":
        findings = get_open_findings(severity=args.severity, category=args.category)
        if args.json:
            print(json.dumps(findings, indent=2, default=str))
        else:
            if not findings:
                print("No open findings.")
            else:
                for f in findings:
                    esc = " [ESCALATED]" if f.get("escalated") else ""
                    print(
                        f"  {f['id']} [{f['severity']}]{esc} "
                        f"{f.get('message', '')[:80]} "
                        f"({f.get('file', '')}:{f.get('line', 0)})"
                    )

    elif args.command == "add":
        if not args.message:
            parser.error("--message required for add")
        finding = add_finding(
            severity=args.severity or "MEDIUM",
            category=args.category or "manual",
            message=args.message,
            file=args.file or "",
            line=args.line,
            session=args.session,
            source="cli",
        )
        print(f"Filed: {finding['id']} [{finding['severity']}] {finding['message'][:80]}")

    elif args.command == "resolve":
        if not args.id:
            parser.error("--id required for resolve")
        result = resolve_finding(args.id, args.resolution, args.session)
        if result:
            print(f"Resolved: {args.id} ({args.resolution})")
        else:
            print(f"Finding {args.id} not found")

    elif args.command == "escalate":
        escalated = escalate_stale_findings(args.session)
        if escalated:
            for f in escalated:
                print(f"  Escalated: {f['id']} → HIGH ({f.get('escalation_reason', '')})")
        else:
            print("No findings to escalate.")

    elif args.command == "stats":
        stats = get_finding_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total: {stats['total']}  Open: {stats['open']}  "
                  f"Resolved: {stats['resolved']}  Escalated: {stats['escalated']}")
            for sev, count in sorted(stats["by_severity"].items()):
                print(f"  {sev}: {count}")

    elif args.command == "briefing":
        print(format_findings_briefing())


if __name__ == "__main__":
    main()
