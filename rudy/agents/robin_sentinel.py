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
    from rudy.robin_taskqueue import seed_standard_tasks, seed_deep_work, process_all
    TASKQUEUE_AVAILABLE = True
except ImportError:
    TASKQUEUE_AVAILABLE = False
from datetime import datetime, timedelta
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

# Backward compatibility: immune memory extracted to sentinel_immune_memory.py (S79)
from rudy.agents.sentinel_immune_memory import (  # noqa: F401
    DEFAULT_KNOWN_GOOD, load_known_good, save_known_good,
    load_immune_memory, record_fix,
)
# ---------------------------------------------------------------------------
# Phase 0: Am I alive?
# Backward compatibility: boot phases extracted to sentinel_boot_phases.py (S79)
from rudy.agents.sentinel_boot_phases import (  # noqa: F401
    phase_0_self_check, _check_ollama,
    phase_1_services, _check_windows_service, _restart_windows_service,
    _check_rustdesk_zombies,
    phase_2_agents, _check_scheduled_task,
    phase_3_connectivity, _check_tcp,
    phase_4_assessment,
)
# Backward compatibility: NightShift was extracted to sentinel_nightshift.py (S79)
from rudy.agents.sentinel_nightshift import NightShift  # noqa: F401
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
    _nightshift_cooldown_until = None  # timestamp-based cooldown (S74 fix)

    def _write_heartbeat(cyc, interval=300):
        """Write sentinel heartbeat — extracted to avoid stale heartbeat (LG-S73-001)."""
        try:
            _hb_path = RUDY_DATA / "coordination" / "sentinel-heartbeat.json"
            _hb_data = {
                "pid": os.getpid(),
                "cycle": cyc,
                "timestamp": datetime.now().isoformat(),
                "poll_interval": interval,
            }
            _hb_tmp = _hb_path.with_suffix(".tmp")
            with open(_hb_tmp, "w") as _hf:
                json.dump(_hb_data, _hf)
            _hb_tmp.replace(_hb_path)
        except Exception:
            pass  # Never let heartbeat IO crash the loop

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

            # S68: Sentinel heartbeat for liveness watchdog
            # S74 FIX (LG-S73-001): extracted to _write_heartbeat() and called
            # at top of loop + after any long operation to prevent stale heartbeat.
            _write_heartbeat(cycle, poll_interval)

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
            # S74 FIX (LG-S73-001): replaced monolithic 4-hour sleep with
            # timestamp-based cooldown so heartbeat keeps ticking.
            _in_cooldown = (
                _nightshift_cooldown_until is not None
                and datetime.now() < _nightshift_cooldown_until
            )
            if not _in_cooldown:
                # S76: Check presence guard before night shift too
                try:
                    from rudy.robin_presence_guard import is_robin_paused
                    if is_robin_paused():
                        log.info("Night shift skipped: Robin paused (kill switch)")
                        _in_cooldown = True  # reuse flag to skip block
                except ImportError:
                    pass
                if not _in_cooldown:
                    ns = NightShift(state, online)
                if not _in_cooldown and ns.should_activate():
                    log.info("Night shift conditions detected — activating")
                    ns.run()
                    _write_heartbeat(cycle, poll_interval)  # refresh after long op
                    # Cooldown: don't run night shift again for 4 hours
                    _nightshift_cooldown_until = datetime.now() + timedelta(hours=4)
                    log.info("Night shift cooldown until %s",
                             _nightshift_cooldown_until.isoformat())

            # Session continuity: perpetual work loop (S70)
            # FIX S71 (LG-S70-001): Run in thread with 120s timeout.
            # FIX S76 (LG-S76-003): PRESENCE GUARD -- never automate Claude
            # while Batman is active at keyboard/mouse. Robin was fighting
            # Batman for control of Claude Desktop. Kill switch support added.
            try:
                from rudy.robin_presence_guard import should_robin_act
                if not should_robin_act():
                    log.info("Presence guard: Batman active or Robin paused "
                             "-- skipping UI automation this cycle")
                else:
                    from rudy.robin_perpetual_loop import check_and_launch_perpetual
                    from concurrent.futures import ThreadPoolExecutor
                    from concurrent.futures import TimeoutError as FuturesTimeout
                    with ThreadPoolExecutor(max_workers=1) as _pool:
                        _future = _pool.submit(check_and_launch_perpetual)
                        try:
                            launch_result = _future.result(timeout=120)
                        except FuturesTimeout:
                            log.warning(
                                "Perpetual loop timed out after 120s "
                                "(LG-S70-001) -- sentinel continuing"
                            )
                            launch_result = None
                    if launch_result and launch_result.get("success"):
                        log.info("Cowork session launched: %s (phase: %s)",
                                 launch_result.get("handoff_used",
                                                   launch_result.get("phase", "?")),
                                 launch_result.get("phase", "?"))
                    elif launch_result and launch_result.get("error"):
                        log.warning("Cowork launch failed: %s",
                                    launch_result.get("error"))
            except Exception as e:
                log.debug("Perpetual loop check skipped: %s", e)

            # Refresh heartbeat after potentially long operations (S74)
            _write_heartbeat(cycle, poll_interval)

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
