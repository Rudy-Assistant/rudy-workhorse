"""
Peers-to-TaskQueue Bridge -- Session 28

Connects claude-peers-mcp delegation messages to Robin's task queue.
Robin polls the broker for DELEGATE messages, converts them to task
queue entries, executes them, and sends RESULT messages back.

This bridges the gap between:
  - peers_delegation.py (message protocol)
  - robin_taskqueue.py (execution engine)

Extended task types handled:
  - shell: Execute a shell command via powershell-execute skill
  - skill_execute: Run an OpenSpace skill by skill_id
  - health_check: System health poll via system-health-check skill
  - security_scan: Security sweep via security-sweep skill

Usage:
  python -m rudy.peers_taskqueue_bridge poll --robin-id <id>
  python -m rudy.peers_taskqueue_bridge once --robin-id <id>

Lucius Gate: LG-028 - No new dependencies. Uses existing modules.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure rudy is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rudy.peers_delegation import (
    poll_messages,
    create_result_message,
    send_to_peer,
    register_peer,
    MSG_DELEGATE,
)
from rudy.robin_taskqueue import (
    make_task,
    add_task,
    execute_task,
    complete_task,
    load_queue,
)

log = logging.getLogger("peers.bridge")

# ---------------------------------------------------------------------------
# Extended task type mapping
# ---------------------------------------------------------------------------

# Maps delegation task_type -> taskqueue handler config
EXTENDED_TYPE_MAP = {
    "shell": {
        "queue_type": "shell",
        "default_command": None,  # Must come from delegation
    },
    "skill_execute": {
        "queue_type": "skill_execute",
        "default_command": None,
    },
    "health_check": {
        "queue_type": "health_check",
        "handler": "_execute_health_check",
    },
    "security_scan": {
        "queue_type": "security_scan",
        "handler": "_execute_security_scan",
    },
}


# ---------------------------------------------------------------------------
# Extended task executors (supplement robin_taskqueue.execute_task)
# ---------------------------------------------------------------------------

def _execute_health_check(task: dict) -> tuple:
    """Run system health check -- CPU, RAM, disk, services, uptime."""
    import subprocess
    commands = [
        ("cpu_ram", "wmic cpu get LoadPercentage /value & wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value"),
        ("disk", "wmic logicaldisk get Size,FreeSpace,Caption /value"),
        ("uptime", "net stats workstation | findstr Statistics"),
    ]
    results = []
    for name, cmd in commands:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, shell=True,
                timeout=30, encoding="utf-8", errors="replace",
            )
            results.append(f"--- {name} ---\n{r.stdout.strip()}")
        except Exception as e:
            results.append(f"--- {name} --- ERROR: {e}")
    return True, "\n".join(results)


def _execute_security_scan(task: dict) -> tuple:
    """Run security sweep -- open ports, Defender, firewall."""
    import subprocess
    commands = [
        ("defender", "powershell -Command \"Get-MpComputerStatus | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,AntivirusSignatureLastUpdated | Format-List\""),
        ("firewall", "netsh advfirewall show allprofiles state"),
        ("ports", "netstat -an | findstr LISTENING"),
    ]
    results = []
    for name, cmd in commands:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, shell=True,
                timeout=30, encoding="utf-8", errors="replace",
            )
            out = r.stdout.strip()
            if name == "ports":
                lines = out.split("\n")
                out = f"{len(lines)} listening ports\n" + "\n".join(lines[:20])
            results.append(f"--- {name} ---\n{out}")
        except Exception as e:
            results.append(f"--- {name} --- ERROR: {e}")
    return True, "\n".join(results)


def _execute_shell(task: dict) -> tuple:
    """Execute a shell command from delegation."""
    import subprocess
    cmd = task.get("command") or task.get("metadata", {}).get("command", "echo No command specified")
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, shell=True,
            timeout=task.get("estimated_minutes", 5) * 60,
            cwd=str(Path(__file__).resolve().parent.parent),
            encoding="utf-8", errors="replace",
        )
        output = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, output[-3000:]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


def execute_extended_task(task: dict) -> tuple:
    """Execute an extended task type from delegation.

    Returns (success: bool, output: str).
    """
    task_type = task.get("type", "unknown")

    if task_type == "health_check":
        return _execute_health_check(task)
    elif task_type == "security_scan":
        return _execute_security_scan(task)
    elif task_type == "shell":
        return _execute_shell(task)
    elif task_type == "skill_execute":
        skill_id = task.get("skill_id", "unknown")
        return False, f"skill_execute not yet wired (skill_id={skill_id})"
    else:
        # Fall through to standard taskqueue executor
        return execute_task(task)


# ---------------------------------------------------------------------------
# Bridge: delegation message -> taskqueue entry -> execute -> result
# ---------------------------------------------------------------------------

def delegation_to_task(msg: dict) -> dict:
    """Convert a DELEGATE message to a taskqueue task dict."""
    task_data = msg.get("task", {})
    return make_task(
        task_type=task_data.get("type", "unknown"),
        title=task_data.get("title", "Untitled delegation"),
        description=task_data.get("description", ""),
        priority=task_data.get("priority", 50),
        estimated_minutes=task_data.get("estimated_minutes", 5),
        command=task_data.get("command"),
        metadata={
            "delegation_id": msg.get("id"),
            "sender": msg.get("sender", "alfred"),
            "skill_id": task_data.get("skill_id"),
            "from_peer": msg.get("_from_peer"),
        },
    )


def process_delegation(
    msg: dict,
    robin_peer_id: str,
) -> dict:
    """Process a single DELEGATE message end-to-end.

    1. Convert to task
    2. Execute (extended or standard)
    3. Send result back via peers-mcp

    Returns the completed task dict.
    """
    task = delegation_to_task(msg)
    delegation_id = msg.get("id", "unknown")
    from_peer = msg.get("_from_peer")

    log.info("Processing delegation %s: [%s] %s",
             delegation_id, task["type"], task["title"])

    start = time.time()

    # Execute based on type
    task_type = task.get("type", "unknown")
    if task_type in EXTENDED_TYPE_MAP:
        success, output = execute_extended_task(task)
    else:
        success, output = execute_task(task)

    duration = time.time() - start

    # Build result message
    result_msg = create_result_message(
        delegation_id=delegation_id,
        success=success,
        output=output,
        duration_seconds=duration,
    )

    # Send result back to Alfred
    if from_peer:
        send_to_peer(robin_peer_id, from_peer, result_msg)
        log.info("Result sent to %s (success=%s, %.1fs)",
                 from_peer, success, duration)

    task["result"] = output
    task["status"] = "completed" if success else "failed"
    return task


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------

def poll_once(robin_peer_id: str) -> int:
    """Poll broker once, process all pending delegations.

    Returns count of delegations processed.
    """
    messages = poll_messages(robin_peer_id)
    delegations = [m for m in messages if m.get("type") == MSG_DELEGATE]

    if not delegations:
        return 0

    log.info("Received %d delegation(s)", len(delegations))

    for msg in delegations:
        try:
            process_delegation(msg, robin_peer_id)
        except Exception as e:
            log.error("Failed processing delegation %s: %s",
                      msg.get("id", "?"), e)

    return len(delegations)


def poll_loop(
    robin_peer_id: str,
    interval_seconds: int = 10,
    max_iterations: int = 0,
):
    """Continuous poll loop for Robin.

    Args:
        robin_peer_id: Robin's peer ID from broker registration.
        interval_seconds: Seconds between polls.
        max_iterations: Stop after N iterations (0=infinite).
    """
    log.info("Starting poll loop (interval=%ds, max=%d)",
             interval_seconds, max_iterations)

    iteration = 0
    while True:
        iteration += 1
        if max_iterations and iteration > max_iterations:
            break

        try:
            count = poll_once(robin_peer_id)
            if count:
                log.info("Processed %d delegation(s) in iteration %d",
                         count, iteration)
        except Exception as e:
            log.error("Poll error: %s", e)

        time.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Peers-to-TaskQueue Bridge for Robin",
    )
    parser.add_argument("command", choices=["poll", "once", "test"])
    parser.add_argument("--robin-id", help="Robin's peer ID")
    parser.add_argument("--interval", type=int, default=10,
                        help="Poll interval in seconds")
    parser.add_argument("--max", type=int, default=0,
                        help="Max poll iterations (0=infinite)")
    args = parser.parse_args()

    if args.command == "poll":
        if not args.robin_id:
            # Auto-register
            robin_id = register_peer(
                pid=os.getpid(),
                cwd=r"C:\Users\ccimi\rudy-workhorse",
                summary="Robin Bridge (poll loop)",
            )
            print(f"Auto-registered as {robin_id}")
        else:
            robin_id = args.robin_id
        poll_loop(robin_id, args.interval, args.max)

    elif args.command == "once":
        if not args.robin_id:
            robin_id = register_peer(
                pid=os.getpid(),
                cwd=r"C:\Users\ccimi\rudy-workhorse",
                summary="Robin Bridge (one-shot)",
            )
        else:
            robin_id = args.robin_id
        count = poll_once(robin_id)
        print(f"Processed {count} delegation(s)")

    elif args.command == "test":
        # Self-test: health check
        task = make_task("health_check", "Self-test health check",
                         "Bridge self-test", priority=10)
        success, output = execute_extended_task(task)
        print(f"Health check: success={success}")
        print(output[:1000])


if __name__ == "__main__":
    main()
