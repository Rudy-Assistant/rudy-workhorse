"""
rudy.workflows.session_gate -- Session start gate integration.

ADR-004 v2.1 Phase 1B: Wires session_start_gate() into the session
lifecycle so that new sessions are checked for critical MCP availability,
vault access, and repo root detection before work begins.

Entry points:
    - run_session_start_gate(): Called by Sentinel's session briefing
      generator or directly at session start. Returns GateResult.
    - format_gate_briefing(): Formats gate results for session-briefing.md.

Import Isolation (C3):
    All imports from rudy.agents.lucius_gate are inside function bodies.
    If lucius_gate is broken, this module degrades to a no-op that logs
    a warning rather than crashing the session.
"""

import json
import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("rudy.session_gate")


def run_session_start_gate(
    session_number: int = 0,
    mcp_tiers_path: Optional[str] = None,
) -> Optional[object]:
    """Run the session start gate and return the GateResult.

    This is the primary integration point. Sentinel calls this during
    session briefing generation. Can also be called directly at the
    start of a Cowork session.

    ADR-004 v2.1 behavior:
        - CRITICAL MCPs unavailable -> session blocked with clear error
        - IMPORTANT MCPs unavailable -> session starts degraded,
          relevant skills excluded from recommendations
        - Gate crash -> returns None (session starts ungated)

    Returns:
        GateResult if gate ran, None if gate could not be loaded.
    """
    try:
        from rudy.agents.lucius_gate import session_start_gate
    except ImportError as e:
        log.warning(f"lucius_gate import failed; session starting ungated: {e}")
        return None

    try:
        result = session_start_gate(
            session_number=session_number,
            mcp_tiers_path=mcp_tiers_path,
        )

        if result.passed and not result.degraded:
            log.info(f"Session start gate PASSED: {result.summary()}")
        elif result.degraded:
            log.warning(
                f"Session start gate DEGRADED: {result.summary()}. "
                "Session will start with reduced capabilities."
            )
        else:
            log.error(
                f"Session start gate BLOCKED: {result.summary()}. "
                "CRITICAL MCPs are unavailable."
            )

        # Write gate result to logs for Sentinel pickup
        _write_gate_log(result)

        return result

    except Exception as e:
        log.error(f"Session start gate crashed: {e}. Session starting ungated.")
        return None


def _write_gate_log(result) -> None:
    """Write gate result to rudy-logs/gate-results/ for audit trail.

    Import isolation: rudy.paths imported inside function body.
    """
    try:
        from rudy.paths import RUDY_LOGS
    except ImportError:
        log.debug("Could not import rudy.paths; skipping gate log write")
        return

    try:
        gate_log_dir = RUDY_LOGS / "gate-results"
        gate_log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        gate_name = "unknown"
        if result.metrics:
            gate_name = result.metrics.gate_name

        filename = f"{gate_name}-{timestamp}.json"
        filepath = gate_log_dir / filename

        data = result.to_dict()
        data["logged_at"] = datetime.now().isoformat()

        filepath.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        log.debug(f"Gate result logged to {filepath}")
    except Exception as e:
        log.debug(f"Could not write gate log: {e}")


def format_gate_briefing(result) -> str:
    """Format a GateResult into a section for session-briefing.md.

    Used by Sentinel's _generate_session_briefing() to include gate
    status in the briefing that Cowork sessions consume.

    Args:
        result: GateResult from run_session_start_gate(), or None.

    Returns:
        Markdown string suitable for inclusion in session-briefing.md.
    """
    if result is None:
        return (
            "## Session Gate\n\n"
            "**Status:** UNGATED (lucius_gate not available)\n\n"
            "The session start gate could not run. This may indicate that "
            "the lucius_gate module is not installed or has an import error. "
            "Proceed with caution.\n"
        )

    lines = [
        "## Session Gate",
        "",
        f"**Status:** {result.summary()}",
    ]

    if result.metrics:
        lines.append(f"**Elapsed:** {result.metrics.total_elapsed_sec:.3f}s")

    lines.append("")

    # List check results
    if result.checks:
        lines.append("| Check | State | Detail |")
        lines.append("|-------|-------|--------|")
        for c in result.checks:
            lines.append(f"| {c.name} | {c.state.value} | {c.detail} |")
        lines.append("")

    # Actionable warnings
    degraded_checks = [c for c in result.checks if c.state.value == "DEGRADED"]
    failed_checks = [c for c in result.checks if c.state.value == "FAIL"]

    if failed_checks:
        lines.append("### Blocked Checks")
        lines.append("")
        for c in failed_checks:
            lines.append(f"- **{c.name}**: {c.detail}")
        lines.append("")

    if degraded_checks:
        lines.append("### Degraded Checks")
        lines.append("")
        for c in degraded_checks:
            lines.append(f"- **{c.name}**: {c.detail}")
        lines.append("")

    return "\n".join(lines)


def get_unavailable_skills(result) -> list[str]:
    """Determine which Cowork skills should be excluded based on gate results.

    When IMPORTANT MCPs are unavailable, the skills that depend on them
    should be flagged so Alfred doesn't attempt to use broken tools.

    Returns:
        List of skill names that should be excluded or noted as degraded.
    """
    if result is None:
        return []

    # Mapping of MCP names to the skills they power
    mcp_skill_map = {
        "github": ["git-workflow", "code-review", "engineering:standup"],
        "gmail": ["email-composer", "meeting-assistant"],
        "google-calendar": ["meeting-assistant", "schedule"],
        "notion": ["productivity:task-management", "productivity:memory-management"],
        "chrome": ["browser-automate"],
        "desktop-commander": ["local-control", "system-health"],
    }

    unavailable = []
    for check in result.checks:
        if check.name.startswith("mcp_") and check.state.value != "PASS":
            mcp_name = check.name[4:]
            skills = mcp_skill_map.get(mcp_name, [])
            unavailable.extend(skills)

    return sorted(set(unavailable))
