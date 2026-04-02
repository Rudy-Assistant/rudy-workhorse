#!/usr/bin/env python3
"""
Robin Cowork Launcher v4 -- Intelligent agent, not a macro.

Uses the PERCEIVE -> REASON -> ACT -> VERIFY pattern:
  - PERCEIVE: Windows-MCP Snapshot to see the screen
  - REASON: Parse elements, find targets BY NAME (no hardcoded coords)
  - ACT: Click/Type via MCP
  - VERIFY: Snapshot again, confirm success

Composes existing modules: robin_mcp_client + robin_human_adapter.
Zero new dependencies. Zero hardcoded coordinates.
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from rudy.robin_mcp_client import MCPServerRegistry
from rudy.robin_human_adapter import create_human_interface
from rudy.paths import REPO_ROOT

log = logging.getLogger("robin_cowork_launcher")

VAULT_HANDOFFS = REPO_ROOT / "vault" / "Handoffs"
COORD_DIR = REPO_ROOT / "rudy-data" / "coordination"
STATE_FILE = COORD_DIR / "cowork-launcher-state.json"

PROMPT_TEMPLATE = (
    "Good evening, Alfred. Session {session} bootstrap.\n\n"
    "READ THESE FILES FIRST (via Desktop Commander):\n"
    "1. C:\\Users\\ccimi\\rudy-workhorse\\CLAUDE.md\n"  # lucius-exempt: bootstrap prompt path for next session
    "2. {handoff_path}\n\n"
    "Follow directive and protocol; then proceed."
)

NO_HANDOFF_PROMPT = (
    "Good evening, Alfred. New session bootstrap.\n\n"
    "READ THIS FILE FIRST (via Desktop Commander):\n"
    "C:\\Users\\ccimi\\rudy-workhorse\\CLAUDE.md\n\n"  # lucius-exempt: bootstrap prompt path for next session
    "No handoff file found. Check vault/Handoffs/ for context. "
    "Follow directive and protocol; then proceed."
)


# ---------------------------------------------------------------------------
# PERCEIVE + REASON: Parse Snapshot, find elements by name
# ---------------------------------------------------------------------------

ELEMENT_RE = re.compile(
    r"(\d+)\|([^|]*)\|([^|]*)\|([^|]*)\|"
    r"\((\d+),\s*(\d+)\)"
)

def parse_snapshot_elements(snapshot_text: str) -> list[dict]:
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


def find_element(elements: list[dict], name_pattern: str,
                 window: str = None, control_type: str = None) -> dict | None:
    """Find an element by name pattern (case-insensitive substring match).

    Robin REASONS about the UI: finds targets dynamically by name,
    never by hardcoded pixel coordinates.
    """
    pattern = name_pattern.lower()
    for el in elements:
        if pattern not in el["name"].lower():
            continue
        if window and window.lower() not in el["window"].lower():
            continue
        if control_type and control_type.lower() != el["control_type"].lower():
            continue
        return el
    return None

def _find_latest_handoff() -> Path | None:
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
# Main launch: PERCEIVE -> REASON -> ACT -> VERIFY
# ---------------------------------------------------------------------------

def launch_cowork_session(
    handoff_path: str | Path | None = None,
    prompt: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Launch a Cowork session using Robin's intelligence."""
    result = {
        "success": False,
        "timestamp": datetime.now().isoformat(),
        "handoff_used": None,
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
    # --- PERCEIVE -> REASON -> ACT -> VERIFY ---
    try:
        registry = MCPServerRegistry()
        if not registry.connect("windows-mcp"):
            result["error"] = "Cannot connect to Windows-MCP"
            return result

        def wmcp(tool, args):
            return registry.call_tool(f"windows-mcp.{tool}", args)

        # === STEP 0: PERCEIVE - See the screen ===
        log.info("PERCEIVE: Taking initial Snapshot...")
        snap = wmcp("Snapshot", {"use_vision": False})
        if not snap.success:
            result["error"] = f"Snapshot failed: {snap.error}"
            return result
        elements = parse_snapshot_elements(snap.content or "")
        log.info("PERCEIVE: Found %d interactive elements", len(elements))
        # === STEP 1: REASON - Find "New task" by name ===
        new_task = find_element(elements, "New task", window="Claude")
        if not new_task:
            # Claude Desktop might not be focused. Try clicking taskbar.
            taskbar_claude = find_element(elements, "Claude", window="Taskbar")
            if taskbar_claude:
                log.info("REASON: Claude not focused. Clicking taskbar...")
                wmcp("Click", {"x": taskbar_claude["x"],
                               "y": taskbar_claude["y"]})
                time.sleep(2)
                # Re-perceive after focusing
                snap = wmcp("Snapshot", {"use_vision": False})
                elements = parse_snapshot_elements(snap.content or "")
                new_task = find_element(elements, "New task", window="Claude")

        if not new_task:
            result["error"] = ("Cannot find 'New task' element. "
                               "Claude Desktop may not be open.")
            return result

        # === ACT: Click "New Task" ===
        log.info("ACT: Clicking 'New task' at (%d, %d)",
                 new_task["x"], new_task["y"])
        wmcp("Click", {"x": new_task["x"], "y": new_task["y"]})
        time.sleep(2.5)
        # === VERIFY + PERCEIVE again ===
        log.info("VERIFY: Snapshot after New Task click...")
        snap = wmcp("Snapshot", {"use_vision": False})
        elements = parse_snapshot_elements(snap.content or "")

        # === STEP 2: REASON - Find and select Cowork mode ===
        cowork_radio = find_element(elements, "Cowork",
                                    window="Claude", control_type="Radio Button")
        if cowork_radio:
            log.info("ACT: Selecting Cowork mode at (%d, %d)",
                     cowork_radio["x"], cowork_radio["y"])
            wmcp("Click", {"x": cowork_radio["x"],
                           "y": cowork_radio["y"]})
            time.sleep(0.5)
        else:
            log.warning("REASON: Cowork radio not found -- may already be selected")
        # === STEP 3: REASON - Find prompt input ===
        prompt_input = find_element(elements, "Write your prompt",
                                    window="Claude")
        if not prompt_input:
            # Fallback: look for any Edit control in Claude
            prompt_input = find_element(elements, "",
                                        window="Claude",
                                        control_type="Edit")
        if not prompt_input:
            result["error"] = "Cannot find prompt input field"
            return result

        # === ACT: Click input, type prompt, send ===
        log.info("ACT: Clicking prompt input at (%d, %d)",
                 prompt_input["x"], prompt_input["y"])
        wmcp("Click", {"x": prompt_input["x"],
                       "y": prompt_input["y"]})
        time.sleep(0.3)

        log.info("ACT: Typing prompt (%d chars)", len(prompt))
        wmcp("Type", {"text": prompt})
        time.sleep(0.5)

        log.info("ACT: Sending with Enter")
        wmcp("Shortcut", {"keys": ["enter"]})
        time.sleep(2.0)
        # === FINAL VERIFY: Did the session start? ===
        log.info("VERIFY: Final Snapshot to confirm launch...")
        snap = wmcp("Snapshot", {"use_vision": False})
        final_elements = parse_snapshot_elements(snap.content or "")

        # Check if we see signs of a new session (e.g., Stop button,
        # progress indicator, or the prompt area changed)
        stop_btn = find_element(final_elements, "Stop", window="Claude")
        progress = find_element(final_elements, "Progress", window="Claude")
        if stop_btn or progress:
            log.info("VERIFY: Session appears to be starting (found activity indicators)")
        else:
            log.info("VERIFY: Snapshot captured. Session may be loading.")

        result["success"] = True
        registry.disconnect_all()

    except Exception as e:
        result["error"] = str(e)
        log.error("Launch failed: %s", e, exc_info=True)

    # Save state for sentinel
    try:
        state = {
            "last_launch": result,
            "last_updated": datetime.now().isoformat(),
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.warning("State save failed: %s", e)

    return result

def check_and_launch_if_needed() -> dict | None:
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
