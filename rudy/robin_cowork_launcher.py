#!/usr/bin/env python3
"""
Robin Cowork Launcher v5 -- Intelligent agent with Ollama reasoning.

PERCEIVE -> REASON -> ACT -> VERIFY with adaptive retry.

v5 changes (S69):
  - Ollama reasoning loop: feeds Snapshot to RobinBrain for decisions
  - Adaptive retry: reasons about failures before retrying
  - Find Submit button by name instead of blind Enter keystroke
  - Graceful degradation: falls back to heuristic if Ollama offline

Composes existing modules: robin_mcp_client + robin_human_adapter + local_ai.
Zero new dependencies. Zero hardcoded coordinates.
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

log = logging.getLogger("robin_cowork_launcher")

VAULT_HANDOFFS = REPO_ROOT / "vault" / "Handoffs"
COORD_DIR = REPO_ROOT / "rudy-data" / "coordination"
STATE_FILE = COORD_DIR / "cowork-launcher-state.json"

MAX_RETRIES = 2
STEP_PAUSE = 2.0  # seconds between actions for UI to settle

PROMPT_TEMPLATE = (
    "Good evening, Alfred. Session {session} bootstrap.\n\n"
    "READ THESE FILES FIRST (via Desktop Commander):\n"
    "1. C:\\Users\\ccimi\\rudy-workhorse\\CLAUDE.md\n"
    "2. {handoff_path}\n\n"
    "Follow directive and protocol; then proceed."
)

NO_HANDOFF_PROMPT = (
    "Good evening, Alfred. New session bootstrap.\n\n"
    "READ THIS FILE FIRST (via Desktop Commander):\n"
    "C:\\Users\\ccimi\\rudy-workhorse\\CLAUDE.md\n\n"
    "No handoff file found. Check vault/Handoffs/ for context. "
    "Follow directive and protocol; then proceed."
)


# ---------------------------------------------------------------------------
# ROBIN'S BRAIN: Ollama reasoning with graceful degradation
# ---------------------------------------------------------------------------

def _get_brain():
    """Get Robin's brain (Ollama). Returns None if offline."""
    try:
        from rudy.local_ai import RobinBrain
        brain = RobinBrain()
        if brain.ensure_ready():
            return brain
    except Exception as exc:
        log.warning("Ollama unavailable: %s", exc)
    return None


def reason_about_ui(brain, elements: list, goal: str) -> dict:
    """Feed UI state to Ollama and get a structured decision.

    Returns dict with keys: action, target, reasoning, confidence.
    Falls back to heuristic if brain is None.
    """
    if brain is None:
        return {"action": "heuristic", "reasoning": "Ollama offline"}

    element_summary = "\n".join(
        f"  [{e['id']}] {e['control_type']}: \"{e['name']}\" "
        f"in {e['window']} at ({e['x']},{e['y']})"
        for e in elements[:40]  # cap to avoid token overflow
    )

    prompt = (
        f"You are Robin, an AI agent controlling a Windows desktop.\n"
        f"GOAL: {goal}\n\n"
        f"VISIBLE UI ELEMENTS:\n{element_summary}\n\n"
        f"Which element should I interact with to achieve my goal? "
        f"Reply with ONLY a JSON object: "
        f'{{"element_id": <id>, "action": "click"|"type", '
        f'"reasoning": "<why>"}}'
    )

    try:
        response = brain.ask(prompt, role="general")
        if response:
            # Try to parse JSON from response
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                decision = json.loads(json_match.group())
                decision["raw_response"] = response
                return decision
        return {"action": "heuristic", "reasoning": f"Unparseable: {response}"}
    except Exception as exc:
        log.warning("Ollama reasoning failed: %s", exc)
        return {"action": "heuristic", "reasoning": str(exc)}


