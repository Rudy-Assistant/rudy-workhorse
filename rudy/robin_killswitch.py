#!/usr/bin/env python3
"""
Robin Killswitch -- SUPREME override for all Robin autonomous behavior.

When the killswitch is active, Robin does NOTHING autonomous:
- No nightwatch cycles
- No session launching
- No autonomy engine
- No launcher watcher restarts
- Liveness watchdog skips ensure/restart

The killswitch file lives at: rudy-data/robin-killswitch.json
Format: {"active": true/false, ...}

Batman can toggle via:
    python -m rudy.robin_killswitch --on "reason"
    python -m rudy.robin_killswitch --off
    python -m rudy.robin_killswitch --status

This check is FIRST in every Robin autonomous code path.
No bypasses. No overrides. Batman's word is final.
"""

import json
import logging
from datetime import datetime

from rudy.paths import RUDY_DATA

KILLSWITCH_FILE = RUDY_DATA / "robin-killswitch.json"
log = logging.getLogger("robin_killswitch")



def is_killed() -> bool:
    """Check if the killswitch is active. Returns True = Robin STOP."""
    try:
        if not KILLSWITCH_FILE.exists():
            return False
        with open(KILLSWITCH_FILE) as f:
            data = json.load(f)
        return data.get("active", False) is True
    except (json.JSONDecodeError, OSError, PermissionError):
        return False


def activate(reason: str = "Manual activation") -> dict:
    """Activate the killswitch. Robin stops all autonomous behavior."""
    data = {
        "active": True,
        "activated_at": datetime.now().isoformat(),
        "reason": reason,
    }
    with open(KILLSWITCH_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.warning("KILLSWITCH ACTIVATED: %s", reason)
    return data


def deactivate() -> dict:
    """Deactivate the killswitch. Robin resumes autonomous behavior."""
    data = {
        "active": False,
        "deactivated_at": datetime.now().isoformat(),
    }
    with open(KILLSWITCH_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info("Killswitch deactivated")
    return data


def status() -> dict:
    """Get current killswitch status."""
    try:
        if not KILLSWITCH_FILE.exists():
            return {"active": False, "file_exists": False}
        with open(KILLSWITCH_FILE) as f:
            data = json.load(f)
        data["file_exists"] = True
        return data
    except (json.JSONDecodeError, OSError):
        return {"active": False, "file_exists": True, "error": "parse"}



if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--on" in args:
        idx = args.index("--on")
        reason = " ".join(args[idx + 1:]) or "Manual activation"
        result = activate(reason)
        print(f"Killswitch ON: {reason}")
    elif "--off" in args:
        result = deactivate()
        print("Killswitch OFF")
    elif "--status" in args:
        result = status()
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python -m rudy.robin_killswitch --on/--off/--status")
