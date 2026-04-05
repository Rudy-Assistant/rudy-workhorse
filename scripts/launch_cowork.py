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

# Session lock -- prevents competing Cowork launches (S124)
sys.path.insert(0, str(Path(r"C:\Users\ccimi\rudy-workhorse")))
from rudy.session_lock import SessionLock

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO = Path(r"C:\Users\ccimi\rudy-workhorse")
VAULT_HANDOFFS = REPO / "vault" / "Handoffs"
RUDY_DATA = REPO.parent / "rudy-data"
COORD_DIR = RUDY_DATA / "coordination"
STATE_FILE = COORD_DIR / "simple-launcher-state.json"
KILL_SWITCH = COORD_DIR / "robin-pause.flag"
LAST_LAUNCH_TS = COORD_DIR / "last-launch-timestamp"
LOG_FILE = RUDY_DATA / "logs" / "launch-cowork.log"

# Session lock instance (S124)
_session_lock = SessionLock()

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


def check_mcp_health(wmcp):
    """Lightweight MCP health check -- returns True if Snapshot works."""
    try:
        result = wmcp("Snapshot", {"use_vision": False})
        return result.success
    except Exception as e:
        log.warning("MCP health check failed: %s", e)
        return False


def reconnect_mcp(registry):
    """Disconnect stale MCP and reconnect. Returns (wmcp, registry).

    S87: When Windows-MCP connections die (Errno 22 after session cleanup),
    the launcher needs to tear down and rebuild the connection rather than
    spinning forever with a dead MCP.
    """
    log.info("MCP reconnecting...")
    try:
        registry.disconnect_all()
    except Exception:
        pass
    time.sleep(5)
    wmcp, new_registry = connect_mcp()
    log.info("MCP reconnected successfully")
    return wmcp, new_registry

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
    CLAUDE_IDLE = "claude_idle"             # Session open, Alfred done, awaiting input
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

    # Session active? Check for generation indicators.
    # NOTE: "Progress" is the Cowork sidebar panel header — ALWAYS visible,
    # NOT an indicator of active generation. Do NOT include it here.
    # "Stop response" appears only during active generation.
    # "Working on it" / "Thinking" appear during model processing.
    for indicator in ["Stop response", "Thinking", "Working on it", "Generating"]:
        el = find(claude_elements, indicator)
        if el:
            return ScreenState.CLAUDE_WORKING, {"indicator": el}

    # Ready to start new task?
    # NOTE: The sidebar always has a "New task" Link — do NOT match it.
    # Only match a Button, which appears on the landing/empty state.
    # For active sessions that ended, the IDLE→escalation path handles it.
    new_task = find(claude_elements, "New task", control_type="Button")
    if new_task:
        return ScreenState.CLAUDE_READY, {"new_task": new_task}

    # Cowork mode selection visible?
    cowork_radio = find(claude_elements, "Cowork", control_type="Radio Button")
    if cowork_radio:
        return ScreenState.CLAUDE_COWORK_SELECT, {"cowork": cowork_radio}

    # Prompt input visible? This means Alfred finished responding.
    # Distinguish: new-task prompt (during launch flow) vs idle session.
    prompt_input = (
        find(claude_elements, "Write your prompt")
        or find(claude_elements, "", control_type="Edit")
    )
    if prompt_input:
        # If we see session context indicators (Progress, Context, etc.)
        # this is an active session where Alfred stopped — IDLE, needs goading.
        # If we see "Start task" button, this is a fresh task form.
        start_task = find(claude_elements, "Start task", control_type="Button")
        context_btn = find(claude_elements, "Context")
        stop_btn = find(claude_elements, "Stop")
        if start_task:
            # Fresh new-task form
            return ScreenState.CLAUDE_PROMPT_READY, {"prompt_input": prompt_input}
        elif context_btn and not stop_btn:
            # Session open, Alfred done responding, input awaiting
            return ScreenState.CLAUDE_IDLE, {"prompt_input": prompt_input}
        else:
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


