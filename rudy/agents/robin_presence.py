#!/usr/bin/env python3

"""
Robin Presence Monitor -- Detects Batman activity and manages handoffs.

This is the glue between Alfred (cloud) and Robin (local). It watches for:
1. Batman activity (HID input, window focus, Cowork sessions)
2. Alfred session lifecycle (start -> active -> idle -> ended)
3. Handoff triggers (explicit command, inactivity, time-of-day)

When Batman goes AFK, Robin takes the wheel. When Batman returns,
Robin yields gracefully and provides a briefing.

ADR-003 defines the handoff protocol:
- Explicit handoff: Batman says "I'm away for N hours"
- Inactivity detection: no HID input for configurable threshold
- Approval routing: Robin can approve on Batman's behalf within scope
- Return detection: HID resume + configurable re-engagement window

Usage:
    python -m rudy.agents.robin_presence                # Start monitoring
    python -m rudy.agents.robin_presence --status       # Current presence state
    python -m rudy.agents.robin_presence --handoff 3    # Explicit 3-hour handoff
    python -m rudy.agents.robin_presence --return       # Signal Batman return
"""

import ctypes
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HOME = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
DESKTOP = HOME / "Desktop"
RUDY_DATA = DESKTOP / "rudy-data"
RUDY_LOGS = DESKTOP / "rudy-logs"
PRESENCE_STATE = RUDY_DATA / "robin-presence.json"
HANDOFF_LOG = RUDY_LOGS / "robin-handoff.log"
COWORK_MARKER = RUDY_LOGS / "last-cowork-activity.txt"

for d in [RUDY_DATA, RUDY_LOGS]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Presence] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(RUDY_LOGS / "robin-presence.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("robin_presence")


# ---------------------------------------------------------------------------
# Presence States
# ---------------------------------------------------------------------------

class PresenceState(str, Enum):
    """Batman's presence states as seen by Robin."""
    ACTIVE = "active"           # Batman is at the keyboard
    IDLE = "idle"               # No HID input for short period (< threshold)
    AFK = "afk"                 # Confirmed away -- Robin can take over
    HANDOFF = "handoff"         # Explicit handoff -- Robin has full authority
    SLEEPING = "sleeping"       # Night hours -- Robin runs night shift
    RETURNING = "returning"     # HID detected after AFK -- re-engagement window


class RobinMode(str, Enum):
    """Robin's operating mode."""
    STANDBY = "standby"         # Batman is active -- Robin monitors only
    SHADOW = "shadow"           # Batman is idle -- Robin pre-stages work
    ACTIVE = "active"           # Batman is AFK -- Robin drives tasks
    NIGHTSHIFT = "nightshift"   # Night mode -- proactive improvement


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "idle_threshold_minutes": 15,       # Minutes of no HID before "idle"
    "afk_threshold_minutes": 120,       # Minutes of no HID before "afk"
    "night_start_hour": 23,             # 11 PM
    "night_end_hour": 6,                # 6 AM
    "return_grace_minutes": 5,          # Minutes after HID resume before full return
    "poll_interval_seconds": 30,        # How often to check HID state
    "cowork_session_timeout_minutes": 60,  # Cowork session assumed dead after this
}


def load_config() -> dict:
    """Load presence config, with defaults."""
    config_file = RUDY_DATA / "presence-config.json"
    config = DEFAULT_CONFIG.copy()
    if config_file.exists():
        try:
            with open(config_file) as f:
                config.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return config


# ---------------------------------------------------------------------------
# HID Activity Detection (Windows)
# ---------------------------------------------------------------------------

