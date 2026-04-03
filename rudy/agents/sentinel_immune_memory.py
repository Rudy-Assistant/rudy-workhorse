"""
Sentinel Immune Memory -- Known-good state and failure memory.

Extracted from robin_sentinel.py (Session 79, ADR-005 Phase 2b).
Manages the known-good baseline and immune memory (what broke + what fixed it).
"""

import json
import logging
from datetime import datetime
from typing import Any

from rudy.paths import RUDY_DATA

KNOWN_GOOD_STATE = RUDY_DATA / "known-good-state.json"
IMMUNE_MEMORY = RUDY_DATA / "robin-immune-memory.json"

log = logging.getLogger("robin_sentinel")

DEFAULT_KNOWN_GOOD: dict[str, Any] = {
    "version": 2,
    "last_updated": None,
    "services": {
        "Tailscale": {"type": "windows-service", "name": "Tailscale", "expected": "running", "sacred": True},
        "sshd": {"type": "windows-service", "name": "sshd", "expected": "running", "sacred": True},
        "WinRM": {"type": "windows-service", "name": "WinRM", "expected": "running", "sacred": True},
    },
    "processes": {
        "rustdesk": {"max_instances": 3, "kill_zombies": True, "sacred": True},
        "ollama": {"expected": True, "port": 11434},
    },
    "scheduled_tasks": {
        "RudyCommandRunner": {"expected": "enabled"},
        "RudyEmailListener": {"expected": "enabled"},
        "RobinSentinel": {"expected": "enabled"},
    },
    "network": {
        "tailscale_ip": "100.83.49.9",
        "dns_test_host": "api.github.com",
        "email_host": "imap.zohomail.com",
    },
    "recovery_playbook": {},
}

def load_known_good() -> dict:
    """Load known-good state, falling back to defaults."""
    if KNOWN_GOOD_STATE.exists():
        try:
            with open(KNOWN_GOOD_STATE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Corrupted known-good state, using defaults: %s", e)
    return DEFAULT_KNOWN_GOOD.copy()

def save_known_good(state: dict) -> None:
    """Persist known-good state with immune memory updates."""
    state["last_updated"] = datetime.now().isoformat()
    tmp = KNOWN_GOOD_STATE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(KNOWN_GOOD_STATE)

def load_immune_memory() -> dict:
    """Load immune memory — record of what went wrong and what fixed it."""
    if IMMUNE_MEMORY.exists():
        try:
            with open(IMMUNE_MEMORY) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"fixes": [], "patterns": {}}

def record_fix(memory: dict, problem: str, fix: str, success: bool) -> None:
    """Record a fix attempt in immune memory."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "problem": problem,
        "fix": fix,
        "success": success,
    }
    memory["fixes"].append(entry)
    if success:
        memory["patterns"][problem] = fix
    tmp = IMMUNE_MEMORY.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(memory, f, indent=2)
    tmp.replace(IMMUNE_MEMORY)

