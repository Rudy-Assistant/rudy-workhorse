#!/usr/bin/env python3
"""
Session Metrics Collector — ADR-015 Phase 1.

Collects automated, objective metrics for session scoring.
Replaces subjective self-reporting with verifiable data.

Metrics collected:
  1. Deliverable verification (claimed files exist on disk)
  2. Finding age analysis (open findings, sessions deferred)
  3. Robin task throughput (tasks completed vs assigned)
  4. Phantom deliverable detection (claimed but missing)

Usage:
  python -m rudy.session_metrics --session S51 --agent lucius \\
      --deliverables path1 path2 --findings-dir vault/Findings

Output: vault/Scores/metrics-{agent}-S{N}.json

Author: Lucius Fox (S51)
ADR: ADR-015-Automated-Scoring-Framework
"""

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from rudy.paths import REPO_ROOT, RUDY_DATA, BATCAVE_VAULT

logger = logging.getLogger("rudy.session_metrics")

SCORES_DIR = BATCAVE_VAULT / "Scores"
FINDINGS_DIR = BATCAVE_VAULT / "Findings"
TASKQUEUE_DIR = RUDY_DATA / "robin-taskqueue"
ACTIVE_QUEUE = TASKQUEUE_DIR / "active.json"
COMPLETED_DIR = TASKQUEUE_DIR / "completed"


# ── Grade bands (ADR-009) ──
def _letter_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


# ── Metric 1: Deliverable Verification ──
def verify_deliverables(paths: list[str]) -> dict:
    """Check that every claimed deliverable exists on disk.

    Returns dict with verified count, missing list, and phantom rate.
    """
    results = {"claimed": len(paths), "verified": 0, "missing": []}
    for p in paths:
        full = Path(p)
        if not full.is_absolute():
            full = REPO_ROOT / p
        if full.exists() and full.stat().st_size > 0:
            results["verified"] += 1
        else:
            results["missing"].append(str(p))
    total = results["claimed"] or 1
    results["phantom_rate"] = round(
        len(results["missing"]) / total, 3
    )
    results["score"] = 100 if not results["missing"] else max(
        0, 100 - (len(results["missing"]) * 20)
    )
    return results


# ── Metric 2: Finding Age Analysis ──
def analyze_findings(current_session: int) -> dict:
    """Scan vault/Findings/*.md for open items and their ages.

    Returns dict with open count, stale count (3+ sessions), and penalty.
    """
    results = {
        "total_findings": 0,
        "open_findings": [],
        "stale_findings": [],
        "resolved_findings": 0,
        "penalty": 0,
        "score": 100,
    }
    if not FINDINGS_DIR.exists():
        return results

    session_re = re.compile(r"LF-S(\d+)-\d+|LG-S(\d+)-\d+")
    status_re = re.compile(
        r"\*\*Status:\*\*\s*(OPEN|RESOLVED|PARTIALLY\s+RESOLVED)",
        re.IGNORECASE,
    )
    for f in sorted(FINDINGS_DIR.glob("*.md")):
        results["total_findings"] += 1
        text = f.read_text(encoding="utf-8", errors="replace")
        # Extract session number from filename
        m = session_re.search(f.stem)
        filed_session = int(m.group(1) or m.group(2)) if m else 0
        # Extract status
        sm = status_re.search(text)
        status = sm.group(1).strip().upper() if sm else "UNKNOWN"
        age = current_session - filed_session

        if "RESOLVED" in status:
            results["resolved_findings"] += 1
        else:
            entry = {
                "id": f.stem,
                "filed_session": filed_session,
                "age_sessions": age,
                "status": status,
            }
            results["open_findings"].append(entry)
            if age >= 3:
                results["stale_findings"].append(entry)
                # ADR-015: -5 per stale finding
                results["penalty"] += 5

    results["score"] = max(0, 100 - results["penalty"])
    return results


# ── Metric 3: Robin Task Throughput ──
def measure_robin_throughput() -> dict:
    """Measure Robin task completion vs assignment.

    Returns dict with assigned, completed, throughput rate, and score.
    """
    results = {
        "assigned": 0,
        "completed": 0,
        "failed": 0,
        "pending": 0,
        "throughput_rate": 0.0,
        "score": 0,
    }
    # Count active (pending) tasks
    if ACTIVE_QUEUE.exists():
        try:
            tasks = json.loads(
                ACTIVE_QUEUE.read_text(encoding="utf-8")
            )
            results["pending"] = len(tasks)
            results["assigned"] += len(tasks)
        except (json.JSONDecodeError, OSError):
            pass

    # Count completed tasks
    if COMPLETED_DIR.exists():
        completed_files = list(COMPLETED_DIR.glob("*.json"))
        results["completed"] = len(completed_files)
        results["assigned"] += len(completed_files)
    total = results["assigned"] or 1
    results["throughput_rate"] = round(
        results["completed"] / total, 3
    )
    # Score: 100% throughput = 100, 0% = 0
    results["score"] = int(results["throughput_rate"] * 100)
    return results


