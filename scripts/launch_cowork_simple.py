#!/usr/bin/env python3
"""
Simple Cowork Session Launcher -- poll, click, paste, approve.

No state machines. No watchdog. No event threading. No escalation paths.
Just a dumb loop that checks the screen every 60s and does the obvious thing.

Usage:
    python launch_cowork_simple.py              # Run once
    python launch_cowork_simple.py --loop       # Perpetual polling
    python launch_cowork_simple.py --dry-run    # Show screen state only

Kill switch: create rudy-data/coordination/robin-pause.flag
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---- Paths ----
REPO = Path(r"C:\Users\ccimi\rudy-workhorse")
VAULT_HANDOFFS = REPO / "vault" / "Handoffs"
COORD_DIR = REPO / "rudy-data" / "coordination"
KILL_SWITCH = COORD_DIR / "robin-pause.flag"
LOG_DIR = REPO / "rudy-data" / "logs"
LOG_FILE = LOG_DIR / "launch-simple.log"

# ---- Timing ----
POLL_INTERVAL = 60      # seconds between state checks
GOAD_AFTER_MIN = 40     # goad Alfred if idle this long after launch
MAX_SESSION_MIN = 90    # force new session after this long
STEP_PAUSE = 2.0        # seconds between UI actions

# ---- Logging ----
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("launcher")

# ---- Element regex (Windows-MCP Snapshot format) ----
EL_RE = re.compile(r"(\d+)\|([^|]*)\|([^|]*)\|([^|]*)\|\((\d+),\s*(\d+)\)")


def parse(text):
    """Parse Snapshot text into element dicts."""
    return [{"id": int(m[0]), "win": m[1].strip(), "ctrl": m[2].strip(),
             "name": m[3].strip(), "x": int(m[4]), "y": int(m[5])}
            for m in EL_RE.findall(text)]


def find(els, name, win=None, ctrl=None):
    """Find first element matching name substring (case-insensitive)."""
    n = name.lower()
    for e in els:
        if n and n not in e["name"].lower():
            continue
        if win and win.lower() not in e["win"].lower():
            continue
        if ctrl and ctrl.lower() != e["ctrl"].lower():
            continue
        return e
    return None

# ---- MCP Connection ----
_wmcp = None
_registry = None


def connect():
    """Connect to Windows-MCP. Returns tool-call function."""
    global _wmcp, _registry
    sys.path.insert(0, str(REPO / "rudy"))
    from robin_mcp_client import MCPServerRegistry
    _registry = MCPServerRegistry()
    if not _registry.connect("windows-mcp"):
        raise RuntimeError("Cannot connect to Windows-MCP")
    log.info("Windows-MCP connected")

    def call(tool, args=None):
        return _registry.call_tool(f"windows-mcp.{tool}", args or {})
    _wmcp = call
    return call


def reconnect():
    """Tear down and rebuild MCP connection."""
    global _wmcp, _registry
    try:
        _registry.disconnect_all()
    except Exception:
        pass
    time.sleep(3)
    return connect()


# ---- Core Actions ----
def snap(wmcp):
    """Take snapshot, return parsed elements. Empty list on failure."""
    try:
        r = wmcp("Snapshot", {"use_vision": False})
        if r.success:
            els = parse(r.content or "")
            wins = list(set(e["win"] for e in els))[:5]
            log.info("Snap: %d els, wins=%s", len(els), wins)
            return els
    except Exception as e:
        log.error("Snap failed: %s", e)
    return []


def dismiss_blocking_dialogs(wmcp):
    """Dismiss any blocking dialog boxes (System Error, Script Host, etc.).

    These dialogs steal focus and prevent the launcher from seeing Claude.
    ROOT CAUSE of 4-hour outage in S92: 'python.exe - System Error' dialog
    blocked all launch attempts from 02:48 to 06:42.
    """
    try:
        r = wmcp("Snapshot", {"use_vision": False})
        if not r.success:
            return False
        els = parse(r.content or "")
        blocker_keywords = ["system error", "script host", "not responding",
                            "has stopped working", "fatal error"]
        for el in els:
            win_lower = el["win"].lower()
            if not any(kw in win_lower for kw in blocker_keywords):
                continue
            # Found a blocker -- try OK/Close buttons first
            for btn_name in ["OK", "Close", "Dismiss", "Yes", "End Now"]:
                btn = find(els, btn_name, win=el["win"], ctrl="Button")
                if btn:
                    log.info("Dismissing '%s' via '%s' button", el["win"], btn_name)
                    wmcp("Click", {"loc": [btn["x"], btn["y"]]})
                    time.sleep(1)
                    return True
            # No button found -- focus and Alt+F4
            log.info("No dismiss button for '%s' -- trying Alt+F4", el["win"])
            wmcp("Click", {"loc": [el["x"], el["y"]]})
            time.sleep(0.5)
            shortcut(wmcp, "alt+F4")
            time.sleep(1)
            return True
    except Exception as e:
        log.error("dismiss_blocking_dialogs error: %s", e)
    return False


def click(wmcp, el, label=""):
    """Click an element."""
    log.info("Click '%s' (%d,%d) [%s]", el["name"], el["x"], el["y"], label)
    wmcp("Click", {"loc": [el["x"], el["y"]]})
    time.sleep(STEP_PAUSE)


def shortcut(wmcp, keys):
    """Send keyboard shortcut."""
    wmcp("Shortcut", {"shortcut": keys})
    time.sleep(0.5)


def _set_clipboard(text):
    """Set clipboard using ctypes -- ZERO subprocesses, ZERO visible windows."""
    import ctypes
    CF_UNICODETEXT = 13
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    user32.OpenClipboard(0)
    user32.EmptyClipboard()
    hMem = kernel32.GlobalAlloc(0x0042, (len(text) + 1) * 2)
    pMem = kernel32.GlobalLock(hMem)
    ctypes.cdll.msvcrt.wcscpy_s(pMem, len(text) + 1, text)
    kernel32.GlobalUnlock(hMem)
    user32.SetClipboardData(CF_UNICODETEXT, hMem)
    user32.CloseClipboard()


def paste_text(wmcp, el, text):
    """Paste text via clipboard (atomic, no keystroke drops, no visible windows)."""
    _set_clipboard(text)
    wmcp("Click", {"loc": [el["x"], el["y"]]})
    time.sleep(0.5)
    shortcut(wmcp, "ctrl+a")
    shortcut(wmcp, "ctrl+v")
    time.sleep(1.0)
    log.info("Pasted %d chars", len(text))


# ---- State Detection (simple) ----
def get_state(els):
    """Return one of: working, idle, ready, mount, cowork_select, gone."""
    cl = [e for e in els if "claude" in e["win"].lower()]
    if not cl:
        return "gone", {}

    # Mount prompt (Allow/Deny)?
    allow = find(cl, "Allow", ctrl="Button")
    deny = find(cl, "Deny", ctrl="Button")
    if allow and deny:
        return "mount", {"allow": allow}

    # Working? (Stop response, Thinking, Working on it, Generating)
    for ind in ["Stop response", "Thinking", "Working on it", "Generating"]:
        if find(cl, ind):
            return "working", {}

    # Active session indicators -- if ANY of these exist, session is live
    # even if no "Working on it" text is visible (between tool calls)
    has_context = find(cl, "Context")
    has_progress = find(cl, "Progress")
    has_todo = find(cl, "Todo")
    session_active = has_context or has_progress or has_todo

    # Ready to start new task? (Button, not sidebar Link)
    nt = find(cl, "New task", ctrl="Button")
    if nt and not session_active:
        return "ready", {"new_task": nt}

    # If session is active but not "working", it's between responses
    # -- treat as working (do NOT launch on top)
    if session_active:
        # Check if there's a prompt input = Alfred finished, awaiting input
        pi = (find(cl, "Reply") or find(cl, "Write your prompt")
              or find(cl, "", ctrl="Edit"))
        if pi:
            return "idle", {"prompt": pi}
        # No prompt input = still processing or user is reading
        return "working", {}

    # Cowork mode selection (ONLY on fresh task form, not active session)
    cw = find(cl, "Cowork", ctrl="Radio Button")
    if cw:
        return "cowork_select", {"cowork": cw}

    # Prompt input visible with no session context = fresh form
    pi = (find(cl, "Reply") or find(cl, "Write your prompt")
          or find(cl, "", ctrl="Edit"))
    if pi:
        return "idle", {"prompt": pi}

    return "unknown", {}


# ---- Handoff & Prompt ----
def latest_handoff():
    """Return path to most recent handoff file, or None."""
    if not VAULT_HANDOFFS.exists():
        return None
    hfs = sorted(VAULT_HANDOFFS.glob("Session-*-Handoff.md"),
                 key=lambda f: f.stat().st_mtime, reverse=True)
    return hfs[0] if hfs else None


def build_prompt(handoff=None):
    """Build the session prompt."""
    if not handoff:
        handoff = latest_handoff()
    if handoff:
        rel = Path(handoff).relative_to(REPO)
        return (
            f"C:\\Users\\ccimi\\rudy-workhorse ; "
            f"Good evening, Alfred. Read {rel} and follow "
            f"protocols, then proceed. IMPORTANT: Before you stop "
            f"responding, you MUST write a handoff to vault/Handoffs/. "
            f"If context is below 50 percent, keep working. "
            f"If context is above 70 percent, write the handoff "
            f"immediately. Robin will launch the next session."
        )
    return (
        r"C:\Users\ccimi\rudy-workhorse ; "
        "Good evening, Alfred. Read CLAUDE.md and follow protocols, "
        "then proceed. Write a handoff to vault/Handoffs/ before stopping."
    )


GOAD_MSG = (
    "IMPORTANT: Please write your handoff to vault/Handoffs/ now and "
    "end the session. Robin will launch the next session. If you have "
    "already written one, say DONE."
)


# ---- Launch Sequence ----
def launch_session(wmcp, handoff=None):
    """Click New Task -> Cowork -> Paste prompt -> Start task -> Approve.
    Returns True on success."""
    prompt = build_prompt(handoff)
    log.info("=== LAUNCH START ===")
    dismiss_blocking_dialogs(wmcp)
    time.sleep(2)

    for attempt in range(3):
        if attempt > 0:
            log.info("Retry %d/3", attempt + 1)
            time.sleep(5)

        els = snap(wmcp)
        if not els:
            continue
        state, det = get_state(els)
        log.info("State: %s", state)

        # Step 1: Get to "New task" screen. Click sidebar link if needed.
        if state in ("working", "idle", "cowork_select", "unknown"):
            nt_link = find(els, "New task", win="Claude")
            if nt_link:
                click(wmcp, nt_link, "New task (sidebar)")
                time.sleep(2)
                els = snap(wmcp)
                if not els:
                    continue
                state, det = get_state(els)

        # Step 2: If we see "New task" button, click it
        if state == "ready":
            click(wmcp, det["new_task"], "New task")
            time.sleep(2)
            els = snap(wmcp)
            if not els:
                continue
            state, det = get_state(els)

        # Step 3: Select Cowork mode
        if state == "cowork_select":
            cw = det.get("cowork") or find(els, "Cowork", ctrl="Radio Button")
            if cw:
                click(wmcp, cw, "Cowork radio")
                time.sleep(2)
                els = snap(wmcp)
                if not els:
                    continue
                state, det = get_state(els)

        # Step 4: Find prompt input and paste
        pi = (find(els, "Write your prompt", win="Claude")
              or find(els, "", win="Claude", ctrl="Edit"))
        if not pi:
            log.error("No prompt input found (state=%s)", state)
            continue
        paste_text(wmcp, pi, prompt)

        # Step 5: Click Start task / Send, or press Enter
        els = snap(wmcp)
        send = (find(els, "Start task", win="Claude", ctrl="Button")
                or find(els, "Start task", win="Claude")
                or find(els, "Send", win="Claude", ctrl="Button"))
        if send:
            click(wmcp, send, "Start task")
        else:
            log.info("No send button, pressing Enter")
            shortcut(wmcp, "enter")
        time.sleep(3)

        # Step 6: Approve mount prompts (poll for 30s)
        for _ in range(6):
            els = snap(wmcp)
            if not els:
                time.sleep(5)
                continue
            st, dt = get_state(els)
            if st == "mount":
                click(wmcp, dt["allow"], "Allow mount")
                time.sleep(3)
                continue
            if st == "working":
                log.info("=== LAUNCH SUCCESS ===")
                return True
            time.sleep(5)

        # If we got here without "working", check one more time
        els = snap(wmcp)
        if els:
            st, _ = get_state(els)
            if st != "ready":  # not back at start = probably working
                log.info("=== LAUNCH PROBABLE SUCCESS (state=%s) ===", st)
                return True

    log.error("=== LAUNCH FAILED after 3 attempts ===")
    return False


# ---- Goad: type message into idle session ----
def goad_handoff(wmcp):
    """Type goad message into an idle session's prompt input."""
    els = snap(wmcp)
    if not els:
        return False
    state, det = get_state(els)
    if state != "idle":
        log.info("Goad: state=%s, not idle -- skipping", state)
        return False
    pi = det.get("prompt")
    if not pi:
        return False
    log.info("=== GOADING HANDOFF ===")
    paste_text(wmcp, pi, GOAD_MSG)
    shortcut(wmcp, "enter")
    return True