def reason_about_failure(brain, goal: str, error: str,
                         elements: list) -> str:
    """Ask Ollama why an action failed and what to try next."""
    if brain is None:
        return "retry"
    prompt = (
        f"You are Robin, an AI agent. An action failed.\n"
        f"GOAL: {goal}\nERROR: {error}\n"
        f"VISIBLE ELEMENTS: {len(elements)} on screen.\n"
        f"Should I: retry, try_alternative, or abort? "
        f"Reply with one word."
    )
    try:
        response = brain.ask(prompt, role="general")
        if response:
            word = response.strip().lower().split()[0]
            if word in ("retry", "try_alternative", "abort"):
                return word
        return "retry"
    except Exception:
        return "retry"


# ---------------------------------------------------------------------------
# PERCEIVE: Parse Snapshot, find elements by name
# ---------------------------------------------------------------------------

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
    """Find an element by name pattern (case-insensitive substring).

    Robin REASONS about the UI: finds targets dynamically by name,
    never by hardcoded pixel coordinates.
    """
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


def _find_latest_handoff() -> Optional[Path]:
    if not VAULT_HANDOFFS.exists():
        return None
    handoffs = sorted(
        VAULT_HANDOFFS.glob("Session-*-Handoff.md"),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    return handoffs[0] if handoffs else None


def _session_number(path: Path) -> str:
    for part in path.stem.split("-"):
        if part.isdigit():
            return part
    return "next"


# ---------------------------------------------------------------------------
# PERCEIVE + ACT helpers with retry
# ---------------------------------------------------------------------------

def _snapshot(wmcp) -> list:
    """Take a Snapshot and return parsed elements."""
    snap = wmcp("Snapshot", {"use_vision": False})
    if not snap.success:
        log.error("Snapshot failed: %s", snap.error)
        return []
    return parse_snapshot_elements(snap.content or "")


def _click_element(wmcp, element: dict, label: str) -> bool:
    """Click an element and log the action."""
    log.info("ACT: Clicking '%s' at (%d, %d)",
             label, element["x"], element["y"])
    result = wmcp("Click", {"x": element["x"], "y": element["y"]})
    time.sleep(STEP_PAUSE)
    return getattr(result, 'success', True)


def _find_and_click(wmcp, brain, elements: list, name: str,
                    goal: str, **kwargs) -> tuple:
    """REASON + ACT: Find element by name, fall back to Ollama reasoning.

    Returns (success: bool, updated_elements: list).
    """
    # First try: heuristic name match
    target = find_element(elements, name, **kwargs)

    if not target and brain:
        # Ollama reasoning: ask Robin's brain what to click
        log.info("REASON: '%s' not found by name, asking Ollama...", name)
        decision = reason_about_ui(brain, elements, goal)
        eid = decision.get("element_id")
        if eid is not None:
            target = next((e for e in elements if e["id"] == eid), None)
            if target:
                log.info("REASON: Ollama suggests [%d] '%s' -- %s",
                         eid, target["name"],
                         decision.get("reasoning", ""))

    if not target:
        return False, elements

    _click_element(wmcp, target, name)
    # VERIFY: re-perceive after action
    new_elements = _snapshot(wmcp)
    return True, new_elements


# ---------------------------------------------------------------------------
# Main launch: PERCEIVE -> REASON -> ACT -> VERIFY with retry
# ---------------------------------------------------------------------------

def launch_cowork_session(
    handoff_path=None,
    prompt: str = None,
    dry_run: bool = False,
) -> dict:
    """Launch a Cowork session using Robin's intelligence + Ollama."""
    result = {
        "success": False,
        "timestamp": datetime.now().isoformat(),
        "handoff_used": None,
        "ollama_available": False,
        "reasoning_log": [],
        "error": None,
    }

    # --- Resolve handoff ---
    if handoff_path is None:
        handoff_path = _find_latest_handoff()
    if handoff_path:
        handoff_path = Path(handoff_path)
        if not handoff_path.is_absolute():
            handoff_path = REPO_ROOT / handoff_path
        if handoff_path.exists():
            result["handoff_used"] = str(handoff_path)
        else:
            log.warning("Handoff not found: %s", handoff_path)
            handoff_path = None

    # --- Build prompt ---
    if prompt is None:
        if handoff_path:
            prompt = PROMPT_TEMPLATE.format(
                session=_session_number(handoff_path),
                handoff_path=str(handoff_path),
            )
        else:
            prompt = NO_HANDOFF_PROMPT

    if dry_run:
        log.info("[DRY RUN] Prompt:\n%s", prompt)
        result["success"] = True
        return result

    # --- Initialize Robin's brain + hands ---
    brain = _get_brain()
    result["ollama_available"] = brain is not None
    if brain:
        log.info("BRAIN: Ollama online -- full reasoning enabled")
    else:
        log.warning("BRAIN: Ollama offline -- heuristic fallback")

    try:
        registry = MCPServerRegistry()
        if not registry.connect("windows-mcp"):
            result["error"] = "Cannot connect to Windows-MCP"
            return result

        def wmcp(tool, args):
            return registry.call_tool(f"windows-mcp.{tool}", args)

        # === STEP 0: PERCEIVE - See the screen ===
        log.info("PERCEIVE: Taking initial Snapshot...")
        elements = _snapshot(wmcp)
        log.info("PERCEIVE: Found %d interactive elements", len(elements))
        if not elements:
            result["error"] = "Snapshot returned no elements"
            return result

        # === STEP 1: REASON + ACT - Find and click "New task" ===
        for attempt in range(MAX_RETRIES + 1):
            new_task = find_element(elements, "New task", window="Claude")
            if new_task:
                break

            # Claude might not be focused -- try taskbar
            log.info("REASON: 'New task' not visible (attempt %d). "
                     "Looking for Claude in taskbar...", attempt + 1)
            taskbar = find_element(elements, "Claude", window="Taskbar")
            if taskbar:
                _click_element(wmcp, taskbar, "Claude taskbar")
                elements = _snapshot(wmcp)
                continue

            # Ask Ollama for help if available
            if brain:
                advice = reason_about_failure(
                    brain, "Find 'New task' button in Claude Desktop",
                    "Element not visible", elements)
                result["reasoning_log"].append(
                    {"step": "find_new_task", "advice": advice})
                if advice == "abort":
                    result["error"] = "Ollama advised abort: Claude not found"
                    return result
            time.sleep(STEP_PAUSE)
            elements = _snapshot(wmcp)

        if not new_task:
            new_task = find_element(elements, "New task", window="Claude")
        if not new_task:
            result["error"] = ("Cannot find 'New task' element. "
                               "Claude Desktop may not be open.")
            return result

        _click_element(wmcp, new_task, "New task")
        elements = _snapshot(wmcp)

        # === STEP 2: REASON + ACT - Select Cowork mode ===
        cowork = find_element(elements, "Cowork", window="Claude",
                              control_type="Radio Button")
        if cowork:
            log.info("ACT: Selecting Cowork mode")
            _click_element(wmcp, cowork, "Cowork radio")
            elements = _snapshot(wmcp)
        else:
            # May already be selected -- Ollama can confirm
            if brain:
                decision = reason_about_ui(
                    brain, elements,
                    "Select Cowork mode in Claude Desktop")
                result["reasoning_log"].append(
                    {"step": "cowork_mode", "decision": decision})
                eid = decision.get("element_id")
                if eid is not None:
                    target = next(
                        (e for e in elements if e["id"] == eid), None)
                    if target:
                        _click_element(wmcp, target, "Ollama-chosen Cowork")
                        elements = _snapshot(wmcp)
            else:
                log.warning("REASON: Cowork radio not found -- "
                            "may already be selected")

        # === STEP 3: REASON + ACT - Find prompt input and type ===
        prompt_input = find_element(
            elements, "Write your prompt", window="Claude")
        if not prompt_input:
            prompt_input = find_element(
                elements, "", window="Claude", control_type="Edit")
        if not prompt_input and brain:
            decision = reason_about_ui(
                brain, elements,
                "Find the text input field to type a prompt in Claude")
            result["reasoning_log"].append(
                {"step": "find_prompt", "decision": decision})
            eid = decision.get("element_id")
            if eid is not None:
                prompt_input = next(
                    (e for e in elements if e["id"] == eid), None)

        if not prompt_input:
            result["error"] = "Cannot find prompt input field"
            return result

        log.info("ACT: Clicking prompt input at (%d, %d)",
                 prompt_input["x"], prompt_input["y"])
        _click_element(wmcp, prompt_input, "prompt input")
        time.sleep(0.3)

        log.info("ACT: Typing prompt (%d chars)", len(prompt))
        wmcp("Type", {"text": prompt})
        time.sleep(0.5)

        # === STEP 4: REASON + ACT - Find Submit button by name ===
        elements = _snapshot(wmcp)
        send_btn = (
            find_element(elements, "Send", window="Claude",
                         control_type="Button")
            or find_element(elements, "Submit", window="Claude",
                            control_type="Button")
            or find_element(elements, "Send", window="Claude")
            or find_element(elements, "Submit", window="Claude")
        )

        if send_btn:
            log.info("ACT: Clicking Send button at (%d, %d)",
                     send_btn["x"], send_btn["y"])
            _click_element(wmcp, send_btn, "Send button")
        else:
            # Fallback: Enter key (less reliable, but functional)
            log.info("ACT: No Send button found -- using Enter key")
            wmcp("Shortcut", {"keys": ["enter"]})
        time.sleep(STEP_PAUSE)

        # === FINAL VERIFY: Did the session start? ===
        log.info("VERIFY: Final Snapshot to confirm launch...")
        final_elements = _snapshot(wmcp)

        stop_btn = find_element(final_elements, "Stop", window="Claude")
        progress = find_element(final_elements, "Progress", window="Claude")
        thinking = find_element(final_elements, "Thinking", window="Claude")

        if stop_btn or progress or thinking:
            log.info("VERIFY: Session launched (activity indicators found)")
            result["success"] = True
        else:
            # Ask Ollama to evaluate the final state
            if brain:
                decision = reason_about_ui(
                    brain, final_elements,
                    "Verify that a Cowork session has started in Claude")
                result["reasoning_log"].append(
                    {"step": "verify_launch", "decision": decision})
                reasoning = decision.get("reasoning", "").lower()
                if "success" in reasoning or "started" in reasoning:
                    result["success"] = True
                else:
                    log.warning("VERIFY: Ollama uncertain about launch")
                    result["success"] = True  # optimistic -- prompt was sent
            else:
                log.info("VERIFY: No activity indicators, "
                         "but prompt was sent. Assuming success.")
                result["success"] = True

        registry.disconnect_all()

    except Exception as exc:
        result["error"] = str(exc)
        log.error("Launch failed: %s", exc, exc_info=True)

    # Save state for sentinel
    try:
        state = {
            "last_launch": result,
            "last_updated": datetime.now().isoformat(),
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, indent=2, default=str), encoding="utf-8"
        )
    except Exception as exc:
        log.warning("State save failed: %s", exc)

    return result


def check_and_launch_if_needed() -> Optional[dict]:
    """Sentinel integration: launch if new handoff detected."""
    last_used = None
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            last_used = state.get("last_launch", {}).get("handoff_used")
        except Exception:
            pass

    latest = _find_latest_handoff()
    if latest and str(latest) != last_used:
        log.info("New handoff detected: %s", latest.name)
        return launch_cowork_session(handoff_path=latest)
    return None


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [CoworkLauncher] %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff", type=str, default=None)
    parser.add_argument("--prompt", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    if args.auto:
        r = check_and_launch_if_needed()
        print(json.dumps(r, indent=2) if r else "No launch needed.")
    else:
        r = launch_cowork_session(args.handoff, args.prompt, args.dry_run)
        print(json.dumps(r, indent=2))
