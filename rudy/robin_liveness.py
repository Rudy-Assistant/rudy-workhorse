#!/usr/bin/env python3
"""
Robin Liveness Protocol — Heartbeat, status, and auto-recovery.

Two consumers:
  1. Alfred (cloud): calls check() or ensure_alive() at session start
     via Desktop Commander / Windows MCP to verify Robin is running.
  2. Robin watchdog (scheduled task): calls ensure_alive() every 5 minutes
     to self-heal if the main process crashed.

Liveness check strategy:
  - Read robin-status.json for last heartbeat timestamp
  - Verify the PID in status file is actually running
  - If stale (>10 min since last heartbeat) or PID dead → restart Robin

Usage:
    # From Alfred (via Desktop Commander on Oracle):
    python -m rudy.robin_liveness --check        # status report (JSON)
    python -m rudy.robin_liveness --ensure        # check + restart if needed
    python -m rudy.robin_liveness --restart       # force restart

    # From Python:
    from rudy.robin_liveness import ensure_alive, check_status
    status = check_status()
    if not status['alive']:
        ensure_alive()
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime

from rudy.paths import REPO_ROOT, RUDY_DATA, RUDY_LOGS, ROBIN_STATE

COORD_DIR = RUDY_DATA / "coordination"
# Robin writes state to ROBIN_STATE (rudy-data/robin-state.json) from robin_main.py
# The alfred_protocol writes a separate robin-status.json in coordination/
# We check BOTH — ROBIN_STATE is the primary heartbeat source
STATUS_FILE = ROBIN_STATE
COORD_STATUS_FILE = COORD_DIR / "robin-status.json"
LIVENESS_LOG = RUDY_LOGS / "robin-liveness.log"

# How long before we consider Robin's heartbeat stale
HEARTBEAT_STALE_SECONDS = 600  # 10 minutes

# Ensure dirs
COORD_DIR.mkdir(parents=True, exist_ok=True)
RUDY_LOGS.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Liveness] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LIVENESS_LOG),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("robin_liveness")


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            # Use tasklist to check specific PID
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Fallback: try os.kill with signal 0 (doesn't kill, just checks)
            try:
                os.kill(pid, 0)
                return True
            except (OSError, PermissionError):
                return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, PermissionError):
            return False


def _find_robin_processes() -> list:
    """Find any running Robin processes by command line pattern."""
    results = []
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                ["wmic", "process", "where",
                 "name='python.exe' and commandline like '%robin_main%'",
                 "get", "processid,commandline", "/format:csv"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.strip().splitlines():
                parts = line.strip().split(",")
                if len(parts) >= 3 and parts[-1].isdigit():
                    results.append(int(parts[-1]))
        else:
            r = subprocess.run(
                ["pgrep", "-f", "robin_main"],
                capture_output=True, text=True, timeout=5,
            )
            for line in r.stdout.strip().splitlines():
                if line.strip().isdigit():
                    results.append(int(line.strip()))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return results


def check_status() -> dict:
    """
    Check Robin's liveness status.

    Returns dict with:
        alive: bool — is Robin running and responsive?
        pid: int — Robin's PID (0 if unknown)
        heartbeat_age_seconds: float — seconds since last heartbeat
        status_state: str — state from robin-status.json
        details: str — human-readable summary
    """
    result = {
        "alive": False,
        "pid": 0,
        "heartbeat_age_seconds": float("inf"),
        "status_state": "unknown",
        "details": "",
        "checked_at": datetime.now().isoformat(),
    }

    # Read status file — try both locations (robin-state.json primary,
    # coordination/robin-status.json fallback from alfred_protocol)
    status = None
    for candidate in [STATUS_FILE, COORD_STATUS_FILE]:
        try:
            with open(candidate) as f:
                status = json.load(f)
            break
        except (FileNotFoundError, json.JSONDecodeError):
            continue

    if status is None:
        result["details"] = "No robin state file found"
        # Still check for running processes before giving up
        robin_pids = _find_robin_processes()
        if robin_pids:
            result["alive"] = True
            result["pid"] = robin_pids[0]
            result["details"] = f"Robin running (PID {robin_pids}) but no state file"
        return result

    result["pid"] = status.get("pid", 0)
    result["status_state"] = status.get("state", "unknown")

    # Check heartbeat freshness
    updated = status.get("updated_at", status.get("last_heartbeat", ""))
    if updated:
        try:
            last_beat = datetime.fromisoformat(updated)
            age = (datetime.now() - last_beat).total_seconds()
            result["heartbeat_age_seconds"] = age
        except (ValueError, TypeError):
            pass

    # Check if PID is alive
    pid = result["pid"]
    pid_alive = _is_pid_alive(pid) if pid > 0 else False

    # Also check for any robin_main processes
    robin_pids = _find_robin_processes()

    if pid_alive and result["heartbeat_age_seconds"] < HEARTBEAT_STALE_SECONDS:
        result["alive"] = True
        result["details"] = f"Robin alive (PID {pid}, heartbeat {result['heartbeat_age_seconds']:.0f}s ago)"
    elif robin_pids:
        result["alive"] = True
        result["pid"] = robin_pids[0]
        result["details"] = f"Robin running (found PID(s) {robin_pids}) but heartbeat stale"
    elif pid_alive:
        result["alive"] = True
        result["details"] = f"Robin PID {pid} alive but heartbeat stale ({result['heartbeat_age_seconds']:.0f}s)"
    else:
        result["alive"] = False
        result["details"] = f"Robin DOWN — PID {pid} not running, no robin_main found"

    return result


def start_robin() -> dict:
    """
    Start Robin's main process.

    Returns dict with:
        started: bool
        pid: int
        error: str (empty on success)
    """
    log.info("Starting Robin...")

    # Find Python — canonical detection from rudy.paths
    from rudy.paths import PYTHON_EXE
    python_exe = PYTHON_EXE

    try:
        if sys.platform == "win32":
            # Start detached (CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS)
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            proc = subprocess.Popen(
                [python_exe, "-m", "rudy.robin_main", "--nightwatch"],
                cwd=str(REPO_ROOT),
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            proc = subprocess.Popen(
                [python_exe, "-m", "rudy.robin_main", "--nightwatch"],
                cwd=str(REPO_ROOT),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        log.info("Robin started: PID %d", proc.pid)
        return {"started": True, "pid": proc.pid, "error": ""}

    except Exception as e:
        log.error("Failed to start Robin: %s", e)
        return {"started": False, "pid": 0, "error": str(e)}


def stop_robin() -> dict:
    """Stop Robin's main process gracefully."""
    status = check_status()
    if not status["alive"]:
        return {"stopped": True, "details": "Robin was not running"}

    pid = status["pid"]
    robin_pids = _find_robin_processes()
    all_pids = list(set([pid] + robin_pids))

    killed = []
    for p in all_pids:
        if p <= 0:
            continue
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(p)],
                               capture_output=True, timeout=10)
            else:
                os.kill(p, 15)  # SIGTERM
            killed.append(p)
        except Exception:
            pass

    log.info("Stopped Robin PIDs: %s", killed)
    return {"stopped": True, "killed_pids": killed}


