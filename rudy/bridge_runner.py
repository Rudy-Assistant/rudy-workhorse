"""rudy.bridge_runner -- Peers Bridge Scheduled Task Runner

Lightweight entry point for running the peers-to-taskqueue bridge as a
Windows Scheduled Task or service. Auto-registers Robin with the broker,
polls for delegations, and writes heartbeat for external monitoring.

Usage:
    C:\\Python312\\python.exe rudy\\bridge_runner.py
    C:\\Python312\\python.exe rudy\\bridge_runner.py --interval 15

Lucius Gate: LG-029 - No new dependencies. Uses existing modules.
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure rudy is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rudy.peers_delegation import register_peer
from rudy.peers_taskqueue_bridge import poll_once
from rudy.paths import RUDY_DATA, REPO_ROOT

# === Configuration ===
DATA_DIR = RUDY_DATA
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "bridge-runner.log"
HEARTBEAT_FILE = DATA_DIR / "bridge-heartbeat.json"
DEFAULT_INTERVAL = 10  # seconds
HEARTBEAT_INTERVAL = 30  # write heartbeat every N seconds

log = logging.getLogger("bridge.runner")


def setup_logging():
    """Configure dual logging: file + console."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

def write_heartbeat(robin_id, iterations=0):
    """Write heartbeat JSON for external health monitoring."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "pid": os.getpid(),
            "robin_id": robin_id,
            "status": "running",
            "iterations": iterations,
        }, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Heartbeat write failed: %s", e)


def check_health():
    """External health check: is heartbeat recent?"""
    if not HEARTBEAT_FILE.exists():
        return False, "No heartbeat file"
    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["timestamp"])
        age = (datetime.now() - ts).total_seconds()
        if age > 120:
            return False, f"Stale heartbeat ({age:.0f}s)"
        return True, f"OK (age={age:.0f}s, pid={data.get('pid')}, iter={data.get('iterations',0)})"
    except Exception as e:
        return False, str(e)

def _signal_handler(signum, _frame):
    log.info("Received signal %d, shutting down...", signum)
    sys.exit(0)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Peers Bridge Runner")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help="Poll interval in seconds")
    parser.add_argument("--max", type=int, default=0,
                        help="Max iterations (0=infinite)")
    parser.add_argument("--health", action="store_true",
                        help="Check health and exit")
    args = parser.parse_args()

    if args.health:
        ok, msg = check_health()
        print(f"{'OK' if ok else 'FAIL'}: {msg}")
        sys.exit(0 if ok else 1)

    setup_logging()
    log.info("=" * 60)
    log.info("Bridge Runner starting (PID %d, interval %ds)",
             os.getpid(), args.interval)
    # Graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Register Robin with the broker
    robin_id = register_peer(
        pid=os.getpid(),
        cwd=str(REPO_ROOT),
        summary="Robin Bridge Runner (scheduled task)",
    )
    log.info("Registered as peer: %s", robin_id)
    write_heartbeat(robin_id)

    # Poll loop with periodic heartbeat (replaces peers_taskqueue_bridge.poll_loop
    # so we can refresh the heartbeat file on every cycle)
    iteration = 0
    last_heartbeat = time.time()
    try:
        while True:
            iteration += 1
            if args.max and iteration > args.max:
                break

            try:
                count = poll_once(robin_id)
                if count:
                    log.info("Processed %d delegation(s) in iteration %d",
                             count, iteration)
            except Exception as e:
                log.error("Poll error: %s", e)

            # Periodic heartbeat refresh
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
                write_heartbeat(robin_id, iterations=iteration)
                last_heartbeat = time.time()

            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Interrupted, exiting")
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        log.info("Bridge Runner stopped after %d iterations", iteration)


if __name__ == "__main__":
    main()
