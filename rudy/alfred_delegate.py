"""Alfred Delegation Helper -- Cowork-to-Robin delegation via peers broker.

Provides a clean API for any Alfred/Cowork session to delegate tasks to
Robin through the peers-to-taskqueue bridge. Handles the ephemeral peer
ID problem by:
  1. Reading Robin's live ID from bridge-heartbeat.json
  2. Registering Alfred with the caller's real PID
  3. Sending delegation and polling for results

Usage (from Cowork test scripts):
    python rudy/alfred_delegate.py health_check
    python rudy/alfred_delegate.py security_scan
    python rudy/alfred_delegate.py shell --command "Get-Process | Select -First 5"
    python rudy/alfred_delegate.py --status

Usage (as library):
    from rudy.alfred_delegate import delegate_and_wait
    result = delegate_and_wait("health_check", "Check Oracle health")

Lucius Gate: LG-030 - No new dependencies. Uses existing modules.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rudy.paths import RUDY_DATA
from rudy.peers_delegation import (
    create_delegation_message,
    register_peer,
    send_to_peer,
    poll_messages,
)

log = logging.getLogger("alfred.delegate")

HEARTBEAT_FILE = RUDY_DATA / "bridge-heartbeat.json"
PEER_CACHE = RUDY_DATA / "alfred-peer-cache.json"
MAX_HEARTBEAT_AGE = 120  # seconds


def _read_robin_id() -> Optional[str]:
    """Read Robin's peer ID from the bridge heartbeat file."""
    if not HEARTBEAT_FILE.exists():
        log.error("No heartbeat file at %s -- is BridgeRunner running?", HEARTBEAT_FILE)
        return None
    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        age = (time.time() -
               time.mktime(time.strptime(data["timestamp"][:19],
                                          "%Y-%m-%dT%H:%M:%S")))
        if age > MAX_HEARTBEAT_AGE:
            log.warning("Heartbeat is stale (%.0fs old)", age)
        return data.get("robin_id")
    except Exception as e:
        log.error("Failed to read heartbeat: %s", e)
        return None


def _get_alfred_id() -> Optional[str]:
    """Register Alfred with the broker using our real PID.

    Caches the ID so we don't re-register on every call within
    the same process. Cache is invalidated if PID changes.
    """
    # Check in-memory cache
    if hasattr(_get_alfred_id, "_cached"):
        cached_pid, cached_id = _get_alfred_id._cached
        if cached_pid == os.getpid():
            return cached_id

    # Check file cache
    if PEER_CACHE.exists():
        try:
            cache = json.loads(PEER_CACHE.read_text(encoding="utf-8"))
            if cache.get("pid") == os.getpid():
                _get_alfred_id._cached = (os.getpid(), cache["alfred_id"])
                return cache["alfred_id"]
        except Exception:
            pass

    # Register fresh
    alfred_id = register_peer(
        pid=os.getpid(),
        cwd=str(Path(__file__).resolve().parent.parent),
        summary="Alfred (Cowork delegate helper)",
    )
    if alfred_id:
        _get_alfred_id._cached = (os.getpid(), alfred_id)
        try:
            PEER_CACHE.write_text(json.dumps({
                "alfred_id": alfred_id,
                "pid": os.getpid(),
                "registered_at": time.time(),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass
    return alfred_id


def delegate_and_wait(
    task_type: str,
    title: str,
    description: str = "",
    command: Optional[str] = None,
    priority: int = 50,
    timeout_seconds: int = 60,
    poll_interval: int = 3,
) -> dict:
    """Delegate a task to Robin and wait for the result.

    Returns dict with keys: success, output, duration_seconds, error.
    On timeout returns: {"success": False, "error": "timeout"}.
    """
    robin_id = _read_robin_id()
    if not robin_id:
        return {"success": False, "error": "Robin not available (no heartbeat)"}

    alfred_id = _get_alfred_id()
    if not alfred_id:
        return {"success": False, "error": "Failed to register Alfred with broker"}

    # Build and send delegation
    msg_text = create_delegation_message(
        task_type=task_type,
        title=title,
        description=description,
        priority=priority,
        command=command,
    )
    msg_data = json.loads(msg_text)
    del_id = msg_data["id"]

    ok = send_to_peer(alfred_id, robin_id, msg_text)
    if not ok:
        return {"success": False, "error": f"Broker rejected send to {robin_id}"}

    log.info("Delegated [%s] %s (id=%s) to Robin %s", task_type, title, del_id, robin_id)

    # Poll for result
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(poll_interval)
        messages = poll_messages(alfred_id)
        for m in messages:
            if m.get("delegation_id") == del_id or m.get("type") == "result":
                return {
                    "success": m.get("success", False),
                    "output": m.get("output", ""),
                    "error": m.get("error", ""),
                    "duration_seconds": m.get("duration_seconds", 0),
                    "delegation_id": del_id,
                }

    return {"success": False, "error": f"Timeout after {timeout_seconds}s", "delegation_id": del_id}


def delegate_fire_and_forget(
    task_type: str,
    title: str,
    description: str = "",
    command: Optional[str] = None,
    priority: int = 50,
) -> Optional[str]:
    """Delegate a task without waiting for result.

    Returns delegation ID on success, None on failure.
    """
    robin_id = _read_robin_id()
    if not robin_id:
        log.error("Robin not available")
        return None

    alfred_id = _get_alfred_id()
    if not alfred_id:
        log.error("Failed to register Alfred")
        return None

    msg_text = create_delegation_message(
        task_type=task_type,
        title=title,
        description=description,
        priority=priority,
        command=command,
    )
    msg_data = json.loads(msg_text)
    del_id = msg_data["id"]

    ok = send_to_peer(alfred_id, robin_id, msg_text)
    if ok:
        log.info("Delegated [%s] %s (fire-and-forget, id=%s)", task_type, title, del_id)
        return del_id
    return None


def check_bridge_health() -> dict:
    """Check if the bridge runner is healthy."""
    if not HEARTBEAT_FILE.exists():
        return {"healthy": False, "reason": "No heartbeat file"}
    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        age = (time.time() -
               time.mktime(time.strptime(data["timestamp"][:19],
                                          "%Y-%m-%dT%H:%M:%S")))
        return {
            "healthy": age < MAX_HEARTBEAT_AGE,
            "age_seconds": round(age, 1),
            "robin_id": data.get("robin_id"),
            "pid": data.get("pid"),
            "status": data.get("status"),
        }
    except Exception as e:
        return {"healthy": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Alfred Delegation Helper")
    parser.add_argument("task_type", nargs="?", default=None,
                        help="Task type: health_check, security_scan, shell")
    parser.add_argument("--title", default=None, help="Task title")
    parser.add_argument("--command", default=None, help="Shell command (for shell tasks)")
    parser.add_argument("--priority", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--status", action="store_true", help="Check bridge health")
    args = parser.parse_args()

    if args.status:
        health = check_bridge_health()
        print(json.dumps(health, indent=2))
        return

    if not args.task_type:
        parser.print_help()
        return

    title = args.title or f"Alfred CLI: {args.task_type}"
    result = delegate_and_wait(
        task_type=args.task_type,
        title=title,
        command=args.command,
        priority=args.priority,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