class HIDMonitor:
    """
    Monitors human input device activity on Windows.

    Uses GetLastInputInfo from user32.dll to detect keyboard/mouse activity.
    This is the same API Windows uses for screensaver activation.
    """

    def __init__(self):
        self._last_input_info = None
        if sys.platform == "win32":
            self._setup_win32()

    def _setup_win32(self) -> None:
        """Set up Win32 API structures for GetLastInputInfo."""

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("dwTime", ctypes.c_uint),
            ]

        self._LASTINPUTINFO = LASTINPUTINFO
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

    def get_idle_seconds(self) -> float:
        """
        Return seconds since last keyboard/mouse input.

        On non-Windows platforms, returns 0 (always active) as a safe fallback.
        """
        if sys.platform != "win32":
            return 0.0

        try:
            lii = self._LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(lii)
            if self._user32.GetLastInputInfo(ctypes.byref(lii)):
                tick_count = self._kernel32.GetTickCount()
                idle_ms = tick_count - lii.dwTime
                return max(0, idle_ms / 1000.0)
        except Exception as e:
            log.warning("HID monitor error: %s", e)

        return 0.0

    def get_idle_minutes(self) -> float:
        """Return minutes since last input."""
        return self.get_idle_seconds() / 60.0


# ---------------------------------------------------------------------------
# Cowork Session Detection
# ---------------------------------------------------------------------------

class CoworkDetector:
    """Detects whether an Alfred Cowork session is active."""

    def __init__(self, config: dict):
        self.timeout_minutes = config.get("cowork_session_timeout_minutes", 60)

    def is_session_active(self) -> bool:
        """
        Check if a Cowork session appears active.

        Signals:
        - COWORK_MARKER file recently modified (Alfred touches this during sessions)
        - Recent .py/.ps1 files in rudy-commands (dispatched by Cowork)
        """
        # Check Cowork activity marker
        if COWORK_MARKER.exists():
            age_minutes = (
                datetime.now() - datetime.fromtimestamp(COWORK_MARKER.stat().st_mtime)
            ).total_seconds() / 60
            if age_minutes < self.timeout_minutes:
                return True

        # Check for recent command dispatches
        commands_dir = DESKTOP / "rudy-commands"
        if commands_dir.exists():
            for f in commands_dir.iterdir():
                if f.suffix in (".py", ".ps1"):
                    age_minutes = (
                        datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)
                    ).total_seconds() / 60
                    if age_minutes < 10:  # Active command in last 10 minutes
                        return True

        return False

    def get_last_session_time(self) -> Optional[datetime]:
        """Get the last known Cowork session activity time."""
        if COWORK_MARKER.exists():
            return datetime.fromtimestamp(COWORK_MARKER.stat().st_mtime)
        return None


# ---------------------------------------------------------------------------
# Presence State Machine
# ---------------------------------------------------------------------------