def paste_prompt(wmcp, element, text):
    """Paste prompt using clipboard. S85 fix for incomplete prompts.

    Type tool sends keystrokes one-by-one for long strings (~30s for 360 chars).
    Any interruption (focus loss, MCP timeout, UI event) = incomplete prompt.
    Clipboard paste is atomic: full text or nothing.
    """
    import tempfile as _tf
    temp_file = Path(_tf.gettempdir()) / "robin-prompt.txt"
    try:
        temp_file.write_text(text, encoding="utf-8")
    except Exception as exc:
        log.error("PASTE: Cannot write temp file: %s", exc)
        return False
    ps_path = str(temp_file).replace("'", "''")
    clip_result = wmcp("Shell", {
        "command": f"Get-Content '{ps_path}' -Raw | Set-Clipboard",
        "timeout": 5,
    })
    if not clip_result.success:
        log.error("PASTE: Set-Clipboard failed: %s", clip_result.error)
        return False
    log.info("PASTE: Clicking prompt input at (%d, %d)",
             element["x"], element["y"])
    click_result = wmcp("Click", {"loc": [element["x"], element["y"]]})
    if not click_result.success:
        log.error("PASTE: Click failed: %s", click_result.error)
        return False
    time.sleep(0.5)
    shortcut(wmcp, "ctrl+a")
    time.sleep(0.2)
    shortcut(wmcp, "ctrl+v")
    time.sleep(1.0)
    try:
        temp_file.unlink()
    except Exception:
        pass
    log.info("PASTE: %d chars pasted via clipboard", len(text))
    return True


def shortcut(wmcp, keys):
    """Send keyboard shortcut."""
    log.info("ACT: Shortcut '%s'", keys)
    result = wmcp("Shortcut", {"shortcut": keys})
    return result.success


def _scroll_chat_to_bottom(wmcp):
    """Scroll Claude chat to bottom so Allow prompts are in the viewport.

    S102 FIX: Allow buttons rendered below the fold are invisible to
    Snapshot's accessibility tree. Pressing End key scrolls the Electron
    chat to the latest content, making permission dialogs visible.
    """
    try:
        shortcut(wmcp, "End")
        time.sleep(0.5)
    except Exception as exc:
        log.debug("Scroll-to-bottom failed (non-fatal): %s", exc)


def dismiss_popup(wmcp, detail):
    """Dismiss a detected popup by clicking its button."""
    btn = detail["popup_button"]
    log.info("DISMISS: Popup '%s' in '%s' — clicking '%s'",
             detail["popup_window"], btn["window"], btn["name"])
    return click(wmcp, btn, "dismiss popup")


