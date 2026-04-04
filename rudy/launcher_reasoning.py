"""
Ollama reasoning layer for the Cowork launcher.

Provides PERCEIVE -> REASON -> ACT -> VERIFY intelligence
as an additive layer on top of heuristic state detection.
Graceful degradation: returns None when Ollama is offline,
letting the caller fall back to heuristics.

Used by: scripts/launch_cowork_simple.py
Architecture: docs/MISSION.md Intelligence Mandate
"""

import json
import logging
import re
import time
from typing import Optional

log = logging.getLogger("launcher.reasoning")

# Cache brain instance across calls
_brain = None
_brain_checked = False


def get_brain():
    """Get Ollama brain (cached). Returns None if offline."""
    global _brain, _brain_checked
    if _brain_checked:
        return _brain
    _brain_checked = True
    try:
        from rudy.local_ai import LocalAI
        brain = LocalAI(default_model="qwen2.5:7b")
        # Check Ollama is reachable
        if brain._ollama.is_available():
            _brain = brain
            log.info("BRAIN: Ollama online -- reasoning enabled")
            return _brain
        log.warning("BRAIN: Ollama not reachable")
    except Exception as exc:
        log.warning("BRAIN: Ollama unavailable: %s", exc)
    return None


def reset_brain():
    """Force re-check of Ollama availability."""
    global _brain, _brain_checked
    _brain = None
    _brain_checked = False


def _format_elements(els, limit=30):
    """Format element list for Ollama prompt."""
    lines = []
    for e in els[:limit]:
        lines.append(
            f"  [{e['id']}] {e['ctrl']}: \"{e['name']}\" "
            f"in {e['win']} at ({e['x']},{e['y']})"
        )
    return "\n".join(lines)


def reason_about_state(els) -> Optional[str]:
    """Ask Ollama to classify UI state from snapshot elements.

    Returns one of: working, idle, ready, mount, cowork_select, gone, None.
    Returns None if Ollama is offline (caller uses heuristic).
    """
    brain = get_brain()
    if brain is None:
        return None

    el_text = _format_elements(els)
    prompt = (
        "You are Robin, an AI agent monitoring Claude Desktop.\n"
        "Based on these UI elements, classify the application state.\n\n"
        f"VISIBLE UI ELEMENTS:\n{el_text}\n\n"
        "States:\n"
        "- working: Claude is actively generating (Stop, Thinking, "
        "Working, Generating visible)\n"
        "- idle: Session exists but Claude is waiting for input "
        "(Reply or prompt input visible, no activity)\n"
        "- ready: No active session, New task button visible\n"
        "- mount: Permission dialog with Allow/Deny buttons\n"
        "- cowork_select: Cowork radio button visible on new task form\n"
        "- gone: Claude window not visible\n\n"
        "Reply with ONLY the state name, nothing else."
    )

    try:
        response = brain.ask(prompt, role="general")
        if response:
            state = response.strip().lower().split()[0]
            valid = {"working", "idle", "ready", "mount",
                     "cowork_select", "gone"}
            if state in valid:
                log.info("REASON: Ollama classifies state=%s", state)
                return state
            log.warning("REASON: Ollama returned invalid state: %s",
                        response.strip())
    except Exception as exc:
        log.warning("REASON: Ollama state classification failed: %s", exc)
    return None


def reason_find_element(els, goal) -> Optional[dict]:
    """Ask Ollama to find the right element to interact with.

    Args:
        els: Parsed snapshot elements.
        goal: What we're trying to do (e.g., "Find the Send button").

    Returns element dict or None.
    """
    brain = get_brain()
    if brain is None:
        return None

    el_text = _format_elements(els, limit=40)
    prompt = (
        "You are Robin, an AI agent controlling Claude Desktop.\n"
        f"GOAL: {goal}\n\n"
        f"VISIBLE UI ELEMENTS:\n{el_text}\n\n"
        "Which element should I interact with? "
        "Reply with ONLY the element ID number, nothing else."
    )

    try:
        response = brain.ask(prompt, role="general")
        if response:
            # Extract first number from response
            match = re.search(r'\d+', response.strip())
            if match:
                eid = int(match.group())
                target = next((e for e in els if e["id"] == eid), None)
                if target:
                    log.info("REASON: Ollama suggests [%d] '%s' for '%s'",
                             eid, target["name"], goal)
                    return target
    except Exception as exc:
        log.warning("REASON: Ollama element search failed: %s", exc)
    return None


def reason_about_failure(goal, error, els) -> str:
    """Ask Ollama what to do after an action fails.

    Returns: 'retry', 'try_alternative', or 'abort'.
    """
    brain = get_brain()
    if brain is None:
        return "retry"

    prompt = (
        "You are Robin, an AI agent. An action failed.\n"
        f"GOAL: {goal}\n"
        f"ERROR: {error}\n"
        f"VISIBLE ELEMENTS: {len(els)} on screen.\n"
        "Should I: retry, try_alternative, or abort? "
        "Reply with one word only."
    )

    try:
        response = brain.ask(prompt, role="general")
        if response:
            word = response.strip().lower().split()[0]
            if word in ("retry", "try_alternative", "abort"):
                log.info("REASON: Ollama advises '%s' for failed '%s'",
                         word, goal)
                return word
    except Exception as exc:
        log.warning("REASON: Ollama failure analysis failed: %s", exc)
    return "retry"


def reason_verify_launch(els) -> Optional[bool]:
    """Ask Ollama whether a Cowork session has successfully started.

    Returns True/False or None if Ollama unavailable.
    """
    brain = get_brain()
    if brain is None:
        return None

    el_text = _format_elements(els)
    prompt = (
        "You are Robin, an AI agent. I just launched a Cowork session "
        "in Claude Desktop.\n\n"
        f"CURRENT UI ELEMENTS:\n{el_text}\n\n"
        "Has the session started successfully? Look for indicators "
        "like Stop button, Thinking text, Working text, Context "
        "indicator, or Todo list.\n"
        "Reply with ONLY 'yes' or 'no'."
    )

    try:
        response = brain.ask(prompt, role="general")
        if response:
            word = response.strip().lower().split()[0]
            result = word in ("yes", "true", "started", "success")
            log.info("REASON: Ollama launch verification=%s", result)
            return result
    except Exception as exc:
        log.warning("REASON: Ollama launch verification failed: %s", exc)
    return None
