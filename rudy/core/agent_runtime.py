"""Runtime helpers extracted from sentinel.py (S202).

Generic, dependency-free primitives for agent runtime budgeting and
observation record construction. Behavior is byte-equivalent to the
prior inline implementations in `rudy.agents.sentinel.Sentinel._time_ok`
and `Sentinel._observe`. See vault/Handoffs/Session-202-Handoff.md.

These are pure functions: no I/O, no logging, no global state. The
caller (Sentinel or any future agent) is responsible for owning
`start`, `max_runtime`, the observations list, and any logger.
"""
from __future__ import annotations

import time
from datetime import datetime


def time_ok(start: float, max_runtime: float) -> bool:
    """Return True while elapsed wall-clock since `start` is under `max_runtime`.

    Mirrors `Sentinel._time_ok` exactly: strict less-than on
    `(time.time() - start) < max_runtime`.
    """
    return (time.time() - start) < max_runtime


def make_observation(
    category: str,
    observation: str,
    actionable: bool = False,
) -> dict:
    """Build a single observation record.

    Mirrors the dict literal in `Sentinel._observe` exactly. Pure: no
    side effects. Caller appends to its observations list and logs.
    """
    return {
        "time": datetime.now().isoformat(),
        "category": category,
        "observation": observation,
        "actionable": actionable,
    }