def nuke_all_error_dialogs():
    """Kill ALL python.exe System Error dialogs at once. S80 fix.

    When multiple Python processes crash, each spawns its own error dialog.
    Clicking OK one at a time takes minutes. This kills them in bulk.
    """
    import subprocess as _sp
    try:
        # Kill WerFault.exe (Windows Error Reporting) — these spawn the dialogs
        _sp.run(["taskkill", "/f", "/im", "WerFault.exe"],
                capture_output=True, timeout=10)
        log.info("NUKE: Killed WerFault.exe error dialog processes")
    except Exception as exc:
        log.warning("NUKE: WerFault kill failed: %s", exc)

    try:
        # Also kill any orphaned python processes that are in error state
        # Only kill those with no command line (zombie/crashed processes)
        _sp.run(
            ["powershell", "-Command",
             "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -eq $null } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, text=True, timeout=15
        )
        log.info("NUKE: Cleaned up zombie Python processes")
    except Exception as exc:
        log.warning("NUKE: Zombie cleanup failed: %s", exc)


def ensure_claude_running():
    """Start Claude Desktop if it's not running. S80 fix."""
    import subprocess as _sp
    try:
        r = _sp.run(
            ["powershell", "-Command",
             "Get-Process -Name 'Claude' -ErrorAction SilentlyContinue | "
             "Select-Object Id | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10
        )
        if r.stdout.strip() and r.stdout.strip() != "null":
            log.info("CLAUDE: Already running")
            return True
    except Exception:
        pass

    log.info("CLAUDE: Not running — starting Claude Desktop")
    try:
        claude_path = os.path.expandvars(
            r"%LOCALAPPDATA%\AnthropicClaude\Claude.exe"
        )
        if os.path.exists(claude_path):
            _sp.Popen([claude_path], creationflags=0x00000008)
            log.info("CLAUDE: Started from %s", claude_path)
            time.sleep(8)  # Give Claude time to initialize
            return True
        # Try alternate location
        alt_path = os.path.expandvars(
            r"%LOCALAPPDATA%\Programs\claude-desktop\Claude.exe"
        )
        if os.path.exists(alt_path):
            _sp.Popen([alt_path], creationflags=0x00000008)
            log.info("CLAUDE: Started from %s", alt_path)
            time.sleep(8)
            return True
        log.error("CLAUDE: Cannot find Claude.exe")
        return False
    except Exception as exc:
        log.error("CLAUDE: Start failed: %s", exc)
        return False


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
    # Method 3 (S80): If Claude not found anywhere, start it
    elements2 = snapshot(wmcp)
    if elements2 and not find(elements2, "Claude", window="Taskbar"):
        log.info("FOCUS: Claude not on taskbar — starting it")
        ensure_claude_running()
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


GOAD_PROMPT = (
    "Please continue if context is below 50 percent. "
    "Otherwise, please draft a handoff to "
    "vault/Handoffs/ and end the session."
)


def build_prompt(handoff_path=None):
    """Build the session prompt."""
    if not handoff_path:
        handoff_path = find_latest_handoff()
    if handoff_path:
        # Strip any extra quotes from CLI args
        handoff_path = str(handoff_path).strip('"').strip("'")
        handoff_rel = Path(handoff_path).relative_to(REPO)
        return (
            f"C:\\Users\\ccimi\\rudy-workhorse ; "
            f"Good evening, Alfred. Read {handoff_rel} and follow "
            f"protocols, then proceed. IMPORTANT: Before you stop "
            f"responding, you MUST write a handoff to vault/Handoffs/. "
            f"If context is below 50 percent, keep working. "
            f"If context is above 70 percent, write the handoff "
            f"immediately. Robin will launch the next session."
        )
    return (
        r"C:\Users\ccimi\rudy-workhorse ; "
        "Good evening, Alfred. Read CLAUDE.md and follow protocols, "
        "then proceed. IMPORTANT: Before you stop responding, you "
        "MUST write a handoff to vault/Handoffs/. If context is "
        "below 50 percent, keep working. If context is above 70 "
        "percent, write the handoff immediately. Robin will launch "
        "the next session."
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

def _next_session_number():
    """Determine the next session number from handoff files."""
    try:
        handoffs = sorted(VAULT_HANDOFFS.glob("Session-*-Handoff.md"))
        if handoffs:
            last = handoffs[-1].stem  # Session-123-Handoff
            num = int(last.split("-")[1])
            return num + 1
    except (IndexError, ValueError):
        pass
    return 0


def launch(wmcp, handoff_path=None, force=False):
    """
    PERCEIVE → REASON → ACT → VERIFY launch sequence.

    Args:
        force: If True, launch even if a session appears active.
               Used for testing while a session is running.

    Returns dict with success, detail, steps taken.
    """
    prompt = build_prompt(handoff_path)

    # S124: Acquire session lock before launching
    session_num = _next_session_number()
    if not force and _session_lock.is_locked():
        owner = _session_lock.get_owner()
        log.info("Session lock held by session %s -- skipping launch",
                 owner.get("session_id") if owner else "unknown")
        return {"success": False, "steps": [], "detail": "session_locked"}
    if not _session_lock.acquire(session_id=session_num,
                                 launcher_pid=os.getpid()):
        log.warning("Failed to acquire session lock")
        if not force:
            return {"success": False, "steps": [], "detail": "lock_acquire_failed"}
    log.info("Session lock acquired for session %d", session_num)

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

        # If already working, we're done (unless --force)
        if state == ScreenState.CLAUDE_WORKING and not force:
            log.info("Session already active — nothing to launch")
            result["success"] = True
            result["detail"] = "session_already_active"
            break
        elif state in (ScreenState.CLAUDE_WORKING,
                      ScreenState.CLAUDE_IDLE) and force:
            log.info("Session present but --force set — clicking New task")
            new_task = find(elements, "New task", window="Claude")
            if new_task:
                click(wmcp, new_task, "New task (force)")
                result["steps"].append("clicked_new_task_force")
                time.sleep(3)  # Wait for UI transition
                elements = snapshot(wmcp)
                state, detail = assess_state(elements)
                log.info("After forced New task click: %s", state)
            else:
                log.error("Cannot find 'New task' — aborting force launch")
                result["detail"] = "no_new_task_in_force_mode"
                continue

        # S85 FIX: Always click "New task" from sidebar to ensure
        # we get a fresh task screen. cowork_select is ambiguous --
        # it could be an active session with the radio visible.
        if state not in (ScreenState.CLAUDE_READY,
                         ScreenState.CLAUDE_PROMPT_READY,
                         ScreenState.CLAUDE_MOUNT_PROMPT):
            claude_elements = [e for e in elements
                               if "claude" in e["window"].lower()]
            _nt_link = find(claude_elements, "New task",
                           window="Claude", control_type="Link")
            if _nt_link:
                log.info("S85 SAFETY: Clicking New task from sidebar")
                click(wmcp, _nt_link, "New task (sidebar safety)")
                result["steps"].append("clicked_new_task_safety")
                time.sleep(3)
                elements = snapshot(wmcp)
                if elements:
                    claude_elements = [e for e in elements
                                      if "claude" in e["window"].lower()]
                    state, detail = assess_state(elements)
                    log.info("S85 SAFETY: After New task, state=%s", state)

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
        log.info("STEP 3: Paste prompt (clipboard)")
        if not paste_prompt(wmcp, prompt_input, prompt):
            log.warning("Clipboard paste failed -- falling back to Type")
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
        _touch_launch_timestamp()
    else:
        log.error("LAUNCH FAILED after %d attempts — detail: %s",
                  MAX_LAUNCH_RETRIES + 1, result["detail"])
        save_state(False, result["detail"])

    # S124: Release lock on failure (caller manages on success)
    if not result["success"]:
        _session_lock.release()
        log.info("Session lock released (launch failed)")

    return result


# ---------------------------------------------------------------------------
# S108: 3-Path Stall Recovery — resolves idle sessions in <5 seconds
# ---------------------------------------------------------------------------

STALL_CHECK_INTERVAL = 5  # seconds — max Allow prompt delay (S108 rule)


def stall_recovery(wmcp, elements, handoff_path=None):
    """3-path decision tree for session perpetuation (S108).

    Called when CLAUDE_IDLE detected. Resolves in <5 seconds.

      PATH A: Allow/permission prompt visible -> click Allow
      PATH B: No handoff exists -> goad Alfred to write one
      PATH C: Handoff exists -> launch new session

    Returns: (action_taken: str, should_launch: bool)
    """
    log.info("STALL RECOVERY: 3-path decision tree activated")

    _scroll_chat_to_bottom(wmcp)
    time.sleep(0.5)
    elements = snapshot(wmcp)
    if not elements:
        log.warning("STALL: Empty snapshot during recovery")
        return "snapshot_failed", False

    state, detail = assess_state(elements)

    # --- PATH A: Allow/permission prompt needs feedback ---
    if state == ScreenState.CLAUDE_MOUNT_PROMPT:
        log.info("STALL PATH A: Allow prompt — clicking")
        click(wmcp, detail["allow"], "Allow (stall recovery)")
        time.sleep(2)
        return "allow_clicked", False

    has_handoff = _has_new_handoff()

    # --- PATH C: Handoff exists — launch new session ---
    if has_handoff:
        log.info("STALL PATH C: Handoff exists — launching")
        return "handoff_ready", True

    # --- PATH B: No handoff — goad Alfred ---
    claude_els = [e for e in elements
                  if "claude" in e.get("window", "").lower()]
    prompt_input = (
        find(claude_els, "Reply")
        or find(claude_els, "Write your prompt")
        or find(claude_els, "", control_type="Edit")
    )

    if prompt_input:
        log.info("STALL PATH B: No handoff — goading Alfred")
        type_text(wmcp, prompt_input, GOAD_PROMPT, clear=True)
        time.sleep(0.5)
        send_els = snapshot(wmcp)
        send_btn = (
            find(send_els, "Send", window="Claude",
                 control_type="Button")
            or find(send_els, "Submit", window="Claude",
                    control_type="Button")
        )
        if send_btn:
            click(wmcp, send_btn, "Send (goad)")
        else:
            shortcut(wmcp, "enter")
        return "goaded", False

    new_task = find(elements, "New task", control_type="Button")
    if new_task:
        log.info("STALL: Start screen — launching fresh")
        return "session_ended", True

    return "no_action", False


# ---------------------------------------------------------------------------
# Loop Mode — Perpetual Session Launcher
# ---------------------------------------------------------------------------

def run_loop(wmcp, interval_min, handoff_path=None):
    """Run perpetually, launching new sessions when needed."""
    log.info("LOOP MODE: interval=%d min, kill switch=%s",
             interval_min, KILL_SWITCH)
    # S83: Seed launch timestamp so handoff watcher has a baseline
    if not LAST_LAUNCH_TS.exists():
        _touch_launch_timestamp()
    iteration = 0
    consecutive_popups = 0  # S80: track consecutive popup states
    consecutive_idles = 0   # S81: track consecutive idle states

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
        # S80 FIX: escalate after 3 consecutive popup iterations
        if state == ScreenState.POPUP_BLOCKING:
            consecutive_popups += 1
            if consecutive_popups >= 3:
                log.info("ESCALATE: %d consecutive popups — nuking all "
                         "error dialogs at once", consecutive_popups)
                nuke_all_error_dialogs()
                time.sleep(3)
                # After nuking, check if Claude is still alive
                elements2 = snapshot(wmcp)
                if elements2:
                    claude_visible = find(elements2, "Claude", window="Taskbar")
                    if not claude_visible:
                        log.info("ESCALATE: Claude not visible after popup "
                                 "nuke — starting Claude Desktop")
                        ensure_claude_running()
                consecutive_popups = 0  # Reset after escalation
            else:
                dismiss_popup(wmcp, detail)
            time.sleep(5)
            continue
        else:
            consecutive_popups = 0  # Reset when not in popup state

        # If session is active, wait (with Allow-prompt monitoring)
        if state == ScreenState.CLAUDE_WORKING:
            consecutive_idles = 0  # Reset idle counter
            _session_lock.heartbeat()  # S124: keep lock alive
            log.info("Session active — sleeping %d min (with Allow monitor)",
                     interval_min)
            _interruptible_sleep(interval_min * 60, wmcp=wmcp)
            continue

        # If mount prompt, approve immediately
        if state == ScreenState.CLAUDE_MOUNT_PROMPT:
            click(wmcp, detail["allow"], "Allow mount (loop)")
            time.sleep(5)
            continue

        # S108: Session idle — run 3-path stall recovery instantly.
        # Replaces old 3-iteration escalation (3+ min) with <5s resolution.
        if state == ScreenState.CLAUDE_IDLE:
            consecutive_idles += 1
            log.info("IDLE (count=%d) — stall recovery", consecutive_idles)
            action, should_launch = stall_recovery(wmcp, elements, handoff_path)
            log.info("STALL: action=%s launch=%s", action, should_launch)
            if should_launch:
                consecutive_idles = 0
                result = launch(wmcp, handoff_path)
                if result["success"]:
                    _interruptible_sleep(interval_min * 60, wmcp=wmcp)
                else:
                    _interruptible_sleep(120)
            elif action == "allow_clicked":
                consecutive_idles = 0
                _interruptible_sleep(10, wmcp=wmcp)
            elif action == "goaded":
                _interruptible_sleep(90, wmcp=wmcp)
            else:
                _interruptible_sleep(30, wmcp=wmcp)
            continue

        # Claude ready or not found — time to launch
        if state in (ScreenState.CLAUDE_READY, ScreenState.CLAUDE_NOT_FOUND,
                     ScreenState.CLAUDE_UNFOCUSED, ScreenState.UNKNOWN,
                     ScreenState.CLAUDE_COWORK_SELECT,
                     ScreenState.CLAUDE_PROMPT_READY):
            log.info("No active session — launching...")
            result = launch(wmcp, handoff_path)
            if result["success"]:
                log.info("Session launched — sleeping %d min", interval_min)
                _interruptible_sleep(interval_min * 60, wmcp=wmcp)
            else:
                log.error("Launch failed — waiting 5 min before retry")
                _interruptible_sleep(300)
            continue

        # Default: wait a bit and re-check
        log.info("Unhandled state %s — waiting 60s", state)
        _interruptible_sleep(60)


def _has_new_handoff():
    """Check if a new handoff file appeared since last launch."""
    try:
        if not LAST_LAUNCH_TS.exists():
            return False
        launch_time = LAST_LAUNCH_TS.stat().st_mtime
        for hf in VAULT_HANDOFFS.glob("Session-*-Handoff.md"):
            if hf.stat().st_mtime > launch_time:
                log.info("New handoff detected: %s", hf.name)
                return True
    except Exception:
        pass
    return False


def _touch_launch_timestamp():
    """Record the current time as last launch timestamp."""
    try:
        LAST_LAUNCH_TS.parent.mkdir(parents=True, exist_ok=True)
        LAST_LAUNCH_TS.write_text(datetime.now().isoformat())
    except Exception:
        pass


def _interruptible_sleep(seconds, wmcp=None):
    """Sleep in 30-second chunks, checking kill switch, handoffs, and Allow prompts.

    When wmcp is provided (active session), also polls for Allow/Deny permission
    prompts every 30 seconds and auto-approves them. This keeps the perpetual
    work loop running without human intervention when Alfred triggers
    request_cowork_directory or other permission-gated tools mid-session.

    S101 FIX: Added wmcp parameter for mid-session Allow prompt detection.
    """
    remaining = seconds
    while remaining > 0:
        # S108: 5s polls (not 30s) — Allow prompts caught within 5 seconds
        chunk = min(STALL_CHECK_INTERVAL, remaining)
        time.sleep(chunk)
        remaining -= chunk
        if is_killed():
            log.info("Kill switch detected during sleep — aborting")
            return
        if _has_new_handoff():
            log.info("Handoff trigger — waking launcher early")
            return
        # S101+S102: Check for Allow prompts during active session
        # S102: Scroll to bottom first so off-screen prompts become visible
        if wmcp is not None:
            try:
                _scroll_chat_to_bottom(wmcp)
                elements = snapshot(wmcp)
                if elements:
                    state_check, detail_check = assess_state(elements)
                    if state_check == ScreenState.CLAUDE_MOUNT_PROMPT:
                        log.info("Allow prompt detected during session — "
                                 "auto-approving")
                        click(wmcp, detail_check["allow"],
                              "Allow (mid-session)")
                        time.sleep(2)
                    elif state_check == ScreenState.POPUP_BLOCKING:
                        dismiss_popup(wmcp, detail_check)
                        time.sleep(2)
            except Exception as exc:
                log.debug("Mid-session prompt check failed: %s", exc)


# ---------------------------------------------------------------------------
# Watch Mode — Event-Driven Instant Launch on Handoff
# ---------------------------------------------------------------------------

def run_watch(wmcp, registry):
    """
    Watch vault/Handoffs/ for new files. Launch INSTANTLY when one appears.
    No polling, no idle detection, no goading. Pure event-driven.

    S87: Accepts registry for MCP reconnection. When Snapshot fails N times,
    auto-reconnects instead of spinning with a dead MCP connection.
    """
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    import threading

    MCP_HEALTH_INTERVAL = 10  # Check MCP health every N idle ticks (~5 min)
    MCP_FAIL_THRESHOLD = 3    # Consecutive failures before reconnect

    log.info("WATCH MODE: monitoring %s for new handoffs", VAULT_HANDOFFS)
    VAULT_HANDOFFS.mkdir(parents=True, exist_ok=True)

    launch_event = threading.Event()
    handoff_file = [None]  # mutable container for the handler

    class HandoffHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            name = Path(event.src_path).name
            if name.startswith("Session-") and name.endswith("-Handoff.md"):
                log.info("HANDOFF DETECTED: %s", name)
                handoff_file[0] = event.src_path
                launch_event.set()

        def on_modified(self, event):
            if event.is_directory:
                return
            name = Path(event.src_path).name
            if name.startswith("Session-") and name.endswith("-Handoff.md"):
                if not launch_event.is_set():
                    log.info("HANDOFF MODIFIED: %s", name)
                    handoff_file[0] = event.src_path
                    launch_event.set()

    observer = Observer()
    observer.schedule(HandoffHandler(), str(VAULT_HANDOFFS), recursive=False)
    observer.start()
    idle_ticks = 0  # S85: cold-start fallback counter
    mcp_fail_count = 0  # S87: consecutive MCP failures

    log.info("Watchdog observer started — waiting for handoff files")

    try:
        while True:
            if is_killed():
                log.info("Kill switch active — exiting watch mode")
                break

            # Block until a handoff file appears (or check kill every 30s)
            triggered = launch_event.wait(timeout=30)
            if not triggered:
                idle_ticks += 1
                # S87: Periodic MCP health check -- detect stale connections
                if idle_ticks % MCP_HEALTH_INTERVAL == 0:
                    if check_mcp_health(wmcp):
                        mcp_fail_count = 0
                    else:
                        mcp_fail_count += 1
                        log.warning(
                            "WATCH: MCP health check failed (%d/%d)",
                            mcp_fail_count, MCP_FAIL_THRESHOLD,
                        )
                        if mcp_fail_count >= MCP_FAIL_THRESHOLD:
                            log.info("WATCH: MCP stale -- reconnecting")
                            try:
                                wmcp, registry = reconnect_mcp(registry)
                                mcp_fail_count = 0
                            except Exception as e:
                                log.error(
                                    "WATCH: MCP reconnect failed: %s", e,
                                )
                # S101+S102: Quick Allow-prompt check every 2 ticks (~60s)
                # when a session appears active. Catches mid-session
                # permission dialogs that would stall Alfred.
                # S102: Scroll to bottom first so off-screen prompts visible.
                if idle_ticks % 2 == 0 and LAST_LAUNCH_TS.exists():
                    try:
                        _ls_age = time.time() - LAST_LAUNCH_TS.stat().st_mtime
                        if _ls_age < 3600:  # Session launched <1hr ago
                            _scroll_chat_to_bottom(wmcp)
                            _q_els = snapshot(wmcp)
                            if _q_els:
                                _q_st, _q_det = assess_state(_q_els)
                                if _q_st == ScreenState.CLAUDE_MOUNT_PROMPT:
                                    log.info("WATCH: Allow prompt detected "
                                             "during idle tick — approving")
                                    click(wmcp, _q_det["allow"],
                                          "Allow (watch idle)")
                                    time.sleep(2)
                                elif _q_st == ScreenState.POPUP_BLOCKING:
                                    dismiss_popup(wmcp, _q_det)
                                    time.sleep(2)
                    except Exception as _ap_exc:
                        log.debug("Allow check in watch idle: %s", _ap_exc)

                # S85 SMART FALLBACK: Check every tick (~30s).
                # Uses FILE TIMESTAMPS + STATE FILE only. No UI interaction.
                if True:
                    _should_launch = False
                    _fb_hf = find_latest_handoff()
                    if not _fb_hf:
                        pass  # No handoffs exist yet
                    elif not LAST_LAUNCH_TS.exists():
                        log.info("WATCH FALLBACK: No launch timestamp (cold start)")
                        _should_launch = True
                    else:
                        _launch_mtime = LAST_LAUNCH_TS.stat().st_mtime
                        _handoff_mtime = _fb_hf.stat().st_mtime
                        _age_sec = time.time() - _launch_mtime
                        _age_min = _age_sec / 60
                        if _handoff_mtime > _launch_mtime:
                            log.info("WATCH FALLBACK: Handoff %s newer than launch -> session ended",
                                     _fb_hf.name)
                            _should_launch = True
                        else:
                            _last_ok = False
                            try:
                                _sj = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                                _last_ok = _sj.get("success", False)
                            except Exception:
                                pass
                            if not _last_ok and _age_sec > 30:
                                log.info("WATCH FALLBACK: Last launch FAILED, %.0fs ago -> retrying",
                                         _age_sec)
                                _should_launch = True
                            elif _last_ok and _age_min > 45:
                                log.info("WATCH FALLBACK: Last launch stale (%.0f min) -> relaunching",
                                         _age_min)
                                _should_launch = True
                            elif idle_ticks % 20 == 0:
                                log.info("WATCH STATUS: Session running (%.0f min, ok=%s)",
                                         _age_min, _last_ok)
                    if _should_launch and _fb_hf:
                        log.info("WATCH FALLBACK: Launching with %s", _fb_hf.name)
                        handoff_file[0] = str(_fb_hf)
                        idle_ticks = 0
                        launch_event.set()
                continue  # Back to top of loop — loop back to check kill switch

            # Handoff detected — launch immediately
            launch_event.clear()
            hf = handoff_file[0]
            log.info("LAUNCHING from handoff: %s", hf)

            # Small delay to let the file finish writing
            time.sleep(2)

            # Attempt launch (force=True: end current session if active)
            launch_succeeded = False
            for attempt in range(3):
                # S90: Reconnect MCP before each attempt if prior failed
                if attempt > 0:
                    try:
                        wmcp, registry = reconnect_mcp(registry)
                    except Exception as _re:
                        log.error("WATCH: MCP reconnect before attempt %d "
                                  "failed: %s", attempt + 1, _re)
                result = launch(wmcp, hf, force=True)
                if result["success"]:
                    log.info("WATCH: Session launched successfully")
                    launch_succeeded = True
                    break
                log.warning("WATCH: Launch attempt %d failed — retrying "
                            "in 10s", attempt + 1)
                time.sleep(10)

            # S90 FIX: If ALL attempts failed, do NOT enter wait loop.
            # Reset and go back to watching for the next handoff trigger.
            if not launch_succeeded:
                log.error("WATCH: All 3 launch attempts FAILED — "
                          "resetting to watch mode (will retry on next "
                          "handoff or fallback tick)")
                # Try to reconnect MCP for next cycle
                try:
                    wmcp, registry = reconnect_mcp(registry)
                except Exception as _re:
                    log.error("WATCH: MCP reconnect after total failure: "
                              "%s", _re)
                idle_ticks = 0
                continue  # Back to top of while True loop

            # After SUCCESSFUL launch, wait for session to end before
            # watching again (check every 60s if session is still active)
            log.info("WATCH: Waiting for session to complete...")
            empty_snapshot_count = 0
            MAX_EMPTY_SNAPSHOTS = 10  # ~10 min of dead MCP before giving up
            while True:
                if is_killed():
                    break
                time.sleep(60)
                # S87: Wrap snapshot with MCP reconnect
                # S102: Scroll to bottom before snapshot so Allow is visible
                _scroll_chat_to_bottom(wmcp)
                try:
                    elements = snapshot(wmcp)
                except Exception as _mcp_err:
                    log.warning("WATCH: MCP error during wait: %s", _mcp_err)
                    try:
                        wmcp, registry = reconnect_mcp(registry)
                    except Exception as _re:
                        log.error("WATCH: MCP reconnect failed: %s", _re)
                    empty_snapshot_count += 1
                    if empty_snapshot_count >= MAX_EMPTY_SNAPSHOTS:
                        log.error("WATCH: %d consecutive MCP failures in "
                                  "wait loop — breaking to watch mode",
                                  MAX_EMPTY_SNAPSHOTS)
                        break
                    continue
                if not elements:
                    empty_snapshot_count += 1
                    if empty_snapshot_count >= MAX_EMPTY_SNAPSHOTS:
                        log.error("WATCH: %d consecutive empty snapshots — "
                                  "breaking to watch mode",
                                  MAX_EMPTY_SNAPSHOTS)
                        break
                    continue
                empty_snapshot_count = 0  # Reset on success
                state, detail = assess_state(elements)
                # S101: Auto-approve Allow prompts during active session
                if state == ScreenState.CLAUDE_MOUNT_PROMPT:
                    log.info("WATCH: Allow prompt during session — "
                             "auto-approving")
                    click(wmcp, detail["allow"],
                          "Allow (mid-session watch)")
                    time.sleep(2)
                    continue
                if state == ScreenState.POPUP_BLOCKING:
                    dismiss_popup(wmcp, detail)
                    time.sleep(2)
                    continue
                if state not in (ScreenState.CLAUDE_WORKING,
                                 ScreenState.CLAUDE_IDLE):
                    log.info("WATCH: Session ended (state: %s) — "
                             "resuming watch", state)
                    break
                # If idle, check if there's ANOTHER new handoff
                if state == ScreenState.CLAUDE_IDLE and _has_new_handoff():
                    log.info("WATCH: Session idle + new handoff — "
                             "will launch on next trigger")
                    break

    except KeyboardInterrupt:
        log.info("Watch mode interrupted")
    finally:
        observer.stop()
        observer.join()


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
    parser.add_argument("--force", action="store_true",
                        help="Launch even if a session appears active")
    parser.add_argument("--watch", action="store_true",
                        help="Event-driven: launch instantly on new handoff")
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

        if args.watch:
            run_watch(wmcp, registry)
        elif args.loop:
            run_loop(wmcp, args.interval, args.handoff)
        else:
            result = launch(wmcp, args.handoff, force=args.force)
            sys.exit(0 if result["success"] else 1)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        # S124: Release session lock on exit
        try:
            _session_lock.release()
            log.info("Session lock released (launcher exit)")
        except Exception:
            pass
        try:
            registry.disconnect_all()
        except Exception:
            pass


if __name__ == "__main__":
    main()
