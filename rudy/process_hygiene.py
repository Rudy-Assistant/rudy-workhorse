"""
Process Hygiene — Kill orphaned processes after DC sessions.

Session 64: Codifies process cleanup as a HARD RULE.

Problem:
    DC start_process spawns powershell/cmd/python/conhost child processes.
    These are never terminated when the session ends, accumulating across
    autonomous loops. S64 audit found 110 orphaned python processes (2GB).

Usage:
    # Import and call at session end
    from rudy.process_hygiene import cleanup_session_processes
    cleanup_session_processes()

    # CLI: run directly
    python -m rudy.process_hygiene

    # From oracle_git.py or any helper script
    from rudy.process_hygiene import cleanup_session_processes
    cleanup_session_processes(dry_run=True)  # preview only
"""

import json
import logging
import os
import subprocess

log = logging.getLogger("process_hygiene")
# Processes that must NEVER be killed
PROTECTED_NAMES = {
    "explorer", "svchost", "system", "csrss", "wininit", "winlogon",
    "lsass", "services", "smss", "dwm", "taskhostw", "sihost",
    "fontdrvhost", "runtimebroker", "shellexperiencehost",
    "searchhost", "startmenuexperiencehost", "textinputhost",
    "ollama", "ollama_llama_server",  # local AI — always running
    "node",  # n8n, MCP servers
    "rustdesk", "tailscaled",  # remote access
    "sshd", "conhost",  # SSH and terminal hosts (kill via parent)
}

# Only kill these process names (DC session children)
TARGET_NAMES = {"python", "python3", "cmd", "powershell"}


def _get_idle_processes(name: str, cpu_threshold: float = 1.0) -> list[dict]:
    """Get processes by name with CPU below threshold."""
    cmd = (
        f"Get-Process {name} -ErrorAction SilentlyContinue "
        f"| Where-Object {{$_.CPU -lt {cpu_threshold}}} "
        f"| Select-Object Id,ProcessName,CPU,WorkingSet64 "
        f"| ConvertTo-Json"
    )
    r = subprocess.run(
        ["powershell", "-Command", cmd],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return []
    data = json.loads(r.stdout)
    return data if isinstance(data, list) else [data]

def cleanup_session_processes(
    dry_run: bool = False,
    cpu_threshold: float = 1.0,
) -> dict:
    """Kill idle DC-spawned processes (python, cmd, powershell).

    Args:
        dry_run: If True, report what would be killed without killing.
        cpu_threshold: Only kill processes with CPU time below this (seconds).

    Returns:
        Dict with counts per process type and total memory freed.
    """
    my_pid = os.getpid()
    results = {"killed": {}, "skipped": 0, "freed_mb": 0.0, "dry_run": dry_run}

    for name in TARGET_NAMES:
        procs = _get_idle_processes(name, cpu_threshold)
        killed = 0
        for p in procs:
            pid = p.get("Id")
            if not pid or pid == my_pid:
                results["skipped"] += 1
                continue
            mem_mb = round(p.get("WorkingSet64", 0) / 1048576, 1)
            if dry_run:
                log.info("[Hygiene] Would kill %s PID %d (%.1f MB)",
                         name, pid, mem_mb)
                killed += 1
                results["freed_mb"] += mem_mb
            else:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                    )
                    killed += 1
                    results["freed_mb"] += mem_mb
                    log.info("[Hygiene] Killed %s PID %d (%.1f MB)",
                             name, pid, mem_mb)
                except Exception as e:
                    log.warning("[Hygiene] Failed to kill PID %d: %s", pid, e)
        results["killed"][name] = killed

    results["freed_mb"] = round(results["freed_mb"], 1)
    total = sum(results["killed"].values())
    log.info("[Hygiene] %s %d processes, freed ~%.1f MB",
             "Would kill" if dry_run else "Killed",
             total, results["freed_mb"])
    return results

def audit_processes() -> dict:
    """Return current count and memory of target process types."""
    audit = {}
    for name in TARGET_NAMES | {"conhost"}:
        cmd = (
            f"Get-Process {name} -ErrorAction SilentlyContinue "
            f"| Measure-Object WorkingSet64 -Sum -Count "
            f"| Select-Object Count,Sum | ConvertTo-Json"
        )
        r = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            d = json.loads(r.stdout)
            audit[name] = {
                "count": d.get("Count", 0),
                "mem_mb": round((d.get("Sum") or 0) / 1048576, 1),
            }
        else:
            audit[name] = {"count": 0, "mem_mb": 0}
    return audit


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description="Process Hygiene Cleanup")
    p.add_argument("--dry-run", action="store_true",
                   help="Preview only, don't kill anything")
    p.add_argument("--audit", action="store_true",
                   help="Just show current process counts")
    args = p.parse_args()

    if args.audit:
        result = audit_processes()
        print(json.dumps(result, indent=2))
    else:
        result = cleanup_session_processes(dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