# ── Composite Score Calculator ──
def compute_composite(
    deliverable_score: float,
    findings_score: float,
    throughput_score: float,
    fixes_score: float = 0.0,
    records_penalty: float = 0.0,
    phantom_count: int = 0,
) -> dict:
    """Compute composite automated score per ADR-016 Reform 4.

    Outcome-weighted scoring (ADR-016, effective S52):
      Fixes merged/verified:   35%
      Deliverable verification: 20%
      Finding resolution rate:  25%
      Robin throughput:          10%
      Records quality:           10% (penalty only: >30 lines = -5)

    Previous weights (ADR-015): deliverables 40%, findings 35%, throughput 25%.
    """
    # ADR-016 outcome-weighted average
    raw = (
        fixes_score * 0.35
        + deliverable_score * 0.20
        + findings_score * 0.25
        + throughput_score * 0.10
        + max(0, 100 - records_penalty) * 0.10
    )
    # ADR-015 anti-inflation safeguards
    penalties = []
    if phantom_count > 0:
        raw = max(0, raw - 10)
        penalties.append(f"phantom_penalty:-10 ({phantom_count} phantoms)")
    if raw < 70:
        # Automated floor: if metrics < 70, final capped at 75
        penalties.append("automated_floor:cap_75")

    final = round(raw, 1)
    return {
        "raw_score": round(raw, 1),
        "final_score": final,
        "grade": _letter_grade(final),
        "penalties_applied": penalties,
        "sub_scores": {
            "deliverables": deliverable_score,
            "findings": findings_score,
            "throughput": throughput_score,
        },
    }


# ── Main Entry Point ──
def collect_metrics(
    session_number: int,
    agent: str,
    deliverable_paths: Optional[list[str]] = None,
    fixes_merged: int = 0,
    record_lines: int = 0,
) -> dict:
    """Run all metric collectors and produce output JSON.

    Args:
        session_number: e.g. 51
        agent: 'lucius' or 'alfred'
        deliverable_paths: list of file paths claimed as deliverables
        fixes_merged: number of fixes merged/verified this session (ADR-016)
        record_lines: total lines in session record + handoff (ADR-016)

    Returns:
        Full metrics dict (also written to vault/Scores/).
    """
    deliverable_paths = deliverable_paths or []

    deliverables = verify_deliverables(deliverable_paths)
    findings = analyze_findings(session_number)
    throughput = measure_robin_throughput()

    # ADR-016 Reform 4: fixes score (0 fixes=0, 1=70, 2+=100)
    fixes_score = min(100, fixes_merged * 70) if fixes_merged else 0.0
    # ADR-016 Reform 2: records penalty (>30 lines = -5 per 10 excess)
    records_penalty = max(0, (record_lines - 30) // 10) * 5 if record_lines > 30 else 0.0

    composite = compute_composite(
        deliverable_score=deliverables["score"],
        findings_score=findings["score"],
        throughput_score=throughput["score"],
        fixes_score=fixes_score,
        records_penalty=records_penalty,
        phantom_count=len(deliverables["missing"]),
    )
    metrics = {
        "session": f"S{session_number}",
        "agent": agent,
        "collected_at": datetime.now().isoformat(),
        "pillar": "automated_metrics (ADR-015)",
        "deliverables": deliverables,
        "findings": findings,
        "robin_throughput": throughput,
        "composite": composite,
    }

    # Write to vault/Scores/
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SCORES_DIR / f"metrics-{agent}-S{session_number}.json"
    out_path.write_text(
        json.dumps(metrics, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(
        "Metrics written: %s (score=%s, grade=%s)",
        out_path.name,
        composite["final_score"],
        composite["grade"],
    )
    return metrics


# ── CLI ──
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="ADR-015 Session Metrics Collector"
    )
    parser.add_argument(
        "--session", type=int, required=True, help="Session number"
    )
    parser.add_argument(
        "--agent", required=True, help="Agent name (lucius/alfred)"
    )
    parser.add_argument(
        "--deliverables", nargs="*", default=[], help="Claimed file paths"
    )
    parser.add_argument(
        "--fixes", type=int, default=0, help="Fixes merged this session (ADR-016)"
    )
    parser.add_argument(
        "--record-lines", type=int, default=0, help="Total lines in session record + handoff (ADR-016)"
    )
    args = parser.parse_args()

    result = collect_metrics(
        session_number=args.session,
        agent=args.agent,
        deliverable_paths=args.deliverables,
        fixes_merged=args.fixes,
        record_lines=args.record_lines,
    )
    print(json.dumps(result, indent=2, default=str))
