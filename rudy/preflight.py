#!/usr/bin/env python3
"""
Preflight — mechanical enforcement of S199 session-start rules.

Created S199 in response to Chris's correctness call: voluntary
compliance with "report context" and "do not claim a blocker without
tool-grepping" had failed for three consecutive sessions. This module
makes both checks have file-system side effects so the next session can
verify them mechanically.

Public API
----------
    report_context(pct: int) -> None
        Append a context-percentage entry for the current session to
        ``rudy-data/preflight/context-log.jsonl``. Raises
        ``ContextReportError`` if pct is out of range. The next
        session's handoff is REQUIRED to read this file and refuse to
        write itself if no entry exists for the prior session.

    claim_blocked(reason, verbs, searched) -> None
        Sanity-check a "blocked because" claim before it is written.
        Requires that ``searched`` (a list of (tool_name, query) pairs)
        covers every verb in ``verbs``. Raises
        ``BlockerClaimWithoutGrepError`` otherwise. Records the claim
        + searches to ``rudy-data/preflight/blocker-claims.jsonl`` so
        the next audit can verify Rule 9 compliance.

    assert_session_start(session_number, context_pct) -> dict
        Combined preflight: writes the context entry, verifies the
        prior session's entry exists (warns if missing), returns a
        status dict for the handoff to embed.

    last_session_context(n: int = 1) -> dict | None
        Read the most recent context entry. Used by handoff writers to
        verify the prior session reported.

This module is stdlib-only on purpose (matches lucius_gate.py's
deliberate import isolation). Failure modes are loud, not silent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# Anchor to *this* file's checkout, NOT cwd. rudy.paths.RUDY_DATA is
# cwd-relative in some checkouts, which broke the S199 first run.
RUDY_DATA = Path(__file__).resolve().parent.parent / "rudy-data"
PREFLIGHT_DIR = RUDY_DATA / "preflight"
CONTEXT_LOG = PREFLIGHT_DIR / "context-log.jsonl"
BLOCKER_LOG = PREFLIGHT_DIR / "blocker-claims.jsonl"

log = logging.getLogger("preflight")


# -------------------------------------------------------------------
# Exceptions -- loud failure on purpose
# -------------------------------------------------------------------

class PreflightError(Exception):
    """Base class. Anything that inherits this is a Rule 8/9 violation."""


class ContextReportError(PreflightError):
    """Raised when a context-percentage report is malformed."""


class BlockerClaimWithoutGrepError(PreflightError):
    """Raised when ``claim_blocked`` is called without sufficient searches.

    The cure is mechanical: do the grep, then call again with the
    results. Do NOT catch and ignore this exception."""


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _ensure_dir() -> None:
    PREFLIGHT_DIR.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, entry: dict) -> None:
    _ensure_dir()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# -------------------------------------------------------------------
# Rule 8 -- context reporting
# -------------------------------------------------------------------

def report_context(
    pct: int | float,
    session_number: Optional[int] = None,
    note: str = "",
) -> dict:
    """Record a context-percentage report. Required at session start.

    Raises ContextReportError if pct is not in [0, 100].
    """
    try:
        pct_f = float(pct)
    except (TypeError, ValueError) as e:
        raise ContextReportError(f"pct must be numeric, got {pct!r}: {e}")
    if not (0 <= pct_f <= 100):
        raise ContextReportError(
            f"pct must be in [0, 100], got {pct_f}"
        )
    entry = {
        "ts": datetime.now().isoformat(),
        "session": session_number,
        "context_pct": pct_f,
        "note": note,
        "pid": os.getpid(),
    }
    _append_jsonl(CONTEXT_LOG, entry)
    log.info("preflight: context %.0f%% recorded for session %s",
             pct_f, session_number)
    return entry


def last_session_context(skip_current_pid: bool = True) -> Optional[dict]:
    """Return the most recent context entry, optionally skipping the
    current process so handoff writers can check the *prior* session."""
    entries = _read_jsonl(CONTEXT_LOG)
    if not entries:
        return None
    if skip_current_pid:
        my_pid = os.getpid()
        entries = [e for e in entries if e.get("pid") != my_pid]
    return entries[-1] if entries else None


# -------------------------------------------------------------------
# Rule 9 -- no blocker claim without tool-grep
# -------------------------------------------------------------------

def claim_blocked(
    reason: str,
    verbs: list[str],
    searched: list[tuple[str, str]],
    session_number: Optional[int] = None,
) -> dict:
    """Validate that a blocker claim was preceded by sufficient grep.

    Args:
        reason: The blocker statement about to be written.
        verbs: Action-verbs the user could plausibly want done.
        searched: List of (tool_name, query) pairs already executed.

    Raises:
        BlockerClaimWithoutGrepError if `searched` does not cover every
        verb at least once. Coverage is keyword-substring: a search
        query covers a verb if the verb (lowercased) appears in the
        query (lowercased).
    """
    if not verbs:
        raise BlockerClaimWithoutGrepError(
            "claim_blocked called with empty verbs list — "
            "you must name what you tried to do"
        )
    if not searched:
        raise BlockerClaimWithoutGrepError(
            f"claim_blocked('{reason}') called with no searches. "
            f"Run ToolSearch + Get-Command for verbs {verbs} first."
        )
    uncovered: list[str] = []
    joined = " ".join(q.lower() for _, q in searched)
    for v in verbs:
        if v.lower() not in joined:
            uncovered.append(v)
    entry = {
        "ts": datetime.now().isoformat(),
        "session": session_number,
        "reason": reason,
        "verbs": verbs,
        "searched": [list(s) for s in searched],
        "uncovered": uncovered,
        "valid": not uncovered,
    }
    _append_jsonl(BLOCKER_LOG, entry)
    if uncovered:
        raise BlockerClaimWithoutGrepError(
            f"claim_blocked('{reason}'): verbs not covered by any "
            f"search: {uncovered}. Run those greps first, then retry."
        )
    log.info("preflight: blocker claim '%s' validated (%d searches)",
             reason, len(searched))
    return entry


# -------------------------------------------------------------------
# Combined session-start helper
# -------------------------------------------------------------------

def assert_session_start(
    session_number: int,
    context_pct: int | float,
    note: str = "",
) -> dict:
    """Run Check 1 + return enough info for the handoff to embed.

    Does NOT raise if the prior session failed to report — only warns —
    because raising would block the current session from writing its
    own remediation. The warning lands in the returned dict so the
    handoff template can surface it.
    """
    entry = report_context(context_pct, session_number=session_number, note=note)
    prior = last_session_context(skip_current_pid=True)
    warnings: list[str] = []
    if prior is None:
        warnings.append(
            "no prior context entries — first session under Rule 8"
        )
    elif prior.get("session") not in (None, session_number - 1):
        warnings.append(
            f"prior context entry is from session {prior.get('session')}, "
            f"expected {session_number - 1} — possible skipped report"
        )
    return {
        "session": session_number,
        "context_pct": entry["context_pct"],
        "prior": prior,
        "warnings": warnings,
        "context_log": str(CONTEXT_LOG),
        "blocker_log": str(BLOCKER_LOG),
    }


if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "report":
        print(json.dumps(report_context(float(sys.argv[2])), indent=2))
    elif len(sys.argv) >= 2 and sys.argv[1] == "last":
        print(json.dumps(last_session_context(False), indent=2))
    else:
        print("usage: preflight.py report <pct> | last")
