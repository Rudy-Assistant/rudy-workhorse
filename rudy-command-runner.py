"""
Rudy Command Runner v2 — Cowork-to-Windows Bridge
===================================================
Watches Desktop/rudy-commands/ for command files (.cmd, .ps1, .py)
and executes them on the Windows host, writing results back.

v2 fixes:
- Rename-before-execute prevents duplicate instance conflicts
- File sync wait prevents "file not found" race condition
- Lock file prevents multiple runners from stepping on each other

File protocol:
    1. Cowork writes: Desktop/rudy-commands/<name>.py (or .cmd, .ps1, .bat)
    2. Runner renames to <name>.py.running (atomic claim)
    3. Runner executes it
    4. Runner writes: Desktop/rudy-commands/<name>.result
    5. Runner deletes <name>.py.running
    6. Cowork reads the .result file
"""

import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
COMMANDS_DIR = DESKTOP / "rudy-commands"
COMMANDS_DIR.mkdir(exist_ok=True)
LOG_DIR = DESKTOP / "rudy-logs"
LOG_DIR.mkdir(exist_ok=True)

POLL_INTERVAL = 2  # seconds
COMMAND_TIMEOUT = 120  # seconds max per command
LOCK_FILE = COMMANDS_DIR / "_runner.lock"

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


def acquire_lock():
    """Ensure only one runner instance is active. Kill stale locks."""
    if LOCK_FILE.exists():
        try:
            lock_data = LOCK_FILE.read_text().strip()
            old_pid = int(lock_data)
            # Check if old process is still running
            result = subprocess.run(
                f'tasklist /FI "PID eq {old_pid}" /NH',
                shell=True, capture_output=True, text=True
            )
            if f"{old_pid}" in result.stdout and "python" in result.stdout.lower():
                log.warning(f"Another runner (PID {old_pid}) is active. Exiting.")
                sys.exit(0)
            else:
                log.info(f"Stale lock from PID {old_pid}. Taking over.")
        except (ValueError, Exception):
            log.info("Stale/corrupt lock file. Taking over.")

    LOCK_FILE.write_text(str(os.getpid()))
    log.info(f"Lock acquired (PID {os.getpid()})")


def release_lock():
    """Release the lock file on exit."""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def wait_for_file_ready(file_path: Path, max_wait=10):
    """Wait for a file to be fully written and readable.

    Files synced from Cowork's Linux VM may not be immediately available
    on the Windows filesystem. This waits for the file to stabilize.
    """
    last_size = -1
    stable_count = 0

    for i in range(max_wait * 4):  # Check every 0.25s
        try:
            if file_path.exists():
                current_size = file_path.stat().st_size
                if current_size > 0:
                    # Check if size has stabilized (same for 2 checks)
                    if current_size == last_size:
                        stable_count += 1
                        if stable_count >= 2:
                            # Try reading to confirm not locked
                            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                                content = f.read()
                            if len(content) > 0:
                                return True
                    else:
                        stable_count = 0
                    last_size = current_size
        except (PermissionError, OSError):
            pass
        time.sleep(0.25)
    return False


