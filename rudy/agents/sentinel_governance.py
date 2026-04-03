"""Governance and signal-emission module for Sentinel.

Extracted from sentinel.py (S88, ADR-005 Phase 2).
Provides Lucius signal detection and coordination monitoring.
"""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from . import DESKTOP, LOGS_DIR

# Module-level constants
LUCIUS_SIGNALS_FILE = (
    Path(os.environ.get("RUDY_DATA", str(DESKTOP / "rudy-data")))
    / "coordination"
    / "lucius-signals.json"
)

LUCIUS_SIGNAL_TYPES = {
    "waste_detected",
    "delegation_violation",
    "tool_amnesia",
    "score_trend",
    "finding_stale",
    "drift_alert",
}

MAX_LUCIUS_SIGNALS = 50


def load_lucius_signals() -> list:
    """Load Lucius signals from the persistent signals file.

    Returns:
        List of signal dictionaries, or empty list if file doesn't exist.
    """
    if not LUCIUS_SIGNALS_FILE.exists():
        return []
    try:
        with open(LUCIUS_SIGNALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def emit_lucius_signal(signal_type: str, detail: str) -> None:
    """Emit a Lucius governance signal.

    Args:
        signal_type: One of LUCIUS_SIGNAL_TYPES.
        detail: Description of the signal.
    """
    if signal_type not in LUCIUS_SIGNAL_TYPES:
        return

    signals = load_lucius_signals()
    signals.append({
        "type": signal_type,
        "detail": detail,
        "timestamp": datetime.now().isoformat(),
    })
    # Keep only the most recent signals
    signals = signals[-MAX_LUCIUS_SIGNALS:]

    LUCIUS_SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(LUCIUS_SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(signals, f, indent=2)
    except Exception:
        pass


def observe_lucius_governance(emit_fn=None) -> None:
    """Check for Lucius-relevant signals: stale findings, score trends.

    Args:
        emit_fn: Optional callable to emit signals. Defaults to emit_lucius_signal.
    """
    if emit_fn is None:
        emit_fn = emit_lucius_signal

    # 1. finding_stale: check findings dir for items open 3+ sessions
    findings_dir = Path(os.environ.get(
        "RUDY_DATA", str(DESKTOP / "rudy-data")
    )) / "findings"
    if findings_dir.exists():
        for fp in findings_dir.glob("*.json"):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    finding = json.load(f)
                status = finding.get("status", "OPEN")
                if status in ("OPEN", "RECURRING"):
                    fid = finding.get("id", fp.stem)
                    emit_fn(
                        "finding_stale",
                        f"{fid} ({finding.get('severity', '?')}): {status}"
                    )
            except Exception:
                pass

    # 2. score_trend: check last handoff scores
    handoffs_dir = Path(os.environ.get(
        "RUDY_DATA", str(DESKTOP / "rudy-data")
    )) / "handoffs"
    if handoffs_dir.exists():
        scores = []
        for hp in sorted(handoffs_dir.glob("session-*-handoff.json"))[-3:]:
            try:
                with open(hp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                score = data.get("compliance_score")
                if score is not None:
                    scores.append(score)
            except Exception:
                pass
        if len(scores) >= 2 and all(s < 70 for s in scores[-2:]):
            emit_fn(
                "score_trend",
                f"Declining: last {len(scores)} scores = {scores}"
            )

    # 3. waste_detected: check latest score for low skills_utilization
    score_file = Path(os.environ.get(
        "RUDY_DATA", str(DESKTOP / "rudy-data")
    )) / "coordination" / "alfred-status.json"
    if score_file.exists():
        try:
            with open(score_file, "r", encoding="utf-8") as f:
                status_data = json.load(f)
            last_action = status_data.get("last_action", "")
            if "custom" in last_action.lower() and "existing" not in last_action.lower():
                emit_fn(
                    "waste_detected",
                    f"Possible custom code when tool exists: {last_action[:100]}"
                )
        except Exception:
            pass

    # Also check for large temp script accumulation in rudy-data/
    temp_scripts = list(Path(os.environ.get(
        "RUDY_DATA", str(DESKTOP / "rudy-data")
    )).glob("temp_*.py"))
    if len(temp_scripts) > 10:
        emit_fn(
            "waste_detected",
            f"{len(temp_scripts)} temp scripts in rudy-data/ — "
            f"indicates excessive throwaway code. Clean up and "
            f"consider converting repeated patterns to Robin skills."
        )

    # 4. delegation_violation: check coordination files for Alfred doing local I/O when Robin was online.
    coord_dir = Path(os.environ.get(
        "RUDY_DATA", str(DESKTOP / "rudy-data")
    )) / "coordination"
    robin_status_file = coord_dir / "robin-status.json"
    if robin_status_file.exists():
        try:
            with open(robin_status_file, "r", encoding="utf-8") as f:
                robin_data = json.load(f)
            robin_state = robin_data.get("state", "offline")
            if robin_state == "online":
                friction_file = coord_dir / "friction-log.json"
                if friction_file.exists():
                    try:
                        with open(friction_file, "r", encoding="utf-8") as f:
                            friction = json.load(f)
                        violations = [
                            e for e in friction.get("entries", [])
                            if e.get("type") == "delegation_bypass"
                        ]
                        if violations:
                            emit_fn(
                                "delegation_violation",
                                f"{len(violations)} delegation bypass(es) "
                                f"while Robin online. Latest: "
                                f"{violations[-1].get('detail', '?')[:80]}"
                            )
                    except Exception:
                        pass
        except Exception:
            pass

    # 5. tool_amnesia: check if registry.json was consulted recently
    registry_path = Path(os.environ.get(
        "RUDY_WORKHORSE", str(DESKTOP / "rudy-workhorse")
    )) / "registry.json"
    if registry_path.exists():
        try:
            reg_mtime = registry_path.stat().st_mtime
            reg_age_hours = (
                datetime.now().timestamp() - reg_mtime
            ) / 3600
            if reg_age_hours > 48:
                emit_fn(
                    "tool_amnesia",
                    f"registry.json not updated in {reg_age_hours:.0f}h. "
                    f"Run lucius audit to refresh capability manifest."
                )
        except Exception:
            pass

    # 6. drift_alert: check for environment/config drift
    expected_coord_files = [
        "alfred-status.json",
        "robin-status.json",
        "session-branch.json",
    ]
    for fname in expected_coord_files:
        fpath = coord_dir / fname
        if not fpath.exists():
            emit_fn(
                "drift_alert",
                f"Expected coordination file missing: {fname}"
            )
        else:
            try:
                age_hours = (
                    datetime.now().timestamp() - fpath.stat().st_mtime
                ) / 3600
                if age_hours > 24:
                    emit_fn(
                        "drift_alert",
                        f"{fname} stale ({age_hours:.0f}h old). "
                        f"Coordination layer may be inactive."
                    )
            except Exception:
                pass

    # Check for runaway process count (LG-S37-001)
    try:
        r = subprocess.run(
            ["tasklist", "/fo", "CSV", "/nh"],
            capture_output=True, text=True, timeout=10,
        )
        node_count = r.stdout.lower().count('"node.exe"')
        python_count = r.stdout.lower().count('"python.exe"')
        total = node_count + python_count
        if total > 30:
            emit_fn(
                "drift_alert",
                f"Process sprawl: {node_count} node + {python_count} python "
                f"= {total} total. Expected <20. "
                f"Investigate bridge_runner child reaping (LG-S37-001)."
            )
    except Exception:
        pass