def ensure_alive() -> dict:
    """
    Check if Robin is alive; start him if not.
    This is the main entry point for both Alfred and the watchdog.

    Returns:
        status: dict from check_status()
        action: "none" | "started" | "restarted"
        start_result: dict from start_robin() (if action != "none")
    """
    status = check_status()

    if status["alive"]:
        log.info("Robin is alive: %s", status["details"])
        return {"status": status, "action": "none"}

    log.warning("Robin is DOWN: %s — starting...", status["details"])
    start_result = start_robin()

    # Give Robin a moment to initialize
    time.sleep(3)

    # Re-check
    new_status = check_status()
    action = "started" if start_result["started"] else "failed"

    log.info("After restart: alive=%s, PID=%s", new_status["alive"], new_status["pid"])
    return {"status": new_status, "action": action, "start_result": start_result}


def restart_robin() -> dict:
    """Force restart Robin regardless of current state."""
    log.info("Force-restarting Robin...")
    stop_result = stop_robin()
    time.sleep(2)
    start_result = start_robin()
    time.sleep(3)
    new_status = check_status()
    return {
        "stop_result": stop_result,
        "start_result": start_result,
        "status": new_status,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Robin Liveness Protocol")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Check status (JSON output)")
    group.add_argument("--ensure", action="store_true", help="Check + start if needed")
    group.add_argument("--restart", action="store_true", help="Force restart")
    group.add_argument("--stop", action="store_true", help="Stop Robin")
    args = parser.parse_args()

    if args.check:
        result = check_status()
    elif args.ensure:
        result = ensure_alive()
    elif args.restart:
        result = restart_robin()
    elif args.stop:
        result = stop_robin()

    print(json.dumps(result, indent=2, default=str))
