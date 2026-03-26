"""
The Workhorse — Watchdog Service
Monitors critical processes and restarts them if they die.
Runs every 60 seconds. Logs all actions.

Critical services monitored:
  1. RustDesk   — remote desktop access (MUST be running or machine is orphaned)
  2. Tailscale  — VPN mesh networking
  3. Rudy Command Runner — Cowork-to-Windows bridge
  4. Rudy Listener — email command listener

Usage:
    python workhorse-watchdog.py           # Run in foreground
    python workhorse-watchdog.py --once    # Single check then exit
"""

import subprocess
import time
import json
import sys
import os
import logging
from pathlib import Path
from datetime import datetime

# --- Configuration ---
CHECK_INTERVAL = 60  # seconds between checks
LOG_DIR = Path(r"C:\Users\C\Desktop\rudy-logs")
LOG_FILE = LOG_DIR / "watchdog.log"
STATUS_FILE = LOG_DIR / "watchdog-status.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("watchdog")


# --- Service definitions ---
# Each entry: name, check method, restart method
SERVICES = [
    {
        "name": "RustDesk",
        "critical": True,  # If this dies, we lose remote access
        "check": "process",
        "process_name": "rustdesk.exe",
        "restart_cmd": [
            # Try multiple known locations
            r"C:\Program Files\RustDesk\rustdesk.exe",
        ],
        "restart_args": ["--tray"],
        "alt_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\RustDesk\rustdesk.exe"),
            r"C:\Program Files (x86)\RustDesk\rustdesk.exe",
        ]
    },
    {
        "name": "Tailscale",
        "critical": True,
        "check": "service",
        "service_names": ["Tailscale", "Tailscaled"],
        "restart_cmd": "net start Tailscale",
    },
    {
        "name": "Rudy Command Runner",
        "critical": False,
        "check": "process_script",
        "script_pattern": "rudy-command-runner.py",
        "restart_cmd": ["python", r"C:\Users\C\Desktop\rudy-command-runner.py"],
    },
    {
        "name": "Rudy Listener",
        "critical": False,
        "check": "process_script",
        "script_pattern": "rudy-listener.py",
        "restart_cmd": ["python", r"C:\Users\C\Desktop\rudy-listener.py"],
    },
]


def is_process_running(name: str) -> bool:
    """Check if a process is running by image name."""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            text=True, timeout=10, stderr=subprocess.STDOUT
        )
        return name.lower() in out.lower()
    except Exception:
        return False


def is_script_running(pattern: str) -> bool:
    """Check if a Python script is running by checking command lines."""
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", "name='python.exe'", "get", "commandline"],
            text=True, timeout=10, stderr=subprocess.STDOUT
        )
        return pattern.lower() in out.lower()
    except Exception:
        # wmic might not be available, try PowerShell
        try:
            out = subprocess.check_output(
                ["powershell", "-Command",
                 f"Get-Process python -ErrorAction SilentlyContinue | "
                 f"Where-Object {{$_.CommandLine -like '*{pattern}*'}} | "
                 f"Measure-Object | Select-Object -ExpandProperty Count"],
                text=True, timeout=10, stderr=subprocess.STDOUT
            )
            return int(out.strip() or "0") > 0
        except Exception:
            return False


def is_service_running(service_names: list) -> tuple:
    """Check if a Windows service is running. Returns (running, service_name)."""
    for svc in service_names:
        try:
            out = subprocess.check_output(
                ["sc", "query", svc],
                text=True, timeout=10, stderr=subprocess.STDOUT
            )
            if "RUNNING" in out:
                return True, svc
        except Exception:
            continue
    return False, service_names[0] if service_names else "unknown"


