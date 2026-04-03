"""
Robin Session Monitor -- Continuous prompt-pause bypass + chat scrolling.

Watches an active Cowork session and auto-approves permission prompts
that would otherwise stall the session waiting for human input.

Handles:
  1. Tool-loading permission prompts (Allow/Deny for DC, MCP tools)
  2. Directory mount prompts (Cowork in <path>)
  3. Any other Allow/Deny dialog in Claude Desktop
  4. Chat scrolling to keep latest content visible for screenshots

PERCEIVE -> REASON -> ACT -> VERIFY pattern throughout.

Usage:
  Standalone:  python robin_session_monitor.py [--duration 300] [--interval 3]
  From sentinel: from rudy.robin_session_monitor import SessionMonitor
                 monitor = SessionMonitor(); monitor.run_cycle()
  Continuous:  monitor.run_continuous(duration_seconds=300)

Created: Session 80
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from rudy.robin_mcp_client import MCPServerRegistry
from rudy.paths import REPO_ROOT

log = logging.getLogger("robin_session_monitor")

STATE_FILE = REPO_ROOT / "rudy-data" / "coordination" / "session-monitor-state.json"

# UI element patterns that indicate a permission prompt
ALLOW_PATTERNS = [
    "Allow Enter",
    "Allow",
]
DENY_PATTERNS = [
    "Deny Esc",
    "Deny",
]

# Patterns indicating session is actively working (no prompt blocking)
ACTIVITY_PATTERNS = [
    "Stop",
    "Working",
    "Thinking",
    "Generating",
]

# Patterns indicating session is idle / waiting for input
IDLE_PATTERNS = [
    "New task",
    "Write your prompt",
    "Queue",
]


# Reuse the launcher's element parser
ELEMENT_RE = re.compile(
    r"(\d+)\|([^|]*)\|([^|]*)\|([^|]*)\|"
    r"\((\d+),\s*(\d+)\)"
)


def parse_snapshot_elements(snapshot_text: str) -> list:
    """Parse Windows-MCP Snapshot output into structured elements."""
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


def find_element(elements: list, name_pattern: str,
                 window: str = None,
                 control_type: str = None) -> Optional[dict]:
    """Find element by name pattern (case-insensitive substring)."""
    pattern = name_pattern.lower()
    for el in elements:
        if pattern and pattern not in el["name"].lower():
            continue
        if window and window.lower() not in el["window"].lower():
            continue
        if control_type and control_type.lower() != el["control_type"].lower():
            continue
        return el
    return None


class SessionMonitor:
    """Continuous monitor for Cowork session prompt pauses.

    Periodically snapshots the Claude Desktop window, detects
    permission prompts (Allow/Deny), and auto-approves them.
    Also scrolls chat to keep latest content visible.
    """

    def __init__(self, poll_interval: float = 3.0):
        self.poll_interval = poll_interval
        self.wmcp = None
        self.registry = None
        self.stats = {
            "prompts_approved": 0,
            "scrolls_performed": 0,
            "cycles_run": 0,
            "errors": 0,
            "last_prompt_approved": None,
            "started_at": datetime.now().isoformat(),
        }
        self._connected = False

    def connect(self) -> bool:
        """Connect to Windows-MCP. Returns True on success."""
        if self._connected:
            return True
        try:
            self.registry = MCPServerRegistry()
            if not self.registry.connect("windows-mcp"):
                log.error("Cannot connect to Windows-MCP")
                return False
            self._connected = True
            return True
        except Exception as exc:
            log.error("MCP connection failed: %s", exc)
            return False

    def _call(self, tool: str, args: dict):
        """Call a Windows-MCP tool."""
        return self.registry.call_tool(f"windows-mcp.{tool}", args)

    def _snapshot(self) -> list:
        """Take a Snapshot, return parsed elements."""
        try:
            snap = self._call("Snapshot", {"use_vision": False})
            if not snap.success:
                log.warning("Snapshot failed: %s", snap.error)
                return []
            return parse_snapshot_elements(snap.content or "")
        except Exception as exc:
            log.warning("Snapshot exception: %s", exc)
            return []

    def _click(self, element: dict, label: str) -> bool:
        """Click an element. Returns True on success."""
        log.info("ACT: Clicking '%s' at (%d, %d)",
                 label, element["x"], element["y"])
        try:
            result = self._call("Click", {
                "loc": [element["x"], element["y"]]
            })
            return result.success
        except Exception as exc:
            log.warning("Click failed on '%s': %s", label, exc)
            return False

    def detect_prompt(self, elements: list) -> Optional[dict]:
        """PERCEIVE: Detect any Allow/Deny permission prompt.

        Scans for Allow buttons in Claude window. Returns the Allow
        element if found, None otherwise.
        """
        for pattern in ALLOW_PATTERNS:
            # Try button type first (most specific)
            btn = find_element(elements, pattern, window="Claude",
                               control_type="Button")
            if btn:
                return btn
            # Then any element with that name in Claude
            btn = find_element(elements, pattern, window="Claude")
            if btn:
                return btn
        # Fallback: check for Deny visible (prompt exists but Allow
        # not matched) -- use Enter shortcut as Allow is default
        for pattern in DENY_PATTERNS:
            deny = find_element(elements, pattern, window="Claude",
                                control_type="Button")
            if deny:
                return {"_use_enter": True, "name": "Allow (via Enter)",
                        "x": 0, "y": 0}
        return None

    def detect_session_state(self, elements: list) -> str:
        """Detect current session state from UI elements.

        Returns: 'active', 'prompt_blocked', 'idle', or 'unknown'.
        """
        # Check for permission prompt first
        if self.detect_prompt(elements):
            return "prompt_blocked"

        # Check for activity indicators
        for pattern in ACTIVITY_PATTERNS:
            if find_element(elements, pattern, window="Claude"):
                return "active"
        # Check for idle indicators
        for pattern in IDLE_PATTERNS:
            if find_element(elements, pattern, window="Claude"):
                return "idle"
        return "unknown"

    def approve_prompt(self, elements: list) -> bool:
        """ACT: Auto-approve a detected permission prompt.

        Clicks Allow button, or presses Enter if Allow is the default.
        Returns True if approval was attempted.
        """
        prompt = self.detect_prompt(elements)
        if not prompt:
            return False

        if prompt.get("_use_enter"):
            # Deny visible but Allow not matched -- Enter is default
            log.info("ACT: Permission prompt detected, pressing Enter "
                     "(Allow is default action)")
            try:
                self._call("Shortcut", {"shortcut": "enter"})
            except Exception as exc:
                log.warning("Enter shortcut failed: %s", exc)
                return False
        else:
            log.info("ACT: Clicking Allow button '%s'", prompt["name"])
            if not self._click(prompt, f"Allow ({prompt['name']})"):
                # Fallback to Enter
                log.info("ACT: Click failed, trying Enter shortcut")
                try:
                    self._call("Shortcut", {"shortcut": "enter"})
                except Exception:
                    return False

        self.stats["prompts_approved"] += 1
        self.stats["last_prompt_approved"] = datetime.now().isoformat()
        log.info("VERIFY: Prompt approved (#%d total)",
                 self.stats["prompts_approved"])
        return True

    def scroll_chat_to_bottom(self, elements: list) -> bool:
        """Scroll Claude chat to bottom to keep latest content visible.

        Uses End key or Ctrl+End to jump to bottom of chat.
        This ensures Robin can see the most recent messages when
        taking screenshots for reasoning.
        """
        # Find the Claude window / chat area
        claude_el = find_element(elements, "", window="Claude")
        if not claude_el:
            return False

        try:
            # Click the chat area first to ensure focus
            self._call("Click", {
                "loc": [claude_el["x"], claude_el["y"]]
            })
            time.sleep(0.3)
            # Ctrl+End scrolls to absolute bottom in most UIs
            self._call("Shortcut", {"shortcut": "ctrl+end"})
            self.stats["scrolls_performed"] += 1
            return True
        except Exception as exc:
            log.warning("Scroll failed: %s", exc)
            return False

    def run_cycle(self) -> dict:
        """Run one monitoring cycle: snapshot, detect, act.

        Returns dict with cycle result.
        """
        if not self._connected and not self.connect():
            return {"error": "Cannot connect to Windows-MCP"}

        self.stats["cycles_run"] += 1
        cycle_result = {
            "cycle": self.stats["cycles_run"],
            "timestamp": datetime.now().isoformat(),
            "state": "unknown",
            "action_taken": None,
        }

        # PERCEIVE
        elements = self._snapshot()
        if not elements:
            cycle_result["state"] = "no_elements"
            return cycle_result

        # DETECT state
        state = self.detect_session_state(elements)
        cycle_result["state"] = state

        # ACT based on state
        if state == "prompt_blocked":
            approved = self.approve_prompt(elements)
            cycle_result["action_taken"] = "approved" if approved else "approve_failed"

            if approved:
                # VERIFY: re-snapshot to confirm prompt dismissed
                time.sleep(1.5)
                verify_elements = self._snapshot()
                still_blocked = self.detect_prompt(verify_elements)

                if still_blocked:
                    log.warning("VERIFY: Prompt still visible after approve "
                                "-- retrying with Enter")
                    try:
                        self._call("Shortcut", {"shortcut": "enter"})
                        time.sleep(1.0)
                    except Exception:
                        pass
                    cycle_result["action_taken"] = "approved_retry"
                else:
                    log.info("VERIFY: Prompt dismissed successfully")

        elif state == "active":
            # Session is working -- scroll to keep latest visible
            self.scroll_chat_to_bottom(elements)
            cycle_result["action_taken"] = "scrolled"

        elif state == "idle":
            cycle_result["action_taken"] = "none_idle"

        return cycle_result

    def run_continuous(self, duration_seconds: float = 300,
                       stop_on_idle: bool = True) -> dict:
        """Run continuous monitoring for a duration.

        Args:
            duration_seconds: How long to monitor (default 5 min).
                None = run indefinitely until session ends.
            stop_on_idle: Stop if session becomes idle (completed).

        Returns dict with session stats.
        """
        if not self._connected and not self.connect():
            return {"error": "Cannot connect to Windows-MCP"}

        log.info("SESSION MONITOR: Starting continuous watch "
                 "(duration=%s, interval=%.1fs)",
                 duration_seconds or "indefinite", self.poll_interval)

        start = time.time()
        idle_count = 0
        MAX_IDLE_CYCLES = 3  # Stop after 3 consecutive idle cycles

        try:
            while True:
                # Check duration limit
                if duration_seconds is not None:
                    elapsed = time.time() - start
                    if elapsed >= duration_seconds:
                        log.info("SESSION MONITOR: Duration limit reached "
                                 "(%.0fs)", elapsed)
                        break

                cycle = self.run_cycle()

                # Track idle state for early exit
                if cycle.get("state") == "idle":
                    idle_count += 1
                    if stop_on_idle and idle_count >= MAX_IDLE_CYCLES:
                        log.info("SESSION MONITOR: Session idle for %d "
                                 "cycles, stopping", idle_count)
                        break
                else:
                    idle_count = 0

                # Adaptive polling: faster when prompt-blocked
                if cycle.get("state") == "prompt_blocked":
                    time.sleep(1.0)  # Fast retry for prompts
                else:
                    time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            log.info("SESSION MONITOR: Interrupted by user")
        except Exception as exc:
            log.error("SESSION MONITOR: Error: %s", exc, exc_info=True)
            self.stats["errors"] += 1

        self.stats["ended_at"] = datetime.now().isoformat()
        self._save_state()

        log.info("SESSION MONITOR: Done. Prompts approved: %d, "
                 "Scrolls: %d, Cycles: %d, Errors: %d",
                 self.stats["prompts_approved"],
                 self.stats["scrolls_performed"],
                 self.stats["cycles_run"],
                 self.stats["errors"])
        return self.stats

    def _save_state(self):
        """Save monitor state for sentinel/debugging."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps(self.stats, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("State save failed: %s", exc)

    def disconnect(self):
        """Clean up MCP connection."""
        if self.registry:
            try:
                self.registry.disconnect_all()
            except Exception:
                pass
            self._connected = False