class PresenceMonitor:
    """
    Main presence state machine.

    Transitions:
        ACTIVE -> IDLE (no HID for idle_threshold)
        IDLE -> ACTIVE (HID detected)
        IDLE -> AFK (no HID for afk_threshold)
        AFK -> RETURNING (HID detected)
        RETURNING -> ACTIVE (grace period expires with continued HID)
        RETURNING -> AFK (HID was transient -- cat on keyboard)
        * -> HANDOFF (explicit command)
        HANDOFF -> RETURNING (HID detected after handoff window expires)
        * -> SLEEPING (night hours + no activity)
        SLEEPING -> RETURNING (HID detected)
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.hid = HIDMonitor()
        self.cowork = CoworkDetector(self.config)
        self.state = self._load_state()
        self.log = logging.getLogger("presence_monitor")

    def _load_state(self) -> dict:
        """Load persisted presence state."""
        if PRESENCE_STATE.exists():
            try:
                with open(PRESENCE_STATE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "presence": PresenceState.ACTIVE.value,
            "robin_mode": RobinMode.STANDBY.value,
            "last_hid_activity": datetime.now().isoformat(),
            "handoff_until": None,
            "handoff_reason": None,
            "last_state_change": datetime.now().isoformat(),
            "batman_briefing_pending": False,
        }

    def _save_state(self) -> None:
        """Persist current state."""
        tmp = PRESENCE_STATE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=2)
        tmp.replace(PRESENCE_STATE)

    def _transition(self, new_presence: PresenceState, new_mode: RobinMode,
                    reason: str = "") -> None:
        """Execute a state transition with logging."""
        old_presence = self.state["presence"]
        old_mode = self.state["robin_mode"]

        if old_presence == new_presence.value and old_mode == new_mode.value:
            return  # No change

        self.state["presence"] = new_presence.value
        self.state["robin_mode"] = new_mode.value
        self.state["last_state_change"] = datetime.now().isoformat()

        self.log.info(
            "TRANSITION: %s/%s -> %s/%s (%s)",
            old_presence, old_mode, new_presence.value, new_mode.value, reason,
        )

        # Log to handoff log
        with open(HANDOFF_LOG, "a") as f:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "from_presence": old_presence,
                "to_presence": new_presence.value,
                "from_mode": old_mode,
                "to_mode": new_mode.value,
                "reason": reason,
            }
            f.write(json.dumps(entry) + "\n")

        self._save_state()

    def evaluate(self) -> dict:
        """
        Evaluate current state and trigger transitions.

        Returns the current state dict.
        """
        idle_minutes = self.hid.get_idle_minutes()
        now = datetime.now()
        hour = now.hour
        presence = PresenceState(self.state["presence"])
        is_night = (hour >= self.config["night_start_hour"] or
                    hour < self.config["night_end_hour"])
        cowork_active = self.cowork.is_session_active()

        # Update last HID activity if not idle
        if idle_minutes < 1:
            self.state["last_hid_activity"] = now.isoformat()

        # --- State transitions ---

        if presence == PresenceState.ACTIVE:
            if idle_minutes >= self.config["afk_threshold_minutes"]:
                if is_night:
                    self._transition(PresenceState.SLEEPING, RobinMode.NIGHTSHIFT,
                                     f"Night hours + {idle_minutes:.0f}m idle")
                else:
                    self._transition(PresenceState.AFK, RobinMode.ACTIVE,
                                     f"{idle_minutes:.0f}m idle (threshold: "
                                     f"{self.config['afk_threshold_minutes']}m)")
            elif idle_minutes >= self.config["idle_threshold_minutes"]:
                self._transition(PresenceState.IDLE, RobinMode.SHADOW,
                                 f"{idle_minutes:.0f}m idle")

        elif presence == PresenceState.IDLE:
            if idle_minutes < 1:
                self._transition(PresenceState.ACTIVE, RobinMode.STANDBY,
                                 "HID activity resumed")
            elif idle_minutes >= self.config["afk_threshold_minutes"]:
                if is_night:
                    self._transition(PresenceState.SLEEPING, RobinMode.NIGHTSHIFT,
                                     f"Night + {idle_minutes:.0f}m idle")
                else:
                    self._transition(PresenceState.AFK, RobinMode.ACTIVE,
                                     f"{idle_minutes:.0f}m idle")

        elif presence == PresenceState.AFK:
            if idle_minutes < 1:
                self._transition(PresenceState.RETURNING, RobinMode.SHADOW,
                                 "HID detected after AFK")
                self.state["batman_briefing_pending"] = True

        elif presence == PresenceState.HANDOFF:
            # Check if handoff window has expired
            handoff_until = self.state.get("handoff_until")
            if handoff_until:
                expiry = datetime.fromisoformat(handoff_until)
                if now > expiry:
                    if idle_minutes < 1:
                        self._transition(PresenceState.RETURNING, RobinMode.SHADOW,
                                         "Handoff expired + HID detected")
                        self.state["batman_briefing_pending"] = True
                    else:
                        self._transition(PresenceState.AFK, RobinMode.ACTIVE,
                                         "Handoff expired, Batman still away")
            elif idle_minutes < 1:
                self._transition(PresenceState.RETURNING, RobinMode.SHADOW,
                                 "HID detected during open-ended handoff")
                self.state["batman_briefing_pending"] = True

        elif presence == PresenceState.SLEEPING:
            if idle_minutes < 1:
                self._transition(PresenceState.RETURNING, RobinMode.SHADOW,
                                 "HID detected -- Batman waking up")
                self.state["batman_briefing_pending"] = True
            elif not is_night:
                self._transition(PresenceState.AFK, RobinMode.ACTIVE,
                                 "Night ended, Batman still away")

        elif presence == PresenceState.RETURNING:
            grace = self.config["return_grace_minutes"]
            state_change = datetime.fromisoformat(self.state["last_state_change"])
            in_grace = (now - state_change).total_seconds() / 60 < grace

            if in_grace:
                if idle_minutes >= 2:
                    self._transition(PresenceState.AFK, RobinMode.ACTIVE,
                                     "Transient HID during grace -- still AFK")
                    self.state["batman_briefing_pending"] = False
            else:
                if idle_minutes < 1:
                    self._transition(PresenceState.ACTIVE, RobinMode.STANDBY,
                                     "Sustained HID -- Batman confirmed back")
                else:
                    self._transition(PresenceState.AFK, RobinMode.ACTIVE,
                                     "Grace expired without sustained HID")
                    self.state["batman_briefing_pending"] = False

        # Update metadata
        self.state["idle_minutes"] = round(idle_minutes, 1)
        self.state["cowork_active"] = cowork_active
        self.state["is_night"] = is_night
        self.state["evaluated_at"] = now.isoformat()

        self._save_state()
        return self.state

    def explicit_handoff(self, hours: float, reason: str = "Batman requested") -> dict:
        """Batman explicitly hands off to Robin for N hours."""
        until = datetime.now() + timedelta(hours=hours)
        self.state["handoff_until"] = until.isoformat()
        self.state["handoff_reason"] = reason
        self._transition(PresenceState.HANDOFF, RobinMode.ACTIVE,
                         f"Explicit handoff for {hours}h: {reason}")
        return self.state

    def signal_return(self) -> dict:
        """Explicitly signal Batman's return (e.g., from mobile command)."""
        self.state["batman_briefing_pending"] = True
        self.state["handoff_until"] = None
        self.state["handoff_reason"] = None
        self._transition(PresenceState.RETURNING, RobinMode.SHADOW,
                         "Explicit return signal")
        return self.state

    def get_briefing_if_pending(self) -> Optional[dict]:
        """
        Check if a return briefing is pending for Batman.

        Returns briefing data if pending, None otherwise.
        After reading, marks briefing as delivered.
        """
        if not self.state.get("batman_briefing_pending"):
            return None

        # Compile briefing from logs
        briefing = {
            "timestamp": datetime.now().isoformat(),
            "away_since": self.state.get("last_state_change", "unknown"),
            "robin_mode_during_absence": self.state.get("robin_mode", "unknown"),
            "items": [],
        }

        # Check for morning briefing draft
        briefing_file = RUDY_LOGS / "morning-briefing-draft.json"
        if briefing_file.exists():
            try:
                with open(briefing_file) as f:
                    briefing["morning_briefing"] = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # Check night shift log for recent entries
        if HANDOFF_LOG.exists():
            try:
                lines = HANDOFF_LOG.read_text().strip().split("\n")
                recent = [json.loads(line) for line in lines[-20:] if line.strip()]
                briefing["handoff_events"] = recent
            except Exception:
                pass

        self.state["batman_briefing_pending"] = False
        self._save_state()

        return briefing


