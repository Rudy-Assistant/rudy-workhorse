"""
Sentinel Boot Phases -- 5-phase boot health cascade.

Extracted from robin_sentinel.py (Session 79, ADR-005 Phase 2b).
Phase 0: Self-check, Phase 1: Services, Phase 2: Agents,
Phase 3: Connectivity, Phase 4: Assessment.
"""

import logging
import platform
import shutil
import socket
import subprocess
import sys
import time

from rudy.agents.sentinel_subprocess import safe_run
from datetime import datetime
from pathlib import Path
from typing import Any

from rudy.paths import (
    HOME,
    REPO_ROOT as RUDY_ROOT,
    RUDY_DATA,
    RUDY_LOGS,
    RUDY_COMMANDS,
)
from rudy.agents.sentinel_immune_memory import load_immune_memory

log = logging.getLogger("robin_sentinel")

ESCALATION_LOG = RUDY_DATA / "robin-escalation.log"


def _escalate(message: str) -> None:
    """Write to escalation log and attempt desktop notification."""
    log.critical("ESCALATION: %s", message)
    with open(ESCALATION_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} | {message}\n")
    try:
        safe_run(
            ["powershell", "-Command",
             f'[System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms"); '
             f'[System.Windows.Forms.MessageBox]::Show("{message}", "Robin Alert", "OK", "Warning")'],
            timeout=5,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------

def phase_0_self_check() -> dict:
    """Verify Robin's own environment is functional."""
    log.info("Phase 0: Self-check")
    status = {"phase": 0, "name": "self_check", "checks": {}, "healthy": True}

    # Python environment
    status["checks"]["python"] = {
        "version": platform.python_version(),
        "ok": sys.version_info >= (3, 10),
    }

    # Can write to disk
    try:
        test_file = RUDY_DATA / ".robin-write-test"
        test_file.write_text("ok")
        test_file.unlink()
        status["checks"]["disk_write"] = {"ok": True}
    except OSError as e:
        status["checks"]["disk_write"] = {"ok": False, "error": str(e)}
        status["healthy"] = False

    # Disk space
    usage = shutil.disk_usage(HOME)
    free_gb = usage.free / (1024**3)
    status["checks"]["disk_space"] = {
        "free_gb": round(free_gb, 1),
        "ok": free_gb > 2.0,
    }
    if free_gb < 2.0:
        status["healthy"] = False
        log.warning("Low disk space: %.1f GB free", free_gb)

    # Ollama responding
    status["checks"]["ollama"] = _check_ollama()

    log.info("Phase 0 complete: %s", "HEALTHY" if status["healthy"] else "DEGRADED")
    return status

def _check_ollama() -> dict:
    """Check if Ollama is responding on localhost:11434."""
    try:
        sock = socket.create_connection(("127.0.0.1", 11434), timeout=3)
        sock.close()
        return {"ok": True}
    except (OSError, socket.timeout):
        # Try to start Ollama
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(3)
            sock = socket.create_connection(("127.0.0.1", 11434), timeout=3)
            sock.close()
            return {"ok": True, "action": "started"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

# ---------------------------------------------------------------------------
# Phase 1: Are critical services alive?
# ---------------------------------------------------------------------------

def phase_1_services(state: dict) -> dict:
    """Check and recover critical Windows services."""
    log.info("Phase 1: Critical services")
    status = {"phase": 1, "name": "critical_services", "services": {}, "healthy": True, "actions": []}

    for svc_key, svc_cfg in state.get("services", {}).items():
        svc_name = svc_cfg.get("name", svc_key)
        svc_status = _check_windows_service(svc_name)
        status["services"][svc_key] = svc_status

        if not svc_status["ok"] and svc_cfg.get("expected") == "running":
            log.warning("Service %s is DOWN — attempting restart", svc_name)
            recovered = _restart_windows_service(svc_name)
            action = f"Restarted {svc_name}: {'success' if recovered else 'FAILED'}"
            status["actions"].append(action)
            log.info(action)
            if not recovered:
                status["healthy"] = False
            if svc_cfg.get("sacred"):
                _escalate(f"SACRED service {svc_name} is DOWN and could not be recovered")

    # Check RustDesk zombie processes
    _check_rustdesk_zombies(state, status)

    log.info("Phase 1 complete: %s", "HEALTHY" if status["healthy"] else "DEGRADED")
    return status

def _check_windows_service(name: str) -> dict:
    """Check Windows service status via sc query."""
    try:
        result = safe_run(
            ["sc", "query", name],
            timeout=10,
        )
        running = "RUNNING" in result.stdout
        return {"ok": running, "state": "running" if running else "stopped"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _restart_windows_service(name: str, max_attempts: int = 3) -> bool:
    """Attempt to restart a Windows service."""
    for attempt in range(max_attempts):
        try:
            safe_run(["sc", "stop", name], timeout=15)
            time.sleep(2)
            result = safe_run(
                ["sc", "start", name],
                timeout=15,
            )
            if result.returncode == 0 or "RUNNING" in result.stdout:
                return True
            time.sleep(3)
        except Exception:
            continue
    return False

def _check_rustdesk_zombies(state: dict, status: dict) -> None:
    """Kill zombie RustDesk processes (the exact cascade that caused the lockout)."""
    rd_cfg = state.get("processes", {}).get("rustdesk", {})
    if not rd_cfg:
        return
    try:
        result = safe_run(
            ["tasklist", "/FI", "IMAGENAME eq rustdesk.exe", "/FO", "CSV", "/NH"],
            timeout=10,
        )
        lines = [line for line in result.stdout.strip().split("\n") if "rustdesk" in line.lower()]
        count = len(lines)
        max_inst = rd_cfg.get("max_instances", 3)

        if count > max_inst and rd_cfg.get("kill_zombies"):
            log.warning("RustDesk has %d instances (max %d) — killing excess", count, max_inst)
            # Kill all, then restart cleanly
            safe_run(["taskkill", "/F", "/IM", "rustdesk.exe"], timeout=10)
            time.sleep(2)
            # Restart RustDesk
            rd_path = Path(r"C:\Program Files\RustDesk\rustdesk.exe")
            if rd_path.exists():
                subprocess.Popen([str(rd_path), "--service"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                status["actions"].append(f"Killed {count} RustDesk zombies, restarted cleanly")
            else:
                status["actions"].append(f"Killed {count} RustDesk zombies, could not find exe to restart")
    except Exception as e:
        log.error("RustDesk zombie check failed: %s", e)

# ---------------------------------------------------------------------------
# Phase 2: Is the agent framework alive?
# ---------------------------------------------------------------------------

def phase_2_agents(state: dict) -> dict:
    """Check that the Rudy agent infrastructure is running."""
    log.info("Phase 2: Agent framework")
    status = {"phase": 2, "name": "agent_framework", "checks": {}, "healthy": True, "actions": []}

    # Check command runner directory exists and is accessible
    status["checks"]["command_queue"] = {
        "ok": RUDY_COMMANDS.exists() and RUDY_COMMANDS.is_dir(),
        "path": str(RUDY_COMMANDS),
    }

    # Check scheduled tasks
    for task_name, task_cfg in state.get("scheduled_tasks", {}).items():
        task_status = _check_scheduled_task(task_name)
        status["checks"][task_name] = task_status
        if not task_status["ok"] and task_cfg.get("expected") == "enabled":
            log.warning("Scheduled task %s is not enabled", task_name)
            status["healthy"] = False

    log.info("Phase 2 complete: %s", "HEALTHY" if status["healthy"] else "DEGRADED")
    return status

def _check_scheduled_task(name: str) -> dict:
    """Check if a Windows scheduled task exists and is enabled."""
    try:
        result = safe_run(
            ["schtasks", "/Query", "/TN", name, "/FO", "CSV", "/NH"],
            timeout=10,
        )
        if result.returncode == 0 and name in result.stdout:
            enabled = "Ready" in result.stdout or "Running" in result.stdout
            return {"ok": enabled, "state": "enabled" if enabled else "disabled"}
        return {"ok": False, "state": "not_found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------------------------------------------------------------------------
# Phase 3: Can I reach the outside world?
# ---------------------------------------------------------------------------

def phase_3_connectivity(state: dict) -> dict:
    """Check internet connectivity and external service reachability."""
    log.info("Phase 3: Connectivity")
    net = state.get("network", {})
    status = {"phase": 3, "name": "connectivity", "checks": {}, "online": False, "actions": []}

    # DNS resolution
    dns_host = net.get("dns_test_host", "api.github.com")
    try:
        ip = socket.gethostbyname(dns_host)
        status["checks"]["dns"] = {"ok": True, "resolved": ip}
    except socket.gaierror:
        status["checks"]["dns"] = {"ok": False}
        log.warning("DNS resolution failed — entering offline mode")
        status["online"] = False
        return status

    # GitHub API reachable (for robin-tasks)
    status["checks"]["github"] = _check_tcp("api.github.com", 443)

    # Email reachable (for alerts)
    email_host = net.get("email_host", "imap.zohomail.com")
    status["checks"]["email"] = _check_tcp(email_host, 993)

    # Tailscale tunnel
    ts_ip = net.get("tailscale_ip")
    if ts_ip:
        status["checks"]["tailscale"] = _check_tcp(ts_ip, 22, timeout=3)

    status["online"] = status["checks"]["dns"]["ok"] and status["checks"]["github"].get("ok", False)

    log.info("Phase 3 complete: %s", "ONLINE" if status["online"] else "OFFLINE")
    return status

def _check_tcp(host: str, port: int, timeout: int = 5) -> dict:
    """Test TCP connectivity to host:port."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return {"ok": True}
    except (OSError, socket.timeout) as e:
        return {"ok": False, "error": str(e)}

# ---------------------------------------------------------------------------
# Phase 4: Full assessment
# ---------------------------------------------------------------------------

def phase_4_assessment(results: list[dict], state: dict) -> dict:
    """Aggregate all phase results into a full system assessment."""
    log.info("Phase 4: Full assessment")

    all_healthy = all(r.get("healthy", r.get("online", True)) for r in results)
    total_actions = sum(len(r.get("actions", [])) for r in results)
    online = any(r.get("online", False) for r in results if r.get("phase") == 3)

    assessment = {
        "phase": 4,
        "name": "full_assessment",
        "timestamp": datetime.now().isoformat(),
        "all_healthy": all_healthy,
        "online": online,
        "total_actions_taken": total_actions,
        "phases": {r["name"]: r for r in results},
        "recommendation": "nominal" if all_healthy else "degraded",
    }

    if not all_healthy:
        issues = []
        for r in results:
            if not r.get("healthy", r.get("online", True)):
                issues.append(r["name"])
        assessment["degraded_systems"] = issues
        log.warning("System DEGRADED: %s", ", ".join(issues))
    else:
        log.info("System NOMINAL — all phases healthy")

    return assessment

# ---------------------------------------------------------------------------
# Night Shift: Robin takes the wheel
# ---------------------------------------------------------------------------


