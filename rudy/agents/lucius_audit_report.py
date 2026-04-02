"""
Lucius Audit Report -- Structured audit report generation.

Extracted from lucius_fox.py (ADR-005 Phase 2b, Session 73).
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from rudy.paths import RUDY_DATA

log = logging.getLogger("lucius_fox")

AUDIT_DIR = RUDY_DATA / "lucius-audits"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def generate_audit_report(
    findings: list,
    status: dict,
    version: str = "unknown",
    audit_dir: Path = None,
) -> dict:
    """Write structured audit report (JSON + Markdown).

    Args:
        findings: List of finding dicts with type, severity, title, detail, recommendation.
        status: Status dict (may contain code_inventory, third_party_imports).
        version: Agent version string.
        audit_dir: Directory for output files. Defaults to rudy-data/lucius-audits/.

    Returns:
        Audit report dict with summary and metadata.
    """
    if audit_dir is None:
        audit_dir = AUDIT_DIR
    audit_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = {
        "audit_id": f"lucius-audit-{timestamp}",
        "timestamp": datetime.now().isoformat(),
        "agent_version": version,
        "summary": {
            "total_findings": len(findings),
            "by_severity": {},
            "by_type": {},
        },
        "findings": findings,
        "code_stats": status.get("code_inventory", {}),
        "third_party": status.get("third_party_imports", []),
    }

    for f in findings:
        sev = f.get("severity", "unknown")
        typ = f.get("type", "unknown")
        report["summary"]["by_severity"][sev] = (
            report["summary"]["by_severity"].get(sev, 0) + 1
        )
        report["summary"]["by_type"][typ] = (
            report["summary"]["by_type"].get(typ, 0) + 1
        )

    # JSON report
    report_file = audit_dir / f"audit-{timestamp}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    log.info("Audit report: %s", report_file)
    log.info("Findings: %s", report["summary"]["by_severity"])

    # Markdown report
    md_file = audit_dir / f"audit-{timestamp}.md"
    lines = [
        "# Lucius Fox Audit Report",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Version:** {version}",
        f"**Findings:** {len(findings)}",
        "",
        "## Summary",
        "",
    ]
    for sev in ["high", "medium", "low", "info"]:
        count = report["summary"]["by_severity"].get(sev, 0)
        if count:
            lines.append(f"- **{sev.upper()}:** {count}")
    lines.append("")
    lines.append("## Findings")
    lines.append("")

    for i, f_item in enumerate(findings, 1):
        sev = f_item.get("severity", "?").upper()
        lines.append(f"### {i}. [{sev}] {f_item['title']}")
        lines.append(f"{f_item.get('detail', '')}")
        lines.append(
            f"**Recommendation:** {f_item.get('recommendation', 'N/A')}"
        )
        lines.append("")

    md_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Markdown report: %s", md_file)
    return report
