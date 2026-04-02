# CONSOLIDATION NOTE (2026-03-29T16:50:24.074430):
# This file is the Batcave boot resilience and NightShift module.
# The passive SentinelObserver class has been moved to rudy/agents/sentinel.py.
# This file is kept separate because boot resilience (832 lines) is a distinct concern
# from the Sentinel's awareness scanning (993 lines).
# Imported by: robin_main.py (run_boot_sequence), robin_presence.py (run_night_shift)

#!/usr/bin/env python3

"""
Robin Sentinel — The Batcave's Immune System + Night Shift Operator

Robin is two things at once:
1. Boot resilience agent: starts on every boot, recovers services, needs nothing external.
2. Night shift operator: when Batman is AFK, Robin drives improvement forward.

Robin is more than human. Robin monitors all services simultaneously, reasons via
local LLM, maintains perfect failure memory, and acts at machine speed. In the sole
digital survivor scenario — Batman incapacitated, Alfred offline, internet down —
Robin is the only intelligence left.

Registered as Windows Scheduled Task: At startup, run as SYSTEM.
Also runs continuously as the night shift when Batman is inactive.

Usage:
 python -m rudy.agents.robin_sentinel # Full boot sequence
 python -m rudy.agents.robin_sentinel --phase 1 # Run specific phase only
 python -m rudy.agents.robin_sentinel --night-shift # Enter night shift mode
 python -m rudy.agents.robin_sentinel --status # Report current state
"""

import json
import os
import logging
import platform
import shutil
import socket
import subprocess
import sys
import time

# Task queue for autonomous operation
try:
    from rudy.robin_taskqueue import seed_standard_nightwatch, seed_deep_work, process_all
    TASKQUEUE_AVAILABLE = True
except ImportError:
    TASKQUEUE_AVAILABLE = False
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

from rudy.paths import (  # noqa: E402
    HOME,
    REPO_ROOT as RUDY_ROOT,
    RUDY_DATA,
    RUDY_LOGS,
    RUDY_COMMANDS,
)
KNOWN_GOOD_STATE = RUDY_DATA / "known-good-state.json"
ESCALATION_LOG = RUDY_DATA / "robin-escalation.log"
IMMUNE_MEMORY = RUDY_DATA / "robin-immune-memory.json"
SENTINEL_STATUS = RUDY_LOGS / "robin-sentinel-status.json"
NIGHT_SHIFT_LOG = RUDY_LOGS / "robin-night-shift.log"