def restart_process(svc_def: dict) -> bool:
    """Attempt to restart a service/process."""
    name = svc_def["name"]
    log.warning(f"Restarting {name}...")

    try:
        if svc_def["check"] == "service":
            # Restart Windows service
            svc_name = svc_def.get("service_names", [""])[0]
            subprocess.run(["net", "stop", svc_name], timeout=15,
                           capture_output=True, text=True)
            time.sleep(2)
            result = subprocess.run(["net", "start", svc_name], timeout=15,
                                    capture_output=True, text=True)
            success = result.returncode == 0
            if not success:
                # Try alternate service name
                for alt in svc_def.get("service_names", [])[1:]:
                    result = subprocess.run(["net", "start", alt], timeout=15,
                                            capture_output=True, text=True)
                    if result.returncode == 0:
                        success = True
                        break

        elif svc_def["check"] == "process":
            # Start executable
            exe = svc_def["restart_cmd"][0]
            args = svc_def.get("restart_args", [])

            if not os.path.exists(exe):
                # Try alternate paths
                for alt in svc_def.get("alt_paths", []):
                    if os.path.exists(alt):
                        exe = alt
                        break

            if os.path.exists(exe):
                subprocess.Popen([exe] + args,
                                 creationflags=subprocess.DETACHED_PROCESS)
                success = True
            else:
                log.error(f"  Executable not found for {name}")
                success = False

        elif svc_def["check"] == "process_script":
            # Start Python script
            cmd = svc_def["restart_cmd"]
            script_path = cmd[-1]
            if os.path.exists(script_path):
                subprocess.Popen(
                    cmd,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                success = True
            else:
                log.error(f"  Script not found: {script_path}")
                success = False
        else:
            success = False

        if success:
            log.info(f"  {name} restart initiated")
        else:
            log.error(f"  {name} restart FAILED")
        return success

    except Exception as e:
        log.error(f"  {name} restart error: {e}")
        return False


def check_all() -> dict:
    """Run health checks on all services. Returns status dict."""
    status = {
        "timestamp": datetime.now().isoformat(),
        "services": {},
        "all_healthy": True,
        "actions_taken": []
    }

    for svc_def in SERVICES:
        name = svc_def["name"]
        running = False

        if svc_def["check"] == "process":
            running = is_process_running(svc_def["process_name"])
        elif svc_def["check"] == "service":
            running, _ = is_service_running(svc_def["service_names"])
        elif svc_def["check"] == "process_script":
            running = is_script_running(svc_def["script_pattern"])

        status["services"][name] = {
            "running": running,
            "critical": svc_def["critical"]
        }

        if not running:
            status["all_healthy"] = False
            severity = "CRITICAL" if svc_def["critical"] else "WARNING"
            log.warning(f"{severity}: {name} is NOT running")

            # Attempt restart
            restarted = restart_process(svc_def)
            status["services"][name]["restarted"] = restarted
            status["actions_taken"].append({
                "service": name,
                "action": "restart",
                "success": restarted
            })

            # Verify after short delay
            if restarted:
                time.sleep(5)
                if svc_def["check"] == "process":
                    now_running = is_process_running(svc_def["process_name"])
                elif svc_def["check"] == "service":
                    now_running, _ = is_service_running(svc_def["service_names"])
                elif svc_def["check"] == "process_script":
                    now_running = is_script_running(svc_def["script_pattern"])
                else:
                    now_running = False

                status["services"][name]["verified"] = now_running
                if now_running:
                    log.info(f"  {name} confirmed running after restart")
                else:
                    log.error(f"  {name} still not running after restart!")
        else:
            log.debug(f"OK: {name}")

    # Save status
    try:
        STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception as e:
        log.error(f"Failed to write status file: {e}")

    return status


def main():
    single_run = "--once" in sys.argv

    log.info("=" * 50)
    log.info("Workhorse Watchdog starting")
    log.info(f"Mode: {'single check' if single_run else 'continuous'}")
    log.info(f"Interval: {CHECK_INTERVAL}s")
    log.info("=" * 50)

    if single_run:
        status = check_all()
        healthy = "ALL HEALTHY" if status["all_healthy"] else "ISSUES DETECTED"
        print(f"\nResult: {healthy}")
        for name, info in status["services"].items():
            icon = "OK" if info["running"] else "DOWN"
            crit = " [CRITICAL]" if info["critical"] and not info["running"] else ""
            print(f"  [{icon}] {name}{crit}")
        return

    # Continuous monitoring loop
    consecutive_failures = {}
    while True:
        try:
            status = check_all()

            if status["all_healthy"]:
                # Reset failure counters
                consecutive_failures.clear()
            else:
                for name, info in status["services"].items():
                    if not info["running"]:
                        consecutive_failures[name] = consecutive_failures.get(name, 0) + 1
                        if consecutive_failures[name] >= 5:
                            log.critical(
                                f"{name} has failed {consecutive_failures[name]} "
                                f"consecutive checks! Manual intervention may be needed."
                            )

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log.info("Watchdog stopped by user")
            break
        except Exception as e:
            log.error(f"Watchdog loop error: {e}")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
