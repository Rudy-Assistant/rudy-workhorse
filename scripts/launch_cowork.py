#!/usr/bin/env python3
"""
Intelligent Cowork Session Launcher — PERCEIVE → REASON → ACT → VERIFY.

Uses Windows-MCP Snapshot for perception at every step. Handles popups,
unexpected windows, and focus loss. NOT a dumb macro — assesses screen
state before every action and recovers from disruptions.

Kill switch: Create rudy-data/coordination/robin-pause.flag to stop.
Delete the file (or run robin-resume.bat) to resume.

Usage:
    python launch_cowork.py                          # Launch once
    python launch_cowork.py --handoff "path/to/h.md" # Specific handoff
    python launch_cowork.py --loop                    # Perpetual (45 min)
    python launch_cowork.py --loop --interval 30      # Custom interval
    python launch_cowork.py --kill                    # Create kill switch
    python launch_cowork.py --resume                  # Remove kill switch

S78 — Built after 78 sessions of Robin failing to perpetuate sessions.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO = Path(r"C:\Users\ccimi\rudy-workhorse")
VAULT_HANDOFFS = REPO / "vault" / "Handoffs"
RUDY_DATA = REPO.parent / "rudy-data"
COORD_DIR = RUDY_DATA / "coordination"
STATE_FILE = COORD_DIR / "simple-launcher-state.json"
KILL_SWITCH = COORD_DIR / "robin-pause.flag"
LOG_FILE = RUDY_DATA / "logs" / "launch-cowork.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("launch_cowork")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STEP_PAUSE = 2.0       # Seconds between actions
SNAPSHOT_TIMEOUT = 10   # Max seconds waiting for a snapshot
MAX_LAUNCH_RETRIES = 2  # Retry entire launch sequence
VERIFY_ATTEMPTS = 3     # Snapshot checks after sending prompt
VERIFY_DELAY = 5        # Seconds between verify attempts
LOOP_INTERVAL_MIN = 45  # Default interval for --loop mode
FOCUS_RETRIES = 3       # Attempts to get Claude focused

# Known popup/dialog patterns to dismiss
DISMISS_PATTERNS = [
    # (name_substring, window_substring, action)
    ("OK", "Error", "click"),
    ("Close", "Error", "click"),
    ("OK", "Warning", "click"),
    ("Yes", "Confirm", "click"),
    ("Dismiss", None, "click"),
    ("Got it", None, "click"),
    ("Close", "Update", "click"),
    ("Later", "Update", "click"),
    ("Remind me later", None, "click"),
    ("No", "Restart", "click"),
    ("Cancel", "Shutdown", "click"),
]

# Element regex matching Windows-MCP Snapshot format:
# ID|Window|ControlType|Name|(X, Y)
ELEMENT_RE = re.compile(
    r"(\d+)\|([^|]*)\|([^|]*)\|([^|]*)\|"
    r"\((\d+),\s*(\d+)\)"
)


# ---------------------------------------------------------------------------
# MCP Connection
# ---------------------------------------------------------------------------

def connect_mcp():
    """Connect to Windows-MCP and return a tool-call function."""
    sys.path.insert(0, str(REPO / "rudy"))
    from robin_mcp_client import MCPServerRegistry

    registry = MCPServerRegistry()
    if not registry.connect("windows-mcp"):
        raise RuntimeError("Failed to connect to Windows-MCP server")
    log.info("Windows-MCP connected")

    def wmcp(tool, args=None):
        return registry.call_tool(f"windows-mcp.{tool}", args or {})

    return wmcp, registry


# ---------------------------------------------------------------------------
# Perception — Snapshot parsing & element search
# ---------------------------------------------------------------------------

def parse_elements(snapshot_text):
    """Parse Snapshot output into element dicts."""
    elements = []
    for m in ELEMENT_RE.finditer(snapshot_text):
        elements.append({
            "id": int(m.group(1)),
            "window": m.group(2).strip(),
            "control_type": m.group(3).strip(),
            "name": m.group(4).strip(),
            "x": int(m.group(5)),
            "y": int(m.group(6)),
        })
    return elements


def find(elements, name, window=None, control_type=None):
    """Find element by case-insensitive substring match."""
    pattern = name.lower()
    for el in elements:
        if pattern and pattern not in el["name"].lower():
            continue
        if window and window.lower() not in el["window"].lower():
            continue
        if control_type and control_type.lower() != el["control_type"].lower():
            continue
        return el
    return None


def find_all(elements, name, window=None, control_type=None):
    """Find ALL matching elements."""
    pattern = name.lower()
    results = []
    for el in elements:
        if pattern and pattern not in el["name"].lower():
            continue
        if window and window.lower() not in el["window"].lower():
            continue
        if control_type and control_type.lower() != el["control_type"].lower():
            continue
        results.append(el)
    return results


def snapshot(wmcp):
    """Take a Snapshot and return parsed elements. Never fails silently."""
    result = wmcp("Snapshot", {"use_vision": False})
    if not result.success:
        log.error("Snapshot FAILED: %s", result.error)
        return []
    elements = parse_elements(result.content or "")
    log.info("Snapshot: %d elements, windows: %s",
             len(elements),
             list(set(el["window"] for el in elements))[:10])
    return elements


# ---------------------------------------------------------------------------
# Reasoning — Assess screen state and decide action
# ---------------------------------------------------------------------------

class ScreenState:
    """Assessed state of the screen."""
    CLAUDE_READY = "claude_ready"           # "New task" visible, ready to launch
    CLAUDE_COWORK_SELECT = "cowork_select"  # Mode selection visible
    CLAUDE_PROMPT_READY = "prompt_ready"    # Prompt input visible
    CLAUDE_WORKING = "claude_working"       # Session active (Stop/Thinking/etc)
    CLAUDE_MOUNT_PROMPT = "mount_prompt"    # Allow/Deny dialog
    CLAUDE_UNFOCUSED = "claude_unfocused"   # Claude window exists but not focused
    CLAUDE_NOT_FOUND = "claude_not_found"   # No Claude window visible
    POPUP_BLOCKING = "popup_blocking"       # Some popup/dialog needs dismissal
    UNKNOWN = "unknown"


def assess_state(elements):
    """REASON about current screen state. Returns (ScreenState, detail_dict)."""
    claude_elements = [e for e in elements if "claude" in e["window"].lower()]
    has_claude = len(claude_elements) > 0

    # Check for blocking popups FIRST (non-Claude windows with dialog elements)
    for pattern_name, pattern_window, _ in DISMISS_PATTERNS:
        btn = find(elements, pattern_name,
                   window=pattern_window if pattern_window else None,
                   control_type="Button")
        if btn and "claude" not in btn["window"].lower():
            return ScreenState.POPUP_BLOCKING, {
                "popup_button": btn,
                "popup_window": btn["window"],
            }

    if not has_claude:
        # Check taskbar for Claude
        taskbar_claude = find(elements, "Claude", window="Taskbar")
        return ScreenState.CLAUDE_NOT_FOUND, {
            "taskbar": taskbar_claude,
        }

    # Claude window exists — check specific states
    # Mount prompt (Allow/Deny)
    allow_btn = find(claude_elements, "Allow", control_type="Button")
    deny_btn = find(claude_elements, "Deny", control_type="Button")
    if allow_btn and deny_btn:
        return ScreenState.CLAUDE_MOUNT_PROMPT, {"allow": allow_btn}

    # Session active?
    for indicator in ["Stop", "Progress", "Thinking", "Working", "Generating"]:
        el = find(claude_elements, indicator)
        if el:
            return ScreenState.CLAUDE_WORKING, {"indicator": el}

    # Ready to start new task?
    new_task = find(claude_elements, "New task")
    if new_task:
        return ScreenState.CLAUDE_READY, {"new_task": new_task}

    # Cowork mode selection visible?
    cowork_radio = find(claude_elements, "Cowork", control_type="Radio Button")
    if cowork_radio:
        return ScreenState.CLAUDE_COWORK_SELECT, {"cowork": cowork_radio}

    # Prompt input visible?
    prompt_input = (
        find(claude_elements, "Write your prompt")
        or find(claude_elements, "", control_type="Edit")
    )
    if prompt_input:
        return ScreenState.CLAUDE_PROMPT_READY, {"prompt_input": prompt_input}

    # Claude exists but we can't identify the state
    # Check if Claude is in the window list but maybe behind other windows
    focused = find(elements, "", window="Claude")
    if not focused and has_claude:
        return ScreenState.CLAUDE_UNFOCUSED, {"claude_elements": claude_elements}

    return ScreenState.UNKNOWN, {"claude_elements": claude_elements}


# ---------------------------------------------------------------------------
# Action — Click, type, dismiss
# ---------------------------------------------------------------------------

def click(wmcp, element, label=""):
    """Click an element. Returns True on success."""
    log.info("ACT: Click '%s' at (%d, %d) [%s]",
             element["name"], element["x"], element["y"], label)
    result = wmcp("Click", {"loc": [element["x"], element["y"]]})
    if not result.success:
        log.error("ACT: Click FAILED: %s", result.error)
        return False
    time.sleep(STEP_PAUSE)
    return True


def type_text(wmcp, element, text, clear=True):
    """Type text into an element. Returns True on success."""
    log.info("ACT: Type %d chars into '%s' at (%d, %d)",
             len(text), element["name"], element["x"], element["y"])
    result = wmcp("Type", {
        "loc": [element["x"], element["y"]],
        "text": text,
        "clear": clear,
    })
    if not result.success:
        log.error("ACT: Type FAILED: %s", result.error)
        return False
    time.sleep(0.5)
    return True


def shortcut(wmcp, keys):
    """Send keyboard shortcut."""
    log.info("ACT: Shortcut '%s'", keys)
    result = wmcp("Shortcut", {"shortcut": keys})
    return result.success


def dismiss_popup(wmcp, detail):
    """Dismiss a detected popup by clicking its button."""
    btn = detail["popup_button"]
    log.info("DISMISS: Popup '%s' in '%s' — clicking '%s'",
             detail["popup_window"], btn["window"], btn["name"])
    return click(wmcp, btn, "dismiss popup")


def focus_claude(wmcp, elements):
    """Try to bring Claude to the foreground."""
    # Method 1: Click Claude on taskbar
    taskbar = find(elements, "Claude", window="Taskbar")
    if taskbar:
        log.info("FOCUS: Clicking Claude on taskbar")
        click(wmcp, taskbar, "taskbar Claude")
        return True
    # Method 2: Alt-tab
    log.info("FOCUS: Trying Alt-Tab")
    shortcut(wmcp, "alt+tab")
    time.sleep(1)
    return True


# ---------------------------------------------------------------------------
# Handoff detection
# ---------------------------------------------------------------------------

def find_latest_handoff():
    """Find the most recent handoff file."""
    if not VAULT_HANDOFFS.exists():
        return None
    handoffs = sorted(
        VAULT_HANDOFFS.glob("Session-*-Handoff.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return handoffs[0] if handoffs else None


def build_prompt(handoff_path=None):
    """Build the session prompt."""
    if not handoff_path:
        handoff_path = find_latest_handoff()
    if handoff_path:
        handoff_rel = Path(handoff_path).relative_to(REPO)
        return (
            f"C:\\Users\\ccimi\\rudy-workhorse ; "
            f"Good evening, Alfred. Read {handoff_rel} and follow "
            f"protocols, then proceed."
        )
    return (
        r"C:\Users\ccimi\rudy-workhorse ; "
        "Good evening, Alfred. Read CLAUDE.md and follow protocols, "
        "then proceed."
    )


# ---------------------------------------------------------------------------
# Kill Switch
# ---------------------------------------------------------------------------

def is_killed():
    """Check if the kill switch is active."""
    if KILL_SWITCH.exists():
        log.info("KILL SWITCH active — halting")
        return True
    return False


def create_kill_switch(reason="Manual kill"):
    """Create the kill switch file."""
    KILL_SWITCH.parent.mkdir(parents=True, exist_ok=True)
    KILL_SWITCH.write_text(
        f"Killed at: {datetime.now().isoformat()}\n"
        f"Reason: {reason}\n"
        f"To resume: delete this file or run: python launch_cowork.py --resume\n",
        encoding="utf-8",
    )
    log.info("Kill switch CREATED: %s", reason)


def remove_kill_switch():
    """Remove the kill switch file."""
    if KILL_SWITCH.exists():
        KILL_SWITCH.unlink()
        log.info("Kill switch REMOVED")
        return True
    log.info("Kill switch was not active")
    return False


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def save_state(success, detail=""):
    """Save launch state for external monitoring."""
    COORD_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "last_launch": datetime.now().isoformat(),
        "success": success,
        "detail": detail,
        "pid": os.getpid(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core Launch Sequence
# ---------------------------------------------------------------------------

def launch(wmcp, handoff_path=None):
    """
    PERCEIVE → REASON → ACT → VERIFY launch sequence.

    Returns dict with success, detail, steps taken.
    """
    prompt = build_prompt(handoff_path)
    log.info("=" * 60)
    log.info("LAUNCH START — prompt: %s", prompt[:80])
    log.info("=" * 60)

    result = {"success": False, "steps": [], "detail": ""}

    for attempt in range(MAX_LAUNCH_RETRIES + 1):
        if attempt > 0:
            log.info("RETRY %d/%d", attempt, MAX_LAUNCH_RETRIES)
            time.sleep(STEP_PAUSE)

        # ------------------------------------------------------------------
        # PHASE 0: PERCEIVE + handle disruptions
        # ------------------------------------------------------------------
        for focus_try in range(FOCUS_RETRIES):
            elements = snapshot(wmcp)
            if not elements:
                log.error("Empty snapshot — display issue?")
                time.sleep(3)
                continue

            state, detail = assess_state(elements)
            log.info("STATE: %s (detail keys: %s)", state, list(detail.keys()))

            # Handle popups
            if state == ScreenState.POPUP_BLOCKING:
                dismiss_popup(wmcp, detail)
                continue  # Re-snapshot after dismissal

            # Handle Claude not visible
            if state == ScreenState.CLAUDE_NOT_FOUND:
                focus_claude(wmcp, elements)
                continue  # Re-snapshot after focus attempt

            # Handle Claude unfocused
            if state == ScreenState.CLAUDE_UNFOCUSED:
                focus_claude(wmcp, elements)
                continue

            break  # Got a usable Claude state
        else:
            result["detail"] = "Could not get Claude focused after retries"
            log.error(result["detail"])
            continue  # Outer retry

        # ------------------------------------------------------------------
        # PHASE 1: Handle current state (state machine)
        # ------------------------------------------------------------------

        # If already working, we're done
        if state == ScreenState.CLAUDE_WORKING:
            log.info("Session already active — nothing to launch")
            result["success"] = True
            result["detail"] = "session_already_active"
            break

        # If mount prompt, approve it first
        if state == ScreenState.CLAUDE_MOUNT_PROMPT:
            click(wmcp, detail["allow"], "Allow mount")
            result["steps"].append("approved_mount")
            time.sleep(3)
            # Re-assess
            elements = snapshot(wmcp)
            state, detail = assess_state(elements)

        # STATE: Ready to start (New task visible)
        if state == ScreenState.CLAUDE_READY:
            log.info("STEP 1: Click 'New task'")
            new_task = detail["new_task"]
            if not click(wmcp, new_task, "New task"):
                continue
            result["steps"].append("clicked_new_task")

            # PERCEIVE after click
            time.sleep(1)
            elements = snapshot(wmcp)
            state, detail = assess_state(elements)
            log.info("After New task click: %s", state)

        # STATE: Cowork mode selection
        if state == ScreenState.CLAUDE_COWORK_SELECT:
            log.info("STEP 2: Select Cowork mode")
            cowork = detail.get("cowork") or find(elements, "Cowork",
                                                   window="Claude",
                                                   control_type="Radio Button")
            if cowork:
                click(wmcp, cowork, "Cowork radio")
                result["steps"].append("selected_cowork")
            else:
                log.warning("Cowork radio not found — may already be selected")

            # PERCEIVE after selection
            elements = snapshot(wmcp)
            state, detail = assess_state(elements)

        # STATE: Prompt input ready
        if state == ScreenState.CLAUDE_PROMPT_READY:
            prompt_input = detail.get("prompt_input")
        else:
            # Try to find prompt input regardless of assessed state
            prompt_input = (
                find(elements, "Write your prompt", window="Claude")
                or find(elements, "", window="Claude", control_type="Edit")
            )

        if not prompt_input:
            log.error("Cannot find prompt input field")
            result["detail"] = "no_prompt_input"
            continue

        # ------------------------------------------------------------------
        # PHASE 2: Type prompt
        # ------------------------------------------------------------------
        log.info("STEP 3: Type prompt")
        if not type_text(wmcp, prompt_input, prompt, clear=True):
            result["detail"] = "type_failed"
            continue
        result["steps"].append("typed_prompt")

        # ------------------------------------------------------------------
        # PHASE 3: Click Start task / Send
        # ------------------------------------------------------------------
        elements = snapshot(wmcp)

        # Check for popups again before sending
        state_check, detail_check = assess_state(elements)
        if state_check == ScreenState.POPUP_BLOCKING:
            dismiss_popup(wmcp, detail_check)
            elements = snapshot(wmcp)

        send_btn = (
            find(elements, "Start task", window="Claude", control_type="Button")
            or find(elements, "Start task", window="Claude")
            or find(elements, "Send", window="Claude", control_type="Button")
            or find(elements, "Submit", window="Claude", control_type="Button")
            or find(elements, "Send", window="Claude")
        )
        if send_btn:
            log.info("STEP 4: Click '%s'", send_btn["name"])
            click(wmcp, send_btn, "Send/Start task")
            result["steps"].append("clicked_send")
        else:
            log.warning("No send button found — trying Enter key")
            shortcut(wmcp, "enter")
            result["steps"].append("pressed_enter")
        time.sleep(STEP_PAUSE)

        # ------------------------------------------------------------------
        # PHASE 4: Handle mount prompt (if bypassPermissions is off)
        # ------------------------------------------------------------------
        for poll in range(4):
            elements = snapshot(wmcp)
            state_check, detail_check = assess_state(elements)

            if state_check == ScreenState.POPUP_BLOCKING:
                dismiss_popup(wmcp, detail_check)
                continue

            if state_check == ScreenState.CLAUDE_MOUNT_PROMPT:
                log.info("Mount prompt detected — approving")
                click(wmcp, detail_check["allow"], "Allow mount")
                result["steps"].append("approved_mount")
                time.sleep(2)
                continue

            if state_check == ScreenState.CLAUDE_WORKING:
                log.info("Session is WORKING — mount phase done")
                break

            # No mount prompt, not working yet — wait a bit
            time.sleep(3)

        # ------------------------------------------------------------------
        # PHASE 5: VERIFY — is the session running?
        # ------------------------------------------------------------------
        log.info("VERIFY: Checking session status...")
        verified = False
        for v in range(VERIFY_ATTEMPTS):
            if v > 0:
                time.sleep(VERIFY_DELAY)

            elements = snapshot(wmcp)

            # Dismiss any surprise popups
            state_check, detail_check = assess_state(elements)
            if state_check == ScreenState.POPUP_BLOCKING:
                dismiss_popup(wmcp, detail_check)
                continue

            if state_check == ScreenState.CLAUDE_WORKING:
                log.info("VERIFY: Session CONFIRMED active")
                result["success"] = True
                verified = True
                break

            if state_check == ScreenState.CLAUDE_MOUNT_PROMPT:
                click(wmcp, detail_check["allow"], "Allow mount (late)")
                result["steps"].append("approved_mount_late")
                continue

            # Check for "New task" — means we're back at start (failed)
            if state_check == ScreenState.CLAUDE_READY:
                log.warning("VERIFY: Back at start screen — launch failed")
                break

            # Ambiguous — keep waiting
            log.info("VERIFY: Attempt %d/%d — state: %s, waiting...",
                     v + 1, VERIFY_ATTEMPTS, state_check)

        if not verified and not result["success"]:
            # Last resort: if we're NOT back at start, assume loading
            elements = snapshot(wmcp)
            back_at_start = find(elements, "New task", window="Claude")
            if not back_at_start:
                log.info("VERIFY: Not at start screen — probable success")
                result["success"] = True
                result["detail"] = "probable_success"
            else:
                result["detail"] = "verify_failed"
                continue  # Outer retry

        if result["success"]:
            break

    # Final logging
    if result["success"]:
        log.info("LAUNCH SUCCESS — steps: %s", result["steps"])
        save_state(True, f"steps={result['steps']}")
    else:
        log.error("LAUNCH FAILED after %d attempts — detail: %s",
                  MAX_LAUNCH_RETRIES + 1, result["detail"])
        save_state(False, result["detail"])

    return result


# ---------------------------------------------------------------------------
# Loop Mode — Perpetual Session Launcher
# ---------------------------------------------------------------------------

def run_loop(wmcp, interval_min, handoff_path=None):
    """Run perpetually, launching new sessions when needed."""
    log.info("LOOP MODE: interval=%d min, kill switch=%s",
             interval_min, KILL_SWITCH)
    iteration = 0

    while True:
        iteration += 1
        log.info("--- Loop iteration %d ---", iteration)

        # Kill switch check
        if is_killed():
            log.info("Exiting loop — kill switch active")
            return

        # PERCEIVE current state
        elements = snapshot(wmcp)
        if not elements:
            log.warning("Empty snapshot — waiting 60s")
            time.sleep(60)
            continue

        state, detail = assess_state(elements)
        log.info("Loop state: %s", state)

        # Dismiss any popups even in loop idle
        if state == ScreenState.POPUP_BLOCKING:
            dismiss_popup(wmcp, detail)
            time.sleep(5)
            continue

        # If session is active, wait
        if state == ScreenState.CLAUDE_WORKING:
            log.info("Session active — sleeping %d min", interval_min)
            _interruptible_sleep(interval_min * 60)
            continue

        # If mount prompt, approve immediately
        if state == ScreenState.CLAUDE_MOUNT_PROMPT:
            click(wmcp, detail["allow"], "Allow mount (loop)")
            time.sleep(5)
            continue

        # Claude ready or not found — time to launch
        if state in (ScreenState.CLAUDE_READY, ScreenState.CLAUDE_NOT_FOUND,
                     ScreenState.CLAUDE_UNFOCUSED, ScreenState.UNKNOWN):
            log.info("No active session — launching...")
            result = launch(wmcp, handoff_path)
            if result["success"]:
                log.info("Session launched — sleeping %d min", interval_min)
                _interruptible_sleep(interval_min * 60)
            else:
                log.error("Launch failed — waiting 5 min before retry")
                _interruptible_sleep(300)
            continue

        # Default: wait a bit and re-check
        log.info("Unhandled state %s — waiting 60s", state)
        _interruptible_sleep(60)


def _interruptible_sleep(seconds):
    """Sleep in 30-second chunks, checking kill switch each time."""
    remaining = seconds
    while remaining > 0:
        chunk = min(30, remaining)
        time.sleep(chunk)
        remaining -= chunk
        if is_killed():
            log.info("Kill switch detected during sleep — aborting")
            return


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Intelligent Cowork session launcher")
    parser.add_argument("--handoff", help="Specific handoff file path")
    parser.add_argument("--loop", action="store_true",
                        help="Run perpetually, launching sessions as needed")
    parser.add_argument("--interval", type=int, default=LOOP_INTERVAL_MIN,
                        help=f"Loop interval in minutes (default: {LOOP_INTERVAL_MIN})")
    parser.add_argument("--kill", action="store_true",
                        help="Create kill switch to stop the launcher")
    parser.add_argument("--resume", action="store_true",
                        help="Remove kill switch to resume")
    parser.add_argument("--dry-run", action="store_true",
                        help="Take snapshot and assess state without acting")
    args = parser.parse_args()

    # Kill/resume commands don't need MCP
    if args.kill:
        create_kill_switch("CLI --kill")
        print(f"Kill switch created: {KILL_SWITCH}")
        return
    if args.resume:
        remove_kill_switch()
        print("Kill switch removed — launcher can resume")
        return

    # Check kill switch before connecting
    if is_killed():
        print(f"Kill switch is active: {KILL_SWITCH}")
        print("Run with --resume to clear it")
        return

    # Connect to Windows-MCP
    try:
        wmcp, registry = connect_mcp()
    except Exception as e:
        log.error("Cannot connect to Windows-MCP: %s", e)
        sys.exit(1)

    try:
        if args.dry_run:
            elements = snapshot(wmcp)
            state, detail = assess_state(elements)
            print(f"\nScreen state: {state}")
            print(f"Detail: {json.dumps({k: str(v)[:80] for k, v in detail.items()}, indent=2)}")
            claude_els = [e for e in elements if "claude" in e["window"].lower()]
            print(f"\nClaude elements ({len(claude_els)}):")
            for el in claude_els[:20]:
                print(f"  [{el['control_type']}] '{el['name']}' at ({el['x']}, {el['y']})")
            return

        if args.loop:
            run_loop(wmcp, args.interval, args.handoff)
        else:
            result = launch(wmcp, args.handoff)
            sys.exit(0 if result["success"] else 1)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        try:
            registry.disconnect_all()
        except Exception:
            pass


if __name__ == "__main__":
    main()