# Ensure directories exist
for d in [RUDY_DATA, RUDY_LOGS, RUDY_COMMANDS]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Robin] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(RUDY_LOGS / "robin-sentinel.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("robin_sentinel")

# ---------------------------------------------------------------------------
# Known-Good State Management (Immune Memory)
# ---------------------------------------------------------------------------

DEFAULT_KNOWN_GOOD: dict[str, Any] = {
    "version": 2,
    "last_updated": None,
    "services": {
        "Tailscale": {"type": "windows-service", "name": "Tailscale", "expected": "running", "sacred": True},
        "sshd": {"type": "windows-service", "name": "sshd", "expected": "running", "sacred": True},
        "WinRM": {"type": "windows-service", "name": "WinRM", "expected": "running", "sacred": True},
    },
    "processes": {
        "rustdesk": {"max_instances": 3, "kill_zombies": True, "sacred": True},
        "ollama": {"expected": True, "port": 11434},
    },
    "scheduled_tasks": {
        "RudyCommandRunner": {"expected": "enabled"},
        "RudyEmailListener": {"expected": "enabled"},
        "RobinSentinel": {"expected": "enabled"},
    },
    "network": {
        "tailscale_ip": "100.83.49.9",
        "dns_test_host": "api.github.com",
        "email_host": "imap.zohomail.com",
    },
    "recovery_playbook": {},
}

def load_known_good() -> dict:
    """Load known-good state, falling back to defaults."""
    if KNOWN_GOOD_STATE.exists():
        try:
            with open(KNOWN_GOOD_STATE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Corrupted known-good state, using defaults: %s", e)
    return DEFAULT_KNOWN_GOOD.copy()

def save_known_good(state: dict) -> None:
    """Persist known-good state with immune memory updates."""
    state["last_updated"] = datetime.now().isoformat()
    tmp = KNOWN_GOOD_STATE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(KNOWN_GOOD_STATE)

def load_immune_memory() -> dict:
    """Load immune memory — record of what went wrong and what fixed it."""
    if IMMUNE_MEMORY.exists():
        try:
            with open(IMMUNE_MEMORY) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"fixes": [], "patterns": {}}

def record_fix(memory: dict, problem: str, fix: str, success: bool) -> None:
    """Record a fix attempt in immune memory."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "problem": problem,
        "fix": fix,
        "success": success,
    }
    memory["fixes"].append(entry)
    if success:
        memory["patterns"][problem] = fix
    tmp = IMMUNE_MEMORY.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(memory, f, indent=2)
    tmp.replace(IMMUNE_MEMORY)

# ---------------------------------------------------------------------------
# Phase 0: Am I alive?
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
        result = subprocess.run(
            ["sc", "query", name],
            capture_output=True, text=True, timeout=10,
        )
        running = "RUNNING" in result.stdout
        return {"ok": running, "state": "running" if running else "stopped"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _restart_windows_service(name: str, max_attempts: int = 3) -> bool:
    """Attempt to restart a Windows service."""
    for attempt in range(max_attempts):
        try:
            subprocess.run(["sc", "stop", name], capture_output=True, timeout=15)
            time.sleep(2)
            result = subprocess.run(
                ["sc", "start", name],
                capture_output=True, text=True, timeout=15,
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
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq rustdesk.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [line for line in result.stdout.strip().split("\n") if "rustdesk" in line.lower()]
        count = len(lines)
        max_inst = rd_cfg.get("max_instances", 3)

        if count > max_inst and rd_cfg.get("kill_zombies"):
            log.warning("RustDesk has %d instances (max %d) — killing excess", count, max_inst)
            # Kill all, then restart cleanly
            subprocess.run(["taskkill", "/F", "/IM", "rustdesk.exe"], capture_output=True, timeout=10)
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
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", name, "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
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

class NightShift:
    """
    When Batman is AFK, Robin drives improvement forward.

    Triggers:
    - Sentinel detects no Cowork session, no emails, no commands for N hours
    - Alfred explicitly hands off at end of session
    - Time-based: after configurable hour (e.g., 11 PM local)
    - Manual: --night-shift flag

    Night shift activities (priority order):
    1. Process robin-tasks from alfred-skills repo (highest priority — Alfred asked for these)
    2. Run pending improvement tasks from overnight schedule
    3. Self-improvement: review immune memory, optimize recovery playbooks
    4. Research and learning: pull from RSS feeds, check for tool updates
    5. Prepare morning briefing for Batman
    6. Code quality: run linters, tests, dependency checks on rudy-workhorse
    """

    # Away-mode: activate after 15 min of inactivity (was 2h).
    # Override via directive file or ROBIN_INACTIVITY_MINUTES env var.
    INACTIVITY_THRESHOLD_HOURS = float(os.environ.get(
        "ROBIN_INACTIVITY_MINUTES", "15")) / 60
    NIGHT_HOURS = (23, 6)  # 11 PM to 6 AM = automatic night shift consideration

    def __init__(self, state: dict, online: bool = False):
        self.state = state
        self.online = online
        self.log = logging.getLogger("robin_nightshift")

    def should_activate(self) -> bool:
        """Determine if night shift should activate."""
        now = datetime.now()

        # Check if it's nighttime
        hour = now.hour
        is_night = hour >= self.NIGHT_HOURS[0] or hour < self.NIGHT_HOURS[1]

        # Check Batman inactivity (look for recent command files, session markers)
        last_activity = self._detect_last_batman_activity()
        inactive_hours = (now - last_activity).total_seconds() / 3600 if last_activity else float("inf")
        is_inactive = inactive_hours >= self.INACTIVITY_THRESHOLD_HOURS

        self.log.info(
            "Night shift check: night=%s inactive=%.1fh (threshold=%dh)",
            is_night, inactive_hours, self.INACTIVITY_THRESHOLD_HOURS,
        )

        return is_night or is_inactive

    def _detect_last_batman_activity(self) -> Optional[datetime]:
        """Detect when Batman was last active by checking various signals."""
        signals = []

        # Check rudy-commands for recent .py/.ps1 files (dispatched by Cowork)
        if RUDY_COMMANDS.exists():
            for f in RUDY_COMMANDS.iterdir():
                if f.suffix in (".py", ".ps1", ".result"):
                    signals.append(datetime.fromtimestamp(f.stat().st_mtime))

        # Check rudy-logs for recent agent activity triggered by Cowork
        cowork_marker = RUDY_LOGS / "last-cowork-activity.txt"
        if cowork_marker.exists():
            signals.append(datetime.fromtimestamp(cowork_marker.stat().st_mtime))

        return max(signals) if signals else None

    def run(self) -> dict:
        """Execute the night shift using the task queue for autonomous operation."""
        self.log.info("=== ROBIN NIGHT SHIFT ACTIVATED ===")
        results = {"started": datetime.now().isoformat(), "tasks_completed": [], "errors": []}

        try:
            # Phase 1: Seed and run the task queue (primary work engine)
            if TASKQUEUE_AVAILABLE:
                self.log.info("Step 1: Seeding task queue (nightwatch + deep work)")
                seed_standard_nightwatch()
                if self.online:
                    seed_deep_work()
                self.log.info("Step 2: Processing task queue (max 30 min)")
                tq_count = process_all(max_tasks=20, max_minutes=30)
                # process_all returns int (number of tasks processed)
                results["taskqueue"] = tq_count
                self.log.info("Task queue: %d tasks processed", tq_count)
            else:
                self.log.warning("Task queue not available — falling back to legacy steps")
                # Legacy fallback: hardcoded steps
                if self.online:
                    results["bridge_tasks"] = self._run_bridge_tasks()
                results["improvements"] = self._review_immune_memory()
                results["code_quality"] = self._run_code_quality()
                if self.online:
                    results["morning_briefing"] = self._prepare_morning_briefing()

            # Phase 2: Prepare morning briefing (always, task queue or not)
            if self.online:
                self.log.info("Step 3: Preparing morning briefing")
                briefing = self._prepare_morning_briefing()
                results["morning_briefing"] = briefing

        except Exception as e:
            self.log.error("Night shift error: %s", e)
            results["errors"].append(str(e))

        results["ended"] = datetime.now().isoformat()
        self.log.info("=== NIGHT SHIFT COMPLETE ===")

        # Write night shift log
        with open(NIGHT_SHIFT_LOG, "a") as f:
            f.write(json.dumps(results, indent=2) + "\n---\n")

        return results

    def _run_bridge_tasks(self) -> dict:
        """Invoke robin_bridge to process pending tasks from alfred-skills."""
        try:
            from rudy.agents.robin_bridge import RobinBridge
            bridge = RobinBridge()
            return bridge.poll_and_execute()
        except ImportError:
            self.log.warning("robin_bridge not yet available")
            return {"status": "bridge_not_implemented"}
        except Exception as e:
            self.log.error("Bridge task error: %s", e)
            return {"status": "error", "error": str(e)}

    def _review_immune_memory(self) -> dict:
        """Review past failures and see if any patterns suggest preventive action."""
        memory = load_immune_memory()
        fixes = memory.get("fixes", [])
        if not fixes:
            return {"status": "no_history"}

        # Count recurring problems
        problem_counts: dict[str, int] = {}
        for fix in fixes:
            p = fix.get("problem", "unknown")
            problem_counts[p] = problem_counts.get(p, 0) + 1

        recurring = {k: v for k, v in problem_counts.items() if v >= 3}
        if recurring:
            self.log.warning("Recurring problems detected: %s", recurring)
            # TODO: Consult Ollama for deeper analysis of recurring issues
            return {"status": "recurring_issues", "recurring": recurring}

        return {"status": "healthy", "total_fixes": len(fixes)}

    def _run_code_quality(self) -> dict:
        """Run basic code quality checks on rudy-workhorse."""
        rudy_dir = RUDY_ROOT / "rudy"
        if not rudy_dir.exists():
            return {"status": "rudy_dir_not_found"}

        results = {}

        # Try ruff lint
        try:
            result = subprocess.run(
                ["python", "-m", "ruff", "check", str(rudy_dir), "--statistics", "--quiet"],
                capture_output=True, text=True, timeout=60,
            )
            results["ruff"] = {
                "return_code": result.returncode,
                "issues": result.stdout.strip() if result.stdout else "clean",
            }
        except Exception as e:
            results["ruff"] = {"error": str(e)}

        return results

    def _prepare_morning_briefing(self) -> dict:
        """Prepare a morning briefing for Batman."""
        briefing = {
            "timestamp": datetime.now().isoformat(),
            "system_status": "Will be populated by Sentinel assessment",
            "robin_tasks_completed": [],
            "alerts": [],
        }

        # The actual briefing content will be enriched by:
        # - Sentinel health status
        # - Bridge task results
        # - Email check (via email_poller or listener)
        # - Calendar check (if we have API access)
        # For now, write a placeholder that the morning briefing agent can pick up
        briefing_file = RUDY_LOGS / "morning-briefing-draft.json"
        with open(briefing_file, "w") as f:
            json.dump(briefing, f, indent=2)
        return {"status": "draft_prepared", "file": str(briefing_file)}

# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

def _escalate(message: str) -> None:
    """Write to escalation log and attempt desktop notification."""
    log.critical("ESCALATION: %s", message)
    with open(ESCALATION_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} | {message}\n")

    # Try desktop notification (works when user is logged in)
    try:
        subprocess.run(
            ["powershell", "-Command",
             f'[System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms"); '
             f'[System.Windows.Forms.MessageBox]::Show("{message}", "Robin Alert", "OK", "Warning")'],
            capture_output=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass  # Non-critical if notification fails

# ---------------------------------------------------------------------------
# Status Reporting
# ---------------------------------------------------------------------------

def write_status(assessment: dict) -> None:
    """Write current status to disk for other agents to read."""
    tmp = SENTINEL_STATUS.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(assessment, f, indent=2)
    tmp.replace(SENTINEL_STATUS)

def report_to_notion(assessment: dict) -> None:
    """If online, update Notion Watchdog Health Log."""
    try:
        from rudy.tools.notion_client import NotionClient
        client = NotionClient()
        client.append_health_log(assessment)
        log.info("Reported status to Notion")
    except ImportError:
        log.debug("Notion client not available")
    except Exception as e:
        log.warning("Failed to report to Notion: %s", e)

# ---------------------------------------------------------------------------
# Main: Full Boot Sequence
# ---------------------------------------------------------------------------

def run_boot_sequence() -> dict:
    """Execute the full 5-phase boot health cascade."""
    log.info("========================================")
    log.info("ROBIN SENTINEL — Boot sequence initiated")
    log.info("========================================")
    start = time.time()

    state = load_known_good()
    memory = load_immune_memory()
    results = []

    # Phase 0: Self-check
    p0 = phase_0_self_check()
    results.append(p0)
    if not p0["healthy"]:
        _escalate("Phase 0 FAILED — Robin's own environment is broken")

    # Phase 1: Critical services (with boot grace period awareness)
    p1 = phase_1_services(state)
    results.append(p1)
    for action in p1.get("actions", []):
        record_fix(memory, action.split(":")[0], action, "success" in action.lower())

    # Phase 2: Agent framework
    p2 = phase_2_agents(state)
    results.append(p2)

    # Phase 3: Connectivity
    p3 = phase_3_connectivity(state)
    results.append(p3)

    # Phase 4: Full assessment
    assessment = phase_4_assessment(results, state)
    assessment["boot_duration_seconds"] = round(time.time() - start, 1)

    # Persist status
    write_status(assessment)
    save_known_good(state)

    # Report externally if online
    if p3.get("online"):
        report_to_notion(assessment)

    log.info("Boot sequence complete in %.1fs — %s",
             assessment["boot_duration_seconds"],
             "NOMINAL" if assessment["all_healthy"] else "DEGRADED")

    return assessment

def run_night_shift(state: dict, online: bool) -> dict:
    """Enter night shift mode."""
    ns = NightShift(state, online)
    if ns.should_activate():
        return ns.run()
    else:
        log.info("Night shift conditions not met — standing by")
        return {"status": "standby"}

def run_continuous() -> None:
    """
    Main loop: boot sequence, then continuous monitoring.
    After boot, check every 5 minutes. Enter night shift when conditions are met.
    """
    # Initial boot sequence
    assessment = run_boot_sequence()
    state = load_known_good()
    online = assessment.get("online", False)

    # Continuous monitoring loop
    cycle = 0
    while True:
        try:
            # Poll faster (60s) when a directive is active, normal (300s) otherwise
            # LG-S44-001 FIX: Watchdog-based directive detection — zero latency.
            # A file watcher monitors active-directive.json for writes. If Batman
            # creates a directive mid-sleep, the Event fires and Robin wakes instantly.
            try:
                from rudy.robin_autonomy import DirectiveTracker, COORD_DIR
                poll_interval = 60 if DirectiveTracker().has_active_directive() else 300
            except Exception:
                COORD_DIR = None
                poll_interval = 300
            _woke_early = False
            try:
                if COORD_DIR is not None:
                    import threading
                    from watchdog.observers import Observer
                    from watchdog.events import FileSystemEventHandler

                    class _DirectiveHandler(FileSystemEventHandler):
                        def __init__(self, event):
                            self._event = event
                        def on_modified(self, event):
                            if "active-directive" in str(event.src_path):
                                log.info("Directive file changed — waking early")
                                self._event.set()

                    _wake = threading.Event()
                    _obs = Observer()
                    _obs.schedule(_DirectiveHandler(_wake), str(COORD_DIR), recursive=False)
                    _obs.start()
                    _woke_early = _wake.wait(timeout=poll_interval)
                    _obs.stop()
                    _obs.join(timeout=2)
                else:
                    time.sleep(poll_interval)
            except ImportError:
                log.debug("watchdog not installed — falling back to timed sleep")
                time.sleep(poll_interval)
            except Exception:
                time.sleep(poll_interval)
            cycle += 1

            # Quick health check every cycle
            phase_1_services(state)
            p3 = phase_3_connectivity(state)
            online = p3.get("online", False)

            # Log connectivity changes
            if online and not assessment.get("online"):
                log.info("CONNECTIVITY RESTORED — sending queued reports")
                assessment["online"] = True
                report_to_notion(assessment)
            elif not online and assessment.get("online"):
                log.warning("CONNECTIVITY LOST — entering offline mode")
                assessment["online"] = False

            # Check for night shift activation every cycle
            ns = NightShift(state, online)
            if ns.should_activate():
                log.info("Night shift conditions detected — activating")
                ns.run()
                # Don't run night shift again for at least 4 hours
                time.sleep(14400)

            # Session continuity: check if a new Cowork session should launch
            # (S68 patch: continuous loop was missing this — only Sentinel agent
            # called _trigger_handoff, but Sentinel agent wasn't running)
            try:
                from rudy.robin_cowork_launcher import check_and_launch_if_needed
                launch_result = check_and_launch_if_needed()
                if launch_result and launch_result.get("success"):
                    log.info("Cowork session launched: %s", launch_result.get("handoff_used", "latest"))
                elif launch_result and launch_result.get("error"):
                    log.warning("Cowork launch failed: %s", launch_result.get("error"))
            except Exception as e:
                log.debug("Cowork launcher check skipped: %s", e)

            # Full re-assessment every 12 cycles (1 hour)
            if cycle % 12 == 0:
                assessment = run_boot_sequence()

        except KeyboardInterrupt:
            log.info("Robin Sentinel shutting down (keyboard interrupt)")
            break
        except Exception as e:
            log.error("Monitoring loop error (continuing): %s", e)
            _escalate(f"Monitoring loop error: {e}")
            time.sleep(60)  # Back off on error

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    if "--status" in args:
        if SENTINEL_STATUS.exists():
            print(SENTINEL_STATUS.read_text())
        else:
            print("No status file found — Robin has not run yet")
        return

    if "--night-shift" in args:
        state = load_known_good()
        p3 = phase_3_connectivity(state)
        result = run_night_shift(state, p3.get("online", False))
        print(json.dumps(result, indent=2))
        return

    if "--phase" in args:
        idx = args.index("--phase")
        phase = int(args[idx + 1]) if idx + 1 < len(args) else 0
        state = load_known_good()
        if phase == 0:
            print(json.dumps(phase_0_self_check(), indent=2))
        elif phase == 1:
            print(json.dumps(phase_1_services(state), indent=2))
        elif phase == 2:
            print(json.dumps(phase_2_agents(state), indent=2))
        elif phase == 3:
            print(json.dumps(phase_3_connectivity(state), indent=2))
        return

    if "--continuous" in args:
        run_continuous()
        return

    # Default: full boot sequence
    assessment = run_boot_sequence()
    print(json.dumps(assessment, indent=2))

if __name__ == "__main__":
    main()