# ---- Main Loop ----
def run_loop(wmcp):
    """Simple polling loop. Check state every 60s, act accordingly."""
    launch_time = None
    goaded = False
    boot_time = time.time()  # Don't launch within 5 min of starting

    while True:
        if KILL_SWITCH.exists():
            log.info("Kill switch active -- stopping")
            return

        els = snap(wmcp)
        if not els:
            log.warning("Empty snapshot -- MCP may be dead, reconnecting")
            try:
                wmcp = reconnect()
            except Exception as e:
                log.error("Reconnect failed: %s -- waiting 60s", e)
            time.sleep(POLL_INTERVAL)
            continue

        state, det = get_state(els)
        now = time.time()
        age_min = (now - launch_time) / 60 if launch_time else 0
        log.info("Poll: state=%s, age=%.0fm, goaded=%s", state, age_min, goaded)

        # 1. Working = session active, do nothing
        if state == "working":
            if not launch_time:
                launch_time = now  # track session we didn't start
            time.sleep(POLL_INTERVAL)
            continue

        # 2. Mount prompt = approve immediately
        if state == "mount":
            click(wmcp, det["allow"], "Allow mount")
            time.sleep(5)
            continue

        # 3. Idle = Alfred stopped responding
        if state == "idle":
            # If session is young (<GOAD_AFTER_MIN), just wait
            if launch_time and age_min < GOAD_AFTER_MIN:
                log.info("Session young (%.0fm) -- waiting", age_min)
                time.sleep(POLL_INTERVAL)
                continue
            # Goad once, then force new session
            if not goaded:
                if goad_handoff(wmcp):
                    goaded = True
                    log.info("Goaded -- waiting 5 min for handoff")
                    time.sleep(300)
                    continue
            # Already goaded or goad failed -- launch new session
            log.info("Post-goad or stale idle -- launching new session")
            if launch_session(wmcp):
                launch_time = time.time()
                goaded = False
            time.sleep(POLL_INTERVAL)
            continue

        # 3.5. Dismiss blocking dialogs (System Error, Script Host, etc.)
        # ROOT CAUSE of S92 4-hour outage: these steal focus from Claude
        if dismiss_blocking_dialogs(wmcp):
            log.info("Dismissed blocking dialog -- re-polling in 3s")
            time.sleep(3)
            continue

        # 4. Ready / gone / cowork_select / unknown = launch new session
        # Safety: don't launch within 5 min of boot (avoid false positives)
        if state in ("ready", "gone", "cowork_select", "unknown") and \
                (time.time() - boot_time) < 300:
            log.info("Boot cooldown (%.0fs) -- skipping launch",
                     time.time() - boot_time)
            time.sleep(POLL_INTERVAL)
            continue
        if state in ("ready", "gone", "cowork_select", "unknown"):
            log.info("No active session -- launching")
            if state == "gone":
                # Try clicking Claude on taskbar first
                tb = find(els, "Claude", win="Taskbar")
                if tb:
                    click(wmcp, tb, "Taskbar Claude")
                    time.sleep(3)
            if launch_session(wmcp):
                launch_time = time.time()
                goaded = False
            else:
                log.error("Launch failed -- waiting 2 min")
                time.sleep(120)
            continue

        # 5. Anything else, just wait
        time.sleep(POLL_INTERVAL)


