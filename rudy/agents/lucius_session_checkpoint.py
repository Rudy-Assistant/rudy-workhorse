"""
Lucius Fox — Session Checkpoint (ADR-005 Phase 2b, S74).

Extracted from lucius_fox.py. Generates context evaluation lines per HARD RULE #5.
"""

import json

from datetime import datetime
from pathlib import Path


def session_checkpoint(
    session_number: int,
    context_pct: float,
    status: str = "",
    audit_dir: Path = None,
    log=None,
) -> str:
    """Generate and log a context evaluation line.

    HARD RULE #5: Every substantive Alfred response must end with a
    context evaluation line. This method formats it, logs it, and
    returns the string for Alfred to append to the response.

    Args:
        session_number: Current session number.
        context_pct: Estimated context window consumption (0-100).
        status: Brief status summary for the line.
        audit_dir: Path to write checkpoint JSONL (optional).
        log: Logger instance (optional).

    Returns:
        Formatted context evaluation string, ready to paste.
    """
    if context_pct >= 70:
        prefix = "HANDOFF REQUIRED"
    elif context_pct >= 50:
        prefix = "APPROACHING LIMIT"
    else:
        prefix = ""

    line = (
        f"[Context: ~{int(context_pct)}% | "
        f"Session {session_number} | {status}]"
    )
    if prefix:
        line = f"**{prefix}** -- {line}"

    if log:
        log.info(
            "Session checkpoint: %s%% context, session %s",
            context_pct,
            session_number,
        )

    # Write checkpoint to status file for post-session gate
    if audit_dir:
        try:
            checkpoint_file = audit_dir / "session-checkpoints.jsonl"
            entry = {
                "session": session_number,
                "context_pct": context_pct,
                "status": status,
                "timestamp": datetime.now().isoformat(),
            }
            with open(checkpoint_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            if log:
                log.warning("Failed to write checkpoint: %s", e)

    return line