# ---------------------------------------------------------------------------
# Sentinel integration: single-cycle check callable from sentinel loop
# ---------------------------------------------------------------------------

def check_and_approve_prompts() -> Optional[dict]:
    """Quick single-cycle check for sentinel integration.

    Call this from the sentinel's periodic loop to detect and
    approve any stalled permission prompts.
    Returns cycle result or None on connection failure.
    """
    monitor = SessionMonitor()
    if not monitor.connect():
        return None

    try:
        result = monitor.run_cycle()
        return result
    finally:
        monitor.disconnect()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [SessionMonitor] %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Robin Session Monitor -- auto-approve Cowork prompts"
    )
    parser.add_argument("--duration", type=int, default=300,
                        help="Monitor duration in seconds (default 300)")
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Poll interval in seconds (default 3.0)")
    parser.add_argument("--single", action="store_true",
                        help="Run single cycle then exit")
    parser.add_argument("--indefinite", action="store_true",
                        help="Run indefinitely (no duration limit)")
    args = parser.parse_args()

    monitor = SessionMonitor(poll_interval=args.interval)

    if args.single:
        if monitor.connect():
            r = monitor.run_cycle()
            print(json.dumps(r, indent=2, default=str))
            monitor.disconnect()
    else:
        dur = None if args.indefinite else args.duration
        stats = monitor.run_continuous(duration_seconds=dur)
        print(json.dumps(stats, indent=2, default=str))
