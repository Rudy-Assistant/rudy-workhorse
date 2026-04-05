"""
Process Hygiene -- Kill orphaned processes after DC sessions.

Session 64: Codifies process cleanup as a HARD RULE.
Session 122: Fix F-S121-001 -- query Robin ecosystem PIDs via
    robin_liveness BEFORE killing, to prevent accidental kills.

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
    "ollama", "ollama_llama_server",  # local AI -- always running
    "node",  # n8n, MCP servers
    "rustdesk", "tailscaled",  # remote access
    "sshd", "conhost",  # SSH and terminal hosts (kill via parent)
    "windows-mcp",  # Windows-MCP server -- Robin's hands (S86 fix)
}

# Only kill these process names (DC session children)
TARGET_NAMES = {"python", "python3", "cmd", "powershell"}


def _get_robin_ecosystem_pids() -> set:
    """Query Robin ecosystem PIDs that must NEVER be killed.

    S122 fix for F-S121-001: Get-Process CommandLine was empty for all
    python processes, so safe-process detection failed and Robin/Sentinel
    were killed. This function uses robin_liveness (which uses wmic, not
    Get-Process) to reliably find Robin ecosystem PIDs.

    Returns a set of PIDs for: robin_main, sentinel, bridge_runner,
    launch_cowork --watch.
    """
    protected = set()
    # 1. Get Robin + Sentinel PIDs from robin_liveness
    try:
        from rudy.robin_liveness import check_full_nervous_system
        ns = check_full_nervous_system()
        for component in ns.get("components", {}).values():
            pid = component.get("pid", 0)
            if pid > 0:
                protected.add(pid)
                log.info("[Hygiene] Protected Robin component PID %d", pid)
    except Exception as e:
        log.warning("[Hygiene] robin_liveness import failed: %s", e)

    # 2. Find bridge_runner and launch_cowork PIDs via wmic
    #    (wmic works when Get-Process CommandLine is empty)
    patterns = ["bridge_runner", "launch_cowork"]
    for pattern in patterns:
        try:
            r = subprocess.run(
                ["wmic", "process", "where",
                 f"name='python.exe' and commandline like '%{pattern}%'",
                 "get", "processid", "/format:csv"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.strip().splitlines():
                parts = line.strip().split(",")
                if len(parts) >= 2 and parts[-1].isdigit():
                    pid = int(parts[-1])
                    protected.add(pid)
                    log.info("[Hygiene] Protected %s PID %d",
                             pattern, pid)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if protected:
        log.info("[Hygiene] Total protected PIDs: %s", protected)
    else:
        log.warning("[Hygiene] No Robin ecosystem PIDs found!")
    return protected


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
        capture_output=True, text=True, timeout=10,
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

    S122: Now queries Robin ecosystem PIDs via robin_liveness BEFORE
    killing anything. This prevents the F-S121-001 bug where Robin
    and Sentinel were accidentally killed because Get-Process
    CommandLine was empty.

    Args:
        dry_run: If True, report what would be killed without killing.
        cpu_threshold: Only kill processes with CPU time below this (seconds).

    Returns:
        Dict with counts per process type and total memory freed.
    """
    my_pid = os.getpid()
    # S122 FIX (F-S121-001): Query Robin PIDs FIRST, exclude explicitly
    robin_pids = _get_robin_ecosystem_pids()
    excluded_pids = {my_pid} | robin_pids
    results = {
        "killed": {}, "skipped": 0, "freed_mb": 0.0,
        "dry_run": dry_run, "robin_protected": sorted(robin_pids),
    }

    for name in TARGET_NAMES:
        procs = _get_idle_processes(name, cpu_threshold)
        kill_pids = []
        total_mem = 0.0
        for p in procs:
            pid = p.get("Id")
            if not pid or pid in excluded_pids:
                results["skipped"] += 1
                if pid in robin_pids:
                    log.info("[Hygiene] PROTECTED Robin PID %d", pid)
                continue
            mem_mb = round(p.get("WorkingSet64", 0) / 1048576, 1)
            kill_pids.append(pid)
            total_mem += mem_mb
            log.info("[Hygiene] %s PID %d (%.1f MB)",
                     "Would kill" if dry_run else "Queued", pid, mem_mb)

        if not kill_pids:
            results["killed"][name] = 0
            continue

        if dry_run:
            results["killed"][name] = len(kill_pids)
            results["freed_mb"] += total_mem
            continue

        # S87: Batch taskkill -- one call per process type instead of per PID.
        BATCH_SIZE = 50  # Windows command line limit safety
        killed = 0
        for i in range(0, len(kill_pids), BATCH_SIZE):
            batch = kill_pids[i:i + BATCH_SIZE]
            cmd = ["taskkill", "/F"]
            for pid in batch:
                cmd.extend(["/PID", str(pid)])
            try:
                subprocess.run(cmd, capture_output=True, timeout=15)
                killed += len(batch)
            except subprocess.TimeoutExpired:
                log.warning("[Hygiene] Batch kill timed out (%d PIDs)",
                            len(batch))
                killed += len(batch) // 2  # estimate partial success
            except Exception as e:
                log.warning("[Hygiene] Batch kill failed: %s", e)
        results["killed"][name] = killed
        results["freed_mb"] += total_mem

    results["freed_mb"] = round(results["freed_mb"], 1)
    total = sum(results["killed"].values())
    log.info("[Hygiene] %s %d processes, freed ~%.1f MB (protected: %s)",
             "Would kill" if dry_run else "Killed",
             total, results["freed_mb"], sorted(robin_pids))
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
