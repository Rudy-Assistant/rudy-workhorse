"""
Rudy Command Runner — Cowork-to-Windows Bridge
================================================
Watches Desktop/rudy-commands/ for command files (.cmd, .ps1, .py)
and executes them on the Windows host, writing results back.

This bridges the gap between Cowork (Linux VM) and the Windows host.
From Cowork, Claude writes a command file to the shared Desktop folder.
This runner picks it up, executes it, and writes the result.

Usage:
    python rudy-command-runner.py

File protocol:
    1. Cowork writes: Desktop/rudy-commands/<name>.cmd (or .ps1 or .py)
    2. Runner executes it within 2 seconds
    3. Runner writes: Desktop/rudy-commands/<name>.result
    4. Cowork reads the .result file

Result file format:
    EXIT_CODE=<code>
    --- STDOUT ---
    <stdout>
    --- STDERR ---
    <stderr>
    --- END ---

Auto-starts via Windows Task Scheduler "Rudy-CommandRunner"
"""

import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime

from rudy.paths import RUDY_COMMANDS, RUDY_LOGS, DESKTOP  # noqa: E402

COMMANDS_DIR = RUDY_COMMANDS
COMMANDS_DIR.mkdir(exist_ok=True)
LOG_DIR = RUDY_LOGS
LOG_DIR.mkdir(exist_ok=True)

POLL_INTERVAL = 2  # seconds
COMMAND_TIMEOUT = 120  # seconds max per command

# Allowed extensions and their executors
EXECUTORS = {
    ".cmd": ["cmd", "/c"],
    ".bat": ["cmd", "/c"],
    ".ps1": ["powershell", "-ExecutionPolicy", "Bypass", "-File"],
    ".py":  [sys.executable],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RUNNER] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "command-runner.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("runner")


def execute_command(cmd_file: Path):
    """Execute a command file and write the result."""
    ext = cmd_file.suffix.lower()
    result_file = cmd_file.with_suffix(".result")

    if ext not in EXECUTORS:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write("EXIT_CODE=-1\n")
            f.write("--- STDOUT ---\n")
            f.write("--- STDERR ---\n")
            f.write(f"Unsupported file type: {ext}\n")
            f.write(f"Supported: {', '.join(EXECUTORS.keys())}\n")
            f.write("--- END ---\n")
        return

    executor = EXECUTORS[ext]
    full_cmd = executor + [str(cmd_file)]

    log.info(f"Executing: {cmd_file.name}")

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            cwd=str(DESKTOP),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

        with open(result_file, "w", encoding="utf-8") as f:
            f.write(f"EXIT_CODE={result.returncode}\n")
            f.write("--- STDOUT ---\n")
            f.write(result.stdout or "(empty)\n")
            f.write("--- STDERR ---\n")
            f.write(result.stderr or "(empty)\n")
            f.write("--- END ---\n")

        log.info(f"Completed: {cmd_file.name} (exit={result.returncode})")

    except subprocess.TimeoutExpired:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write("EXIT_CODE=-2\n")
            f.write("--- STDOUT ---\n")
            f.write("--- STDERR ---\n")
            f.write(f"TIMEOUT: Command exceeded {COMMAND_TIMEOUT}s limit\n")
            f.write("--- END ---\n")
        log.error(f"Timeout: {cmd_file.name}")

    except Exception as e:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write("EXIT_CODE=-3\n")
            f.write("--- STDOUT ---\n")
            f.write("--- STDERR ---\n")
            f.write(f"ERROR: {str(e)}\n")
            f.write("--- END ---\n")
        log.error(f"Error executing {cmd_file.name}: {e}")

    finally:
        # Remove the command file after execution
        try:
            cmd_file.unlink()
        except Exception:
            pass


def watch_loop():
    """Main watch loop — poll for new command files."""
    log.info(f"Watching: {COMMANDS_DIR}")
    log.info(f"Supported types: {', '.join(EXECUTORS.keys())}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info(f"Timeout per command: {COMMAND_TIMEOUT}s")

    while True:
        try:
            for item in sorted(COMMANDS_DIR.iterdir()):
                if item.suffix.lower() in EXECUTORS and not item.name.startswith("_"):
                    execute_command(item)
        except Exception as e:
            log.error(f"Watch loop error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  RUDY COMMAND RUNNER — Cowork-to-Windows Bridge")
    log.info(f"  Started: {datetime.now().isoformat()}")
    log.info("=" * 50)

    # Create a readme in the commands dir for discoverability
    readme = COMMANDS_DIR / "_README.txt"
    if not readme.exists():
        readme.write_text(
            "RUDY COMMAND RUNNER\n"
            "===================\n"
            "Drop .cmd, .bat, .ps1, or .py files here.\n"
            "They'll be executed within 2 seconds.\n"
            "Results appear as .result files.\n"
            "\n"
            "This bridges Cowork (Linux VM) to the Windows host.\n"
        )

    try:
        watch_loop()
    except KeyboardInterrupt:
        log.info("Shutting down...")
    except Exception as e:
        log.critical(f"Fatal: {e}")
        sys.exit(1)