# ---------------------------------------------------------------------------
# Integration: Robin Task Triggers
# ---------------------------------------------------------------------------

def should_robin_activate(state: dict) -> bool:
    """Check if Robin should be in active mode based on presence state."""
    mode = state.get("robin_mode", RobinMode.STANDBY.value)
    return mode in (RobinMode.ACTIVE.value, RobinMode.NIGHTSHIFT.value)


def should_robin_shadow(state: dict) -> bool:
    """Check if Robin should be in shadow (pre-staging) mode."""
    return state.get("robin_mode") == RobinMode.SHADOW.value


# ---------------------------------------------------------------------------
# Continuous Monitoring
# ---------------------------------------------------------------------------

def run_continuous(config: Optional[dict] = None) -> None:
    """Main monitoring loop."""
    monitor = PresenceMonitor(config)
    poll_interval = monitor.config["poll_interval_seconds"]

    log.info("Robin Presence Monitor starting (poll every %ds)", poll_interval)
    log.info("Thresholds: idle=%dm, afk=%dm, night=%d-%d",
             monitor.config["idle_threshold_minutes"],
             monitor.config["afk_threshold_minutes"],
             monitor.config["night_start_hour"],
             monitor.config["night_end_hour"])

    prev_mode = None

    while True:
        try:
            state = monitor.evaluate()
            current_mode = state.get("robin_mode")

            # Log mode changes
            if current_mode != prev_mode:
                log.info("Robin mode: %s (presence: %s, idle: %.1fm)",
                         current_mode, state["presence"], state["idle_minutes"])
                prev_mode = current_mode

                # Trigger sentinel night shift when entering nightshift mode
                if current_mode == RobinMode.NIGHTSHIFT.value:
                    _trigger_night_shift()

                # Trigger bridge polling when entering active mode
                if current_mode == RobinMode.ACTIVE.value:
                    _trigger_bridge_poll()

            time.sleep(poll_interval)

        except KeyboardInterrupt:
            log.info("Presence monitor shutting down")
            break
        except Exception as e:
            log.error("Monitor loop error: %s", e)
            time.sleep(60)


