#!/usr/bin/env python3
"""
Robin Perpetual Work Loop -- Session continuity without human intervention.

When Robin's sentinel detects inactivity AND no fresh handoff exists,
this module closes the gap:

  1. PERCEIVE: Navigate to Claude Desktop, read current thread context
  2. REASON:   Feed context to Ollama for structured handoff summary
  3. ACT:      Prompt Alfred for handoff in current thread, then launch new
  4. VERIFY:   Confirm the new session started

Composes existing modules:
  - robin_cowork_launcher (Launcher v5: Snapshot, find_element, Ollama)
  - local_ai / RobinBrain (Ollama reasoning for context summarization)
  - robin_mcp_client (Windows-MCP: Snapshot, Click, Type, Scrape)

Zero new dependencies. Intelligence Mandate: PERCEIVE -> REASON -> ACT -> VERIFY.

Session 70 -- Alfred S70 + Batman directive.
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from rudy.paths import REPO_ROOT, VAULT_HANDOFFS
from rudy.robin_cowork_launcher import (
    COORD_DIR,
    STATE_FILE,
    STEP_PAUSE,
    _get_brain,
    _snapshot,
    _click_element,
    find_element,
    launch_cowork_session,
    _find_latest_handoff,
)

log = logging.getLogger("robin_perpetual_loop")

# How long (seconds) to wait for Alfred to produce a handoff after prompting
HANDOFF_WAIT_TIMEOUT = 180
HANDOFF_POLL_INTERVAL = 15

# Minimum age (seconds) of a handoff to consider it "fresh" (not stale)
FRESH_HANDOFF_MAX_AGE = 600  # 10 minutes


def _has_fresh_handoff() -> Optional[Path]:
    """Check if a handoff exists that hasn't been launched yet.

    Returns the handoff Path if fresh, None otherwise.
    This mirrors check_and_launch_if_needed() logic.
    """
    last_used = None
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            last_used = state.get("last_launch", {}).get("handoff_used")
        except Exception:
            pass

    latest = _find_latest_handoff()
    if latest and str(latest) != last_used:
        return latest
    return None


def _handoff_is_recent(path, max_age_seconds=FRESH_HANDOFF_MAX_AGE):
    """Check if a handoff file was modified recently."""
    try:
        age = time.time() - path.stat().st_mtime
        return age < max_age_seconds
    except Exception:
        return False


def _read_screen_context(wmcp, brain, elements):
    """PERCEIVE: Read visible text from Claude Desktop for context.

    Uses Scrape tool from Windows-MCP to capture text content,
    then feeds it to Ollama for summarization.

    Falls back to element names if Scrape is unavailable.
    """
    # Try Scrape for rich text content
    try:
        scrape_result = wmcp("Scrape", {"app_title": "Claude"})
        if hasattr(scrape_result, 'success') and scrape_result.success:
            content = getattr(scrape_result, 'content', '') or ''
            if len(content) > 100:
                log.info("PERCEIVE: Scraped %d chars from Claude Desktop",
                         len(content))
                return content[:4000]  # Cap to avoid token overflow
    except Exception as exc:
        log.debug("Scrape unavailable: %s", exc)

    # Fallback: construct context from visible element names
    claude_elements = [
        e for e in elements
        if "claude" in e.get("window", "").lower()
    ]
    if claude_elements:
        summary = "\n".join(
            f"[{e['control_type']}] {e['name']}"
            for e in claude_elements[:30]
            if e.get("name", "").strip()
        )
        log.info("PERCEIVE: Extracted %d element names as context",
                 len(claude_elements))
        return summary

    return ""


def _reason_about_session(brain, screen_context):
    """REASON: Ask Ollama to summarize the current session state.

    Returns a dict with: session_number, completed, priorities, robin_status.
    Falls back to a generic summary if Ollama is offline.
    """
    fallback = {
        "session_number": "unknown",
        "summary": "Could not analyze session context",
        "completed": [],
        "priorities": ["Continue from last handoff"],
        "robin_status": "unknown",
    }
    if brain is None:
        fallback["summary"] = "Ollama offline -- generic handoff"
        return fallback

    prompt = (
        "You are Robin, analyzing a Claude Desktop session for handoff.\n\n"
        "VISIBLE CONTEXT:\n"
        f"{screen_context[:3000]}\n\n"
        "Produce a JSON summary with these keys:\n"
        '  "session_number": best guess at current session number\n'
        '  "summary": one-sentence session state description\n'
        '  "completed": list of completed items\n'
        '  "priorities": list of remaining priorities\n'
        '  "robin_status": Robin health if visible\n'
        "\nReply with ONLY the JSON object."
    )

    try:
        response = brain.ask(prompt, role="general", max_tokens=512)
        if response:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
    except Exception as exc:
        log.warning("REASON: Ollama session analysis failed: %s", exc)

    return fallback


def _build_handoff_prompt(session_info):
    """Build the prompt Robin types into current thread to request a handoff."""
    session_num = session_info.get("session_number", "N")
    return (
        f"Draft a handoff for Session {session_num}+1. Include: "
        "completed items, remaining priorities, Robin status, "
        "and IMPORTANT instruction to read CLAUDE.md first. "
        f"Write to vault/Handoffs/Session-{{next}}-Handoff.md"
    )


def _wait_for_new_handoff(before_path, timeout=HANDOFF_WAIT_TIMEOUT):
    """Wait for a new handoff file to appear in vault/Handoffs/.

    Returns the new handoff path, or None if timeout.
    """
    start = time.time()
    before_name = before_path.name if before_path else ""

    while time.time() - start < timeout:
        latest = _find_latest_handoff()
        if latest:
            if latest.name != before_name:
                log.info("ACT: New handoff detected: %s", latest.name)
                return latest
            if _handoff_is_recent(latest, max_age_seconds=timeout):
                log.info("ACT: Handoff updated: %s", latest.name)
                return latest
        time.sleep(HANDOFF_POLL_INTERVAL)

    log.warning("ACT: Timed out waiting for handoff (%ds)", timeout)
    return None


def perpetual_loop_handoff(dry_run=False):
    """Execute the perpetual work loop protocol.

    Called by sentinel when inactivity detected AND no fresh handoff exists.
    Robin generates a handoff by prompting Alfred, then launches new session.

    Returns a result dict with success status and reasoning log.
    """
    result = {
        "success": False,
        "timestamp": datetime.now().isoformat(),
        "phase": "init",
        "ollama_available": False,
        "reasoning_log": [],
        "error": None,
    }

    log.info("=== PERPETUAL WORK LOOP ACTIVATED ===")

    # --- FAST PATH: If a fresh handoff already exists, just launch ---
    fresh = _has_fresh_handoff()
    if fresh:
        log.info("FAST PATH: Fresh handoff exists: %s", fresh.name)
        result["phase"] = "fast_path"
        if dry_run:
            result["success"] = True
            result["reasoning_log"].append(
                {"step": "fast_path", "handoff": str(fresh)})
            return result
        launch_result = launch_cowork_session(handoff_path=fresh)
        result["success"] = launch_result.get("success", False)
        result["launch_result"] = launch_result
        return result

    # --- Initialize Robin's brain + hands ---
    brain = _get_brain()
    result["ollama_available"] = brain is not None
    if brain:
        log.info("BRAIN: Ollama online -- full reasoning enabled")
    else:
        log.warning("BRAIN: Ollama offline -- heuristic fallback")

    if dry_run:
        log.info("[DRY RUN] Would navigate to Claude Desktop "
                 "and prompt for handoff")
        result["success"] = True
        result["phase"] = "dry_run"
        return result

    try:
        from rudy.robin_mcp_client import MCPServerRegistry
        registry = MCPServerRegistry()
        if not registry.connect("windows-mcp"):
            result["error"] = "Cannot connect to Windows-MCP"
            return result

        def wmcp(tool, args):
            return registry.call_tool(f"windows-mcp.{tool}", args)

        # === STEP 1: PERCEIVE - Find Claude Desktop ===
        result["phase"] = "perceive_claude"
        log.info("PERCEIVE: Taking initial Snapshot...")
        elements = _snapshot(wmcp)
        if not elements:
            result["error"] = "Snapshot returned no elements"
            return result

        # Find Claude Desktop window
        claude_window = find_element(elements, "", window="Claude")
        if not claude_window:
            taskbar = find_element(
                elements, "Claude", window="Taskbar")
            if taskbar:
                _click_element(wmcp, taskbar, "Claude taskbar")
                time.sleep(STEP_PAUSE)
                elements = _snapshot(wmcp)
                claude_window = find_element(
                    elements, "", window="Claude")

        if not claude_window:
            result["error"] = "Claude Desktop not found (not open?)"
            log.error("PERCEIVE: Claude Desktop not visible")
            # FALLBACK: Launch with no-handoff prompt
            log.info("FALLBACK: Launching with generic prompt")
            launch_result = launch_cowork_session()
            result["success"] = launch_result.get("success", False)
            result["phase"] = "fallback_no_claude"
            result["launch_result"] = launch_result
            return result

        # === STEP 2: PERCEIVE - Read current thread context ===
        result["phase"] = "perceive_context"
        log.info("PERCEIVE: Reading screen context...")
        screen_context = _read_screen_context(
            wmcp, brain, elements)
        result["reasoning_log"].append({
            "step": "screen_context",
            "chars": len(screen_context),
        })

        # === STEP 3: REASON - Analyze session state ===
        result["phase"] = "reason"
        log.info("REASON: Analyzing session state with Ollama...")
        session_info = _reason_about_session(brain, screen_context)
        result["reasoning_log"].append({
            "step": "session_analysis",
            "info": session_info,
        })
        log.info("REASON: Session %s -- %s",
                 session_info.get("session_number", "?"),
                 session_info.get("summary", "no summary"))

        # === STEP 4: ACT - Type handoff request in current thread ===
        result["phase"] = "act_prompt_handoff"
        pre_handoff = _find_latest_handoff()

        prompt_input = find_element(
            elements, "Write your prompt", window="Claude")
        if not prompt_input:
            prompt_input = find_element(
                elements, "", window="Claude", control_type="Edit")
        if not prompt_input and brain:
            from rudy.robin_cowork_launcher import reason_about_ui
            decision = reason_about_ui(
                brain, elements,
                "Find the text input field in Claude Desktop")
            eid = decision.get("element_id")
            if eid is not None:
                prompt_input = next(
                    (e for e in elements if e["id"] == eid), None)

        if not prompt_input:
            result["error"] = "Cannot find prompt input"
            log.info("FALLBACK: No input -- launching generic session")
            launch_result = launch_cowork_session()
            result["success"] = launch_result.get("success", False)
            result["phase"] = "fallback_no_input"
            result["launch_result"] = launch_result
            return result

        # Type the handoff request
        handoff_prompt = _build_handoff_prompt(session_info)
        log.info("ACT: Typing handoff request at (%d, %d)",
                 prompt_input["x"], prompt_input["y"])
        wmcp("Type", {
            "loc": [prompt_input["x"], prompt_input["y"]],
            "text": handoff_prompt,
            "clear": True,
        })
        time.sleep(0.5)

        # Find and click Send
        elements = _snapshot(wmcp)
        send_btn = (
            find_element(elements, "Send", window="Claude",
                         control_type="Button")
            or find_element(elements, "Submit", window="Claude",
                            control_type="Button")
            or find_element(elements, "Send", window="Claude")
        )
        if send_btn:
            _click_element(wmcp, send_btn, "Send button")
        else:
            wmcp("Shortcut", {"shortcut": "enter"})
        time.sleep(STEP_PAUSE)

        # === STEP 5: WAIT - Monitor for new handoff file ===
        result["phase"] = "wait_handoff"
        log.info("WAIT: Monitoring vault/Handoffs/ for new handoff...")
        new_handoff = _wait_for_new_handoff(pre_handoff)

        if new_handoff:
            log.info("ACT: Handoff received: %s", new_handoff.name)
        else:
            log.warning("TIMEOUT: No handoff produced. "
                        "Launching with generic prompt.")

        # === STEP 6: ACT - Launch new session with handoff ===
        result["phase"] = "act_launch"
        launch_result = launch_cowork_session(
            handoff_path=new_handoff  # None = NO_HANDOFF_PROMPT
        )
        result["success"] = launch_result.get("success", False)
        result["launch_result"] = launch_result
        log.info("LAUNCH: success=%s", result["success"])

        # === STEP 7: VERIFY ===
        result["phase"] = "verify"
        if result["success"]:
            log.info("VERIFY: Perpetual loop completed successfully")
        else:
            log.warning("VERIFY: Launch reported failure: %s",
                        launch_result.get("error"))

        registry.disconnect_all()

    except Exception as exc:
        result["error"] = str(exc)
        log.error("Perpetual loop failed: %s", exc, exc_info=True)

    # Save state
    try:
        state_file = COORD_DIR / "perpetual-loop-state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(result, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("State save failed: %s", exc)

    return result


def _last_launch_age_minutes() -> float:
    """How many minutes since the last successful Cowork launch.

    Returns float("inf") if no launch recorded or state unreadable.
    """
    try:
        if not STATE_FILE.exists():
            return float("inf")
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        ts = state.get("last_launch", {}).get("timestamp")
        if not ts:
            return float("inf")
        last_dt = datetime.fromisoformat(ts)
        delta = datetime.now() - last_dt
        return delta.total_seconds() / 60.0
    except Exception:
        return float("inf")


def _is_cowork_session_active(wmcp_factory=None) -> bool:
    """Detect if a Cowork session is currently active in Claude Desktop.

    PERCEIVE: Takes a Snapshot and checks for session indicators.
    A session is active if we see activity indicators (Stop, Working,
    Thinking, etc.) or if we do NOT see the "New task" button (meaning
    we're inside a session, not on the start screen).

    Returns True if a session appears active, False otherwise.
    If Windows-MCP is unavailable, returns False (conservative).
    """
    if wmcp_factory is None:
        try:
            from rudy.robin_mcp_client import MCPServerRegistry
            registry = MCPServerRegistry()
            if not registry.connect("windows-mcp"):
                return False

            def wmcp(tool, args):
                return registry.call_tool(f"windows-mcp.{tool}", args)
            result = _is_cowork_session_active_inner(wmcp)
            registry.disconnect_all()
            return result
        except Exception as exc:
            log.debug("Session active check failed: %s", exc)
            return False
    return _is_cowork_session_active_inner(wmcp_factory)


def _is_cowork_session_active_inner(wmcp) -> bool:
    """Inner implementation for session detection.

    S77 principle: FALSE NEGATIVES ARE SAFE, FALSE POSITIVES ARE FATAL.
    A false negative (session active but we think it ended) = we launch
    a new tab = harmless. A false positive (session ended but we think
    it's active) = we NEVER launch again = system death.
    """
    elements = _snapshot(wmcp)
    if not elements:
        log.info("Session check: Snapshot empty -- treating as NOT active")
        return False

    # Check Claude window exists at all
    claude_elements = [e for e in elements
                       if "claude" in e.get("window", "").lower()]
    if not claude_elements:
        log.info("Session check: No Claude window found -- NOT active")
        return False

    # POSITIVE: Active indicators = session is doing something
    activity = (
        find_element(elements, "Stop", window="Claude")
        or find_element(elements, "Working", window="Claude")
        or find_element(elements, "Thinking", window="Claude")
        or find_element(elements, "Generating", window="Claude")
        or find_element(elements, "Progress", window="Claude")
    )
    if activity:
        log.info("Session ACTIVE: found '%s'", activity.get("name", "?"))
        return True

    # NEGATIVE: Start screen = no session
    new_task = find_element(elements, "New task", window="Claude")
    if new_task:
        log.info("Session NOT active: 'New task' visible (start screen)")
        return False

    # No clear signal -- check for reply/input field which suggests
    # we're inside a session (even if idle)
    prompt_field = (
        find_element(elements, "Reply", window="Claude")
        or find_element(elements, "Write your prompt", window="Claude")
    )
    if prompt_field:
        log.debug("Session appears active: input field visible")
        return True

    # S77 FIX: Default to NOT active. A false-negative here (thinking
    # session ended when it hasn't) just launches a harmless new tab.
    # A false-positive (thinking session active when it ended) blocks
    # all future launches indefinitely — which is catastrophic.
    # The sentinel log showed 5+ hours of "Session still active"
    # because this defaulted to True. Never again.
    log.info("Session status ambiguous (no indicators, no start screen, "
             "no input field) -- treating as ENDED to allow launch")
    return False


# S77: Session timeout -- how long to wait for a session to end before
# launching a new one anyway. If the last launch was > this many minutes
# ago and no fresh handoff has appeared, the session has likely ended
# (or crashed) and Robin should start a new one.
SESSION_TIMEOUT_MINUTES = 45


def check_and_launch_perpetual():
    """Sentinel integration point — DISABLED S78.

    Session launching is now handled exclusively by the standalone
    intelligent launcher: scripts/launch_cowork.py --loop

    The sentinel's launcher was unreliable across 78 sessions due to:
    - Split prompts (Type tool splitting on semicolons)
    - Race conditions with the standalone launcher
    - No Snapshot-based state assessment before each action
    - False-positive session-active detection blocking all launches

    The standalone launcher uses PERCEIVE-REASON-ACT-VERIFY at every
    step and runs as a separate process with a 2-minute check interval.
    """
    log.info("Session launching disabled in sentinel (S78) -- "
             "handled by scripts/launch_cowork.py")
    return {"success": False, "skipped": True,
            "reason": "disabled_s78_standalone_launcher"}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [PerpetualLoop] %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Robin Perpetual Work Loop")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log actions without executing")
    args = parser.parse_args()

    result = perpetual_loop_handoff(dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
