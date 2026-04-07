"""Generic JSON state-file helpers extracted from rudy/agents/sentinel.py (S201).

Sentinel was the first place these functions appeared, but the load/save
pattern is generic to any long-running agent that persists per-run state
to a JSON file. Extracting them here lets future agents reuse the same
shape without copy-pasting from sentinel.py. See vault/Handoffs/Session-201-Handoff.md.

This module is intentionally small, dependency-free, and stdlib-only so
it can be imported from anywhere in rudy/ without circular-import risk.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


DEFAULT_STATE: Dict[str, Any] = {
    "run_count": 0,
    "last_run": None,
    "file_hashes": {},
    "last_agent_statuses": {},
    "improvement_log": [],
    "streak": 0,  # consecutive healthy runs
}


def load_state(state_file: Path, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Load JSON state from `state_file`. Return `default` (or DEFAULT_STATE) on
    any failure (missing file, decode error, IO error). Mirrors the behavior of
    Sentinel._load_state for backward compatibility.
    """
    state_file = Path(state_file)
    if state_file.exists():
        try:
            with open(state_file) as f:
                return json.load(f)
        except Exception:
            pass
    return dict(default if default is not None else DEFAULT_STATE)


def save_state(state_file: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp `last_run` and increment `run_count`, then write `state` to
    `state_file` as pretty JSON. Returns the (mutated) state dict for chaining.
    Mirrors the behavior of Sentinel._save_state.
    """
    state_file = Path(state_file)
    state["last_run"] = datetime.now().isoformat()
    state["run_count"] = state.get("run_count", 0) + 1
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    return state