def _trigger_night_shift() -> None:
    """Signal Robin Sentinel to enter night shift."""
    try:
        from rudy.agents.robin_sentinel import run_night_shift, load_known_good, phase_3_connectivity
        state = load_known_good()
        p3 = phase_3_connectivity(state)
        run_night_shift(state, p3.get("online", False))
    except ImportError:
        log.warning("robin_sentinel not available for night shift trigger")
    except Exception as e:
        log.error("Night shift trigger failed: %s", e)


def _trigger_bridge_poll() -> None:
    """Signal Robin Bridge to poll for pending tasks."""
    try:
        from rudy.agents.robin_bridge import RobinBridge
        bridge = RobinBridge()
        result = bridge.poll_and_execute()
        if result.get("tasks_completed", 0) > 0:
            log.info("Bridge poll: completed %d tasks", result["tasks_completed"])
    except ImportError:
        log.warning("robin_bridge not available for task polling")
    except Exception as e:
        log.error("Bridge poll trigger failed: %s", e)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    if "--status" in args:
        if PRESENCE_STATE.exists():
            state = json.loads(PRESENCE_STATE.read_text())
            print(json.dumps(state, indent=2))
        else:
            print("No presence state -- monitor has not run yet")
        return

    if "--handoff" in args:
        idx = args.index("--handoff")
        hours = float(args[idx + 1]) if idx + 1 < len(args) else 3.0
        reason = " ".join(args[idx + 2:]) if idx + 2 < len(args) else "Batman requested"
        monitor = PresenceMonitor()
        state = monitor.explicit_handoff(hours, reason)
        print(f"Handoff activated for {hours}h. Robin mode: {state['robin_mode']}")
        return

    if "--return" in args:
        monitor = PresenceMonitor()
        state = monitor.signal_return()
        briefing = monitor.get_briefing_if_pending()
        print("Batman return signaled.")
        if briefing:
            print("\n=== ROBIN BRIEFING ===")
            print(json.dumps(briefing, indent=2))
        return

    if "--briefing" in args:
        monitor = PresenceMonitor()
        briefing = monitor.get_briefing_if_pending()
        if briefing:
            print(json.dumps(briefing, indent=2))
        else:
            print("No briefing pending")
        return

    # Default: continuous monitoring
    run_continuous()


if __name__ == "__main__":
    main()