def execute_command(cmd_file: Path):
    """Execute a command file using rename-before-execute pattern."""
    ext = cmd_file.suffix.lower()
    name_stem = cmd_file.stem
    result_file = cmd_file.with_suffix(".result")

    if ext not in EXECUTORS:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(f"EXIT_CODE=-1\n--- STDOUT ---\n(empty)\n--- STDERR ---\n")
            f.write(f"Unsupported file type: {ext}\n--- END ---\n")
        return

    # === RENAME-BEFORE-EXECUTE ===
    # Atomically claim the file by renaming it. This prevents:
    # 1. Another runner instance from also trying to execute it
    # 2. The file from being modified mid-execution
    # Use _running_ prefix instead of .running suffix so extensions stay valid
    # (PowerShell requires .ps1 extension)
    running_file = cmd_file.parent / f"_running_{cmd_file.name}"
    try:
        cmd_file.rename(running_file)
    except (FileNotFoundError, PermissionError, OSError) as e:
        # Another instance already claimed it, or file disappeared
        log.debug(f"Could not claim {cmd_file.name}: {e}")
        return

    log.info(f"Claimed: {cmd_file.name} → {running_file.name}")

    # Wait for file content to be fully synced
    if not wait_for_file_ready(running_file):
        log.warning(f"File not ready after waiting: {cmd_file.name}")
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(f"EXIT_CODE=-4\n--- STDOUT ---\n(empty)\n--- STDERR ---\n")
            f.write(f"File was not readable after wait (sync issue?)\n--- END ---\n")
        try:
            running_file.unlink()
        except Exception:
            pass
        return

    executor = EXECUTORS[ext]
    full_cmd = executor + [str(running_file)]

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
            f.write(f"--- STDOUT ---\n")
            f.write(result.stdout or "(empty)\n")
            f.write(f"--- STDERR ---\n")
            f.write(result.stderr or "(empty)\n")
            f.write(f"--- END ---\n")

        log.info(f"Completed: {cmd_file.name} (exit={result.returncode})")

    except subprocess.TimeoutExpired:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(f"EXIT_CODE=-2\n--- STDOUT ---\n(empty)\n--- STDERR ---\n")
            f.write(f"TIMEOUT: Command exceeded {COMMAND_TIMEOUT}s limit\n--- END ---\n")
        log.error(f"Timeout: {cmd_file.name}")

    except Exception as e:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(f"EXIT_CODE=-3\n--- STDOUT ---\n(empty)\n--- STDERR ---\n")
            f.write(f"ERROR: {str(e)}\n--- END ---\n")
        log.error(f"Error executing {cmd_file.name}: {e}")

    finally:
        # Clean up the .running file
        try:
            running_file.unlink()
        except Exception:
            pass


def cleanup_stale_running():
    """Clean up any _running_ files left from a previous crash."""
    for item in COMMANDS_DIR.iterdir():
        if item.name.startswith('_running_'):
            age = time.time() - item.stat().st_mtime
            if age > COMMAND_TIMEOUT + 30:
                log.info(f"Cleaning stale: {item.name} (age={age:.0f}s)")
                try:
                    item.unlink()
                except Exception:
                    pass


def watch_loop():
    """Main watch loop — poll for new command files."""
    log.info(f"Watching: {COMMANDS_DIR}")
    log.info(f"Supported types: {', '.join(EXECUTORS.keys())}")
    log.info(f"Poll interval: {POLL_INTERVAL}s, timeout: {COMMAND_TIMEOUT}s")

    cleanup_stale_running()

    while True:
        try:
            for item in sorted(COMMANDS_DIR.iterdir()):
                if (item.suffix.lower() in EXECUTORS
                        and not item.name.startswith("_")):
                    execute_command(item)
        except Exception as e:
            log.error(f"Watch loop error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  RUDY COMMAND RUNNER v2")
    log.info(f"  Started: {datetime.now().isoformat()}")
    log.info(f"  PID: {os.getpid()}")
    log.info("=" * 50)

    acquire_lock()

    # Create a readme in the commands dir
    readme = COMMANDS_DIR / "_README.txt"
    if not readme.exists():
        readme.write_text(
            "RUDY COMMAND RUNNER v2\n"
            "======================\n"
            "Drop .cmd, .bat, .ps1, or .py files here.\n"
            "They'll be picked up within 2 seconds.\n"
            "Results appear as <name>.result files.\n"
            "\n"
            "Protocol: file → renamed to .running → executed → .result written → .running deleted\n"
            "This prevents race conditions with file sync from Cowork.\n"
        )

    try:
        watch_loop()
    except KeyboardInterrupt:
        log.info("Shutting down...")
    except Exception as e:
        log.critical(f"Fatal: {e}")
        sys.exit(1)
    finally:
        release_lock()