# ---- Single Launch ----
def run_once(wmcp, handoff=None):
    """Launch one session and exit."""
    ok = launch_session(wmcp, handoff)
    sys.exit(0 if ok else 1)


# ---- Entry Point ----
def main():
    parser = argparse.ArgumentParser(description="Simple Cowork Launcher")
    parser.add_argument("--loop", action="store_true", help="Perpetual polling mode")
    parser.add_argument("--handoff", help="Specific handoff file path")
    parser.add_argument("--dry-run", action="store_true", help="Show state only")
    parser.add_argument("--kill", action="store_true", help="Create kill switch")
    parser.add_argument("--resume", action="store_true", help="Remove kill switch")
    args = parser.parse_args()

    if args.kill:
        COORD_DIR.mkdir(parents=True, exist_ok=True)
        KILL_SWITCH.write_text(f"Killed at {datetime.now()}\n")
        print("Kill switch created")
        return
    if args.resume:
        if KILL_SWITCH.exists():
            KILL_SWITCH.unlink()
        print("Kill switch removed")
        return

    wmcp = connect()

    if args.dry_run:
        els = snap(wmcp)
        state, det = get_state(els)
        print(f"State: {state}")
        print(f"Detail: {json.dumps({k: str(v)[:60] for k, v in det.items()})}")
        return

    if args.loop:
        run_loop(wmcp)
    else:
        run_once(wmcp, args.handoff)


if __name__ == "__main__":
    main()
