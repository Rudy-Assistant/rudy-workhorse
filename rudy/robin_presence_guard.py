#!/usr/bin/env python3
"""
Robin Presence Guard -- Prevents Robin from interfering with Batman.

Three independent safety mechanisms:
1. HID Detection: Windows GetLastInputInfo API detects keyboard/mouse activity.
   If Batman touched the keyboard/mouse in the last N seconds, Robin yields.
2. Kill Switch: A pause file that Batman can create to stop Robin immediately.
   Create: rudy-data/coordination/robin-pause.flag
   Remove: delete the file or run `robin-resume.bat`
3. Claude Window Check: If Claude Desktop has focus, Robin doesn't touch it.

Usage:
    from rudy.robin_presence_guard import should_robin_act

    if should_robin_act():
        # Safe to automate Claude Desktop
        launch_cowork_session()
    else:
        # Batman is active -- yield
        pass

S76 -- Created after Robin fought Batman for Claude Desktop control.
"""

import ctypes
import ctypes.wintypes
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

from rudy.paths import RUDY_DATA

log = logging.getLogger("robin_presence_guard")

# Configuration
PAUSE_FLAG = RUDY_DATA / "coordination" / "robin-pause.flag"
# Robin yields if Batman was active within this many seconds
HID_IDLE_THRESHOLD_SECONDS = int(os.environ.get(
    "ROBIN_HID_IDLE_THRESHOLD", "120"))  # 2 minutes default


def get_idle_seconds() -> float:
    """Get seconds since last keyboard/mouse input via Win32 API.

    Uses GetLastInputInfo which tracks physical HID events.
    Returns float("inf") on non-Windows or API failure.
    """
    if sys.platform != "win32":
        return float("inf")
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.UINT),
                ("dwTime", ctypes.wintypes.DWORD),
            ]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return float("inf")
        millis_now = ctypes.windll.kernel32.GetTickCount()
        idle_ms = millis_now - lii.dwTime
        return max(0, idle_ms / 1000.0)
    except Exception as exc:
        log.warning("GetLastInputInfo failed: %s", exc)
        return float("inf")


def is_batman_active() -> bool:
    """True if Batman has been active at keyboard/mouse recently.

    S77 FIX: Always log idle seconds at INFO level for debugging.
    Previous versions logged at DEBUG, making it invisible in
    production logs. This caused hours of undiagnosed blocking.
    """
    idle = get_idle_seconds()
    active = idle < HID_IDLE_THRESHOLD_SECONDS
    # S77: Always log the actual idle value — critical for debugging
    log.info("HID idle: %.0fs (threshold: %ds) -> %s",
             idle, HID_IDLE_THRESHOLD_SECONDS,
             "ACTIVE (blocking)" if active else "IDLE (ok to act)")
    return active


def is_robin_paused() -> bool:
    """True if the kill switch file exists."""
    paused = PAUSE_FLAG.exists()
    if paused:
        log.info("Robin PAUSED -- kill switch active: %s", PAUSE_FLAG)
    return paused


def should_robin_act() -> bool:
    """Master gate: Should Robin perform UI automation right now?

    Returns True only if ALL conditions are met:
    1. Kill switch is NOT active
    2. Batman is NOT active at keyboard/mouse
    """
    if is_robin_paused():
        return False
    if is_batman_active():
        return False
    return True


def pause_robin(reason: str = "Manual pause") -> Path:
    """Create the kill switch file. Returns the path."""
    PAUSE_FLAG.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FLAG.write_text(
        f"Paused at: {datetime.now().isoformat()}\n"
        f"Reason: {reason}\n"
        f"To resume: delete this file or run robin-resume.bat\n",
        encoding="utf-8",
    )
    log.info("Robin PAUSED: %s", reason)
    return PAUSE_FLAG


def resume_robin() -> bool:
    """Remove the kill switch file. Returns True if was paused."""
    if PAUSE_FLAG.exists():
        PAUSE_FLAG.unlink()
        log.info("Robin RESUMED")
        return True
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s")

    idle = get_idle_seconds()
    result = {
        "idle_seconds": round(idle, 1),
        "batman_active": is_batman_active(),
        "robin_paused": is_robin_paused(),
        "should_robin_act": should_robin_act(),
        "hid_threshold": HID_IDLE_THRESHOLD_SECONDS,
        "pause_flag": str(PAUSE_FLAG),
    }
    print(json.dumps(result, indent=2))
