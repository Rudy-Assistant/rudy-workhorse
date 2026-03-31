"""Alfred-Robin Collaboration Protocol -- Orchestrates handoffs between Alfred and Robin.

Two collaboration modes:

Mode 1 -- Timed Absence:
    Batman signals departure with directive + time budget.
    Alfred writes the directive via DirectiveTracker.create_directive(),
    delegates work to Robin via alfred_delegate.py, monitors progress,
    handles checkpoints, and prepares a summary when Batman returns.

Mode 2 -- Indefinite Handoff:
    Alfred detects 5-minute inactivity OR Batman says "Robin, take over".
    Alfred writes a long-duration directive with no practical expiry.
    Robin enters INITIATIVE MODE from robin_autonomy.py and reads the room
    via SituationalAwareness. Robin never idles -- always improving the
    Batcave.

Integration:
    Alfred (Cowork) -> alfred_robin_protocol.py
        -> DirectiveTracker (robin_autonomy.py) for directive state
        -> alfred_delegate.py -> broker -> bridge_runner.py -> Robin taskqueue
        -> AlfredMailbox / RobinMailbox (robin_alfred_protocol.py) for inbox msgs

Lucius Gate: LG-031 - No new dependencies. Composes existing modules only.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from rudy.paths import RUDY_DATA, RUDY_LOGS
from rudy.robin_autonomy import DirectiveTracker, SituationalAwareness
from rudy.robin_alfred_protocol import AlfredMailbox
from rudy.alfred_delegate import (
    delegate_and_wait,
    delegate_fire_and_forget,
    check_bridge_health,
)

log = logging.getLogger("alfred_robin_protocol")

# Paths
COORD_DIR = RUDY_DATA / "coordination"
HANDOFF_LOG = RUDY_LOGS / "alfred-robin-handoffs.json"
INACTIVITY_FILE = COORD_DIR / "alfred-last-activity.json"
COORD_DIR.mkdir(parents=True, exist_ok=True)

# Defaults
DEFAULT_TIMED_HOURS = 2.0
DEFAULT_INDEFINITE_HOURS = 168.0  # 1 week -- effectively indefinite
INACTIVITY_THRESHOLD_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Handoff Journal -- persistent record of all Alfred<->Robin handoffs
# ---------------------------------------------------------------------------

def _load_handoff_log() -> list:
    if HANDOFF_LOG.exists():
        try:
            return json.loads(HANDOFF_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_handoff_log(entries: list) -> None:
    HANDOFF_LOG.write_text(
        json.dumps(entries[-200:], indent=2, default=str),
        encoding="utf-8",
    )


def _record_handoff(direction: str, mode: str, details: dict) -> None:
    """Append a handoff event to the persistent log."""
    entries = _load_handoff_log()
    entries.append({
        "timestamp": datetime.now().isoformat(),
        "direction": direction,  # "alfred_to_robin" or "robin_to_alfred"
        "mode": mode,            # "timed_absence" or "indefinite_handoff"
        "details": details,
    })
    _save_handoff_log(entries)


# ---------------------------------------------------------------------------
# Activity Tracker -- detects Batman inactivity for Mode 2
# ---------------------------------------------------------------------------

class ActivityTracker:
    """Tracks Batman's last interaction to detect inactivity."""

    def __init__(self):
        self._file = INACTIVITY_FILE

    def touch(self) -> None:
        """Record that Batman just interacted (call on every user message)."""
        self._file.write_text(json.dumps({
            "last_activity": datetime.now().isoformat(),
            "pid": __import__("os").getpid(),
        }), encoding="utf-8")

    def seconds_since_activity(self) -> float:
        """Seconds since the last recorded activity. Returns inf if no file."""
        if not self._file.exists():
            return float("inf")
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            last = datetime.fromisoformat(data["last_activity"])
            return (datetime.now() - last).total_seconds()
        except Exception:
            return float("inf")

    def is_inactive(self, threshold: float = INACTIVITY_THRESHOLD_SECONDS) -> bool:
        return self.seconds_since_activity() > threshold


# ---------------------------------------------------------------------------
# Mode 1: Timed Absence Handoff (Alfred -> Robin)
# ---------------------------------------------------------------------------

class TimedAbsenceHandoff:
    """Orchestrates Mode 1: Batman leaves with a directive and time budget.

    Workflow:
        1. Alfred creates a directive via DirectiveTracker
        2. Alfred notifies Robin via the mailbox protocol
        3. Alfred delegates initial work via the bridge
        4. Alfred monitors progress and checkpoints
        5. When Batman returns (or timer expires), Alfred summarizes
    """

    def __init__(self, session_id: str = "", session_number: int = 0):
        self.mailbox = AlfredMailbox(
            session_id=session_id, session_number=session_number
        )
        self.tracker = DirectiveTracker()

    def initiate(
        self,
        directive_text: str,
        hours: float = DEFAULT_TIMED_HOURS,
        checkpoints: list = None,
        initial_tasks: list = None,
    ) -> dict:
        """Batman is leaving. Set up the directive and delegate to Robin.

        Args:
            directive_text: What Batman wants done (natural language).
            hours: Time budget in hours.
            checkpoints: Optional list of checkpoint dicts
                         [{"at_pct": 25, "note": "..."}, ...].
            initial_tasks: Optional list of tasks to delegate immediately.
                           Each is a dict: {"type": "...", "title": "...", ...}.

        Returns:
            dict with directive details and delegation results.
        """
        # 1. Create the directive
        directive = DirectiveTracker.create_directive(
            directive_text, hours, checkpoints
        )
        log.info(
            "Timed absence initiated: '%s' (%.1fh budget)",
            directive_text[:80], hours,
        )

        # 2. Notify Robin via mailbox
        self.mailbox.respond_to_robin("directive", {
            "directive": directive_text,
            "mode": "timed_absence",
            "hours": hours,
            "expires_at": directive["expires_at"],
            "checkpoints": directive.get("checkpoints", []),
        })

        # 3. Verify bridge health before delegating
        bridge = check_bridge_health()
        if not bridge.get("healthy"):
            log.warning("Bridge unhealthy at handoff: %s", bridge)

        # 4. Delegate initial tasks (if any)
        delegation_results = []
        for task in (initial_tasks or []):
            task_type = task.get("type", "shell")
            title = task.get("title", f"Directive task: {task_type}")
            result = delegate_and_wait(
                task_type=task_type,
                title=title,
                description=task.get("description", directive_text),
                command=task.get("command"),
                priority=task.get("priority", 30),
                timeout_seconds=task.get("timeout", 120),
            )
            delegation_results.append({"task": task, "result": result})

        # 5. Record handoff
        handoff_record = {
            "directive": directive_text,
            "hours": hours,
            "expires_at": directive["expires_at"],
            "bridge_healthy": bridge.get("healthy", False),
            "initial_tasks_count": len(initial_tasks or []),
            "initial_results": delegation_results,
        }
        _record_handoff("alfred_to_robin", "timed_absence", handoff_record)

        return {
            "success": True,
            "directive": directive,
            "bridge_health": bridge,
            "delegations": delegation_results,
        }

    def check_progress(self) -> dict:
        """Check how the directive is progressing (call periodically)."""
        self.tracker = DirectiveTracker()  # reload
        if not self.tracker.has_active_directive():
            return {"active": False, "status": "no_active_directive"}

        directive = self.tracker.get_directive()
        pct = self.tracker.get_progress_pct()
        remaining = self.tracker.get_time_remaining()
        checkpoint = self.tracker.get_current_checkpoint()

        # Check Robin's inbox for reports
        robin_reports = []
        alfred_inbox = self.mailbox.check_inbox()
        for msg in alfred_inbox:
            if msg.get("type") in ("report", "task_complete", "finding"):
                robin_reports.append(msg)

        return {
            "active": True,
            "directive": directive.get("directive", ""),
            "progress_pct": round(pct, 1),
            "time_remaining": str(remaining).split(".")[0] if remaining else None,
            "checkpoint_due": checkpoint,
            "robin_reports": robin_reports,
            "progress_entries": directive.get("progress", []),
        }

    def handle_checkpoint(self, summary: str) -> None:
        """Record a checkpoint and notify Robin."""
        checkpoint = self.tracker.get_current_checkpoint()
        if checkpoint:
            pct = checkpoint["at_pct"]
            self.tracker.record_progress(pct, summary)
            self.mailbox.respond_to_robin("checkpoint", {
                "checkpoint_pct": pct,
                "summary": summary,
                "next_checkpoint": self.tracker.get_current_checkpoint(),
            })

    def batman_returns(self) -> dict:
        """Batman is back. Summarize what happened and close the directive.

        Returns a summary dict with all progress, reports, and status.
        """
        self.tracker = DirectiveTracker()  # reload
        directive = self.tracker.get_directive()

        # Gather Robin's reports from inbox
        robin_reports = []
        alfred_inbox = self.mailbox.check_inbox()
        for msg in alfred_inbox:
            robin_reports.append({
                "type": msg.get("type"),
                "timestamp": msg.get("timestamp"),
                "payload": msg.get("payload", {}),
            })
            self.mailbox.mark_read(msg.get("id", ""))

        summary = {
            "directive": directive.get("directive", "unknown") if directive else "none",
            "status": "completed" if not directive else directive.get("status", "unknown"),
            "progress_entries": directive.get("progress", []) if directive else [],
            "robin_reports": robin_reports,
            "bridge_health": check_bridge_health(),
        }

        # Close the directive
        if directive:
            directive["status"] = "completed_batman_returned"
            directive["completed_at"] = datetime.now().isoformat()
            from rudy.paths import RUDY_DATA
            directive_file = RUDY_DATA / "coordination" / "active-directive.json"
            directive_file.write_text(
                json.dumps(directive, indent=2), encoding="utf-8"
            )

        # Notify Robin that Alfred is back in control
        self.mailbox.respond_to_robin("session_start", {
            "note": "Batman has returned. Alfred resuming control.",
            "directive_closed": True,
        })

        _record_handoff("robin_to_alfred", "batman_returned", {
            "reports_count": len(robin_reports),
            "directive": summary["directive"],
        })

        log.info(
            "Batman returned. Directive closed. %d Robin reports collected.",
            len(robin_reports),
        )
        return summary


# ---------------------------------------------------------------------------
# Mode 2: Indefinite Handoff (Alfred -> Robin, Robin takes initiative)
# ---------------------------------------------------------------------------

class IndefiniteHandoff:
    """Orchestrates Mode 2: Robin takes over when Batman is away indefinitely.

    Triggered by:
        - Batman explicitly says "Robin, take over"
        - Alfred detects 5-minute inactivity

    Robin enters INITIATIVE MODE and continuously improves the system.
    Alfred writes a long-duration directive so Robin's AutonomyEngine
    picks it up in DIRECTIVE MODE first, then transitions to INITIATIVE
    when the directive work is done.
    """

    def __init__(self, session_id: str = "", session_number: int = 0):
        self.mailbox = AlfredMailbox(
            session_id=session_id, session_number=session_number
        )

    def initiate(
        self,
        context: str = "",
        priorities: list = None,
        hours: float = DEFAULT_INDEFINITE_HOURS,
    ) -> dict:
        """Hand control to Robin indefinitely.

        Args:
            context: Current state summary for Robin.
            priorities: Ordered list of things Robin should focus on.
            hours: Nominal time budget (default 168h = 1 week).

        Returns:
            dict with handoff confirmation.
        """
        # Build a directive that captures the full context
        priority_text = ""
        if priorities:
            priority_text = "\nPriorities (ordered):\n" + "\n".join(
                f"  {i+1}. {p}" for i, p in enumerate(priorities)
            )

        directive_text = (
            f"Indefinite handoff from Alfred. Batman is away.\n"
            f"Context: {context or 'No specific context provided.'}\n"
            f"{priority_text}\n\n"
            f"When directive work is complete, enter INITIATIVE MODE.\n"
            f"KEY PRINCIPLE: Never idle. Always improve the Batcave.\n"
            f"Priority order: fix findings > run audits > update docs > "
            f"test systems > research tools > prepare next Alfred session."
        )

        # Create directive with generous time budget
        directive = DirectiveTracker.create_directive(directive_text, hours)

        # Notify Robin
        self.mailbox.respond_to_robin("directive", {
            "directive": directive_text,
            "mode": "indefinite_handoff",
            "hours": hours,
            "priorities": priorities or [],
            "context": context,
        })

        # Also send a session_end to signal Alfred is going offline
        self.mailbox.announce_session_end(
            summary=f"Indefinite handoff to Robin. Context: {context[:200]}",
            next_priorities=priorities,
        )

        # Verify bridge
        bridge = check_bridge_health()

        handoff_record = {
            "context": context[:500],
            "priorities": priorities or [],
            "hours": hours,
            "bridge_healthy": bridge.get("healthy", False),
        }
        _record_handoff("alfred_to_robin", "indefinite_handoff", handoff_record)

        log.info("Indefinite handoff to Robin. Priorities: %s", priorities)

        return {
            "success": True,
            "directive": directive,
            "bridge_health": bridge,
            "mode": "indefinite_handoff",
        }

    def robin_returns_control(self, reason: str = "alfred_session_start") -> dict:
        """Robin hands control back to Alfred (e.g., new Cowork session starts).

        Args:
            reason: Why control is returning.

        Returns:
            Summary of what Robin did while in control.
        """
        # Gather situation from Robin's perspective
        sit = SituationalAwareness()
        state = sit.gather()

        # Read Robin reports from inbox
        mailbox = AlfredMailbox()
        robin_reports = []
        for msg in mailbox.check_inbox():
            robin_reports.append({
                "type": msg.get("type"),
                "timestamp": msg.get("timestamp"),
                "payload": msg.get("payload", {}),
            })
            mailbox.mark_read(msg.get("id", ""))

        # Close any active directive
        tracker = DirectiveTracker()
        directive = tracker.get_directive()
        if directive:
            directive["status"] = "superseded_by_alfred"
            directive["completed_at"] = datetime.now().isoformat()
            directive_file = RUDY_DATA / "coordination" / "active-directive.json"
            directive_file.write_text(
                json.dumps(directive, indent=2), encoding="utf-8"
            )

        _record_handoff("robin_to_alfred", reason, {
            "reports_count": len(robin_reports),
            "signals": list(state.get("signals", {}).keys()),
        })

        log.info("Robin returning control to Alfred. %d reports.", len(robin_reports))

        return {
            "robin_reports": robin_reports,
            "situational_awareness": state,
            "directive_was_active": directive is not None,
            "reason": reason,
        }


# ---------------------------------------------------------------------------
# Inactivity Monitor -- polls for Mode 2 trigger
# ---------------------------------------------------------------------------

class InactivityMonitor:
    """Monitors Batman's activity and triggers Mode 2 handoff if idle.

    Call check() periodically. If Batman is inactive for > threshold,
    it returns a recommendation to initiate indefinite handoff.
    """

    def __init__(self, threshold_seconds: float = INACTIVITY_THRESHOLD_SECONDS):
        self.threshold = threshold_seconds
        self.activity = ActivityTracker()
        self._handoff_triggered = False

    def record_activity(self) -> None:
        """Call whenever Batman interacts."""
        self.activity.touch()
        self._handoff_triggered = False  # reset on new activity

    def check(self) -> dict:
        """Check if we should hand off to Robin.

        Returns:
            {"should_handoff": bool, "idle_seconds": float, ...}
        """
        idle = self.activity.seconds_since_activity()

        if idle > self.threshold and not self._handoff_triggered:
            self._handoff_triggered = True
            return {
                "should_handoff": True,
                "idle_seconds": round(idle, 1),
                "recommendation": "initiate_indefinite_handoff",
            }

        return {
            "should_handoff": False,
            "idle_seconds": round(idle, 1),
        }


# ---------------------------------------------------------------------------
# Delegation Helpers -- new task type: "directive"
# ---------------------------------------------------------------------------

def delegate_directive(
    directive_text: str,
    mode: str = "timed_absence",
    hours: float = DEFAULT_TIMED_HOURS,
    priority: int = 20,
    timeout_seconds: int = 30,
) -> Optional[str]:
    """Delegate a directive payload to Robin via the bridge.

    This adds a new task type 'directive' to the delegation pipeline.
    Robin's bridge_runner should recognize this type and activate the
    AutonomyEngine in DIRECTIVE MODE.

    Args:
        directive_text: The directive content.
        mode: "timed_absence" or "indefinite_handoff".
        hours: Time budget.
        priority: Delegation priority (lower = higher).
        timeout_seconds: How long to wait for acknowledgment.

    Returns:
        Delegation ID on success, None on failure.
    """
    description = json.dumps({
        "directive": directive_text,
        "mode": mode,
        "hours": hours,
        "created_at": datetime.now().isoformat(),
    })

    return delegate_fire_and_forget(
        task_type="directive",
        title=f"Directive ({mode}): {directive_text[:60]}",
        description=description,
        priority=priority,
    )


# ---------------------------------------------------------------------------
# Convenience: Full handoff flows (call these from Alfred/Cowork)
# ---------------------------------------------------------------------------

def handoff_timed_absence(
    directive: str,
    hours: float = DEFAULT_TIMED_HOURS,
    session_id: str = "",
    session_number: int = 0,
    initial_tasks: list = None,
) -> dict:
    """One-call entry point for Mode 1 timed absence.

    Usage from Cowork:
        from rudy.alfred_robin_protocol import handoff_timed_absence
        result = handoff_timed_absence(
            "Run full security audit and fix critical findings",
            hours=2.0,
        )
    """
    handler = TimedAbsenceHandoff(session_id, session_number)
    return handler.initiate(directive, hours, initial_tasks=initial_tasks)


def handoff_indefinite(
    context: str = "",
    priorities: list = None,
    session_id: str = "",
    session_number: int = 0,
) -> dict:
    """One-call entry point for Mode 2 indefinite handoff.

    Usage from Cowork:
        from rudy.alfred_robin_protocol import handoff_indefinite
        result = handoff_indefinite(
            context="Session 30 complete. PR #56 merged.",
            priorities=["Fix Lucius findings", "Run audits", "Update docs"],
        )
    """
    handler = IndefiniteHandoff(session_id, session_number)
    return handler.initiate(context, priorities)


def alfred_resumes_control(session_id: str = "", session_number: int = 0) -> dict:
    """Call when a new Alfred/Cowork session starts to reclaim control.

    Reads Robin's reports, closes any active directive, and returns
    a briefing of what happened while Alfred was away.

    Usage from Cowork:
        from rudy.alfred_robin_protocol import alfred_resumes_control
        briefing = alfred_resumes_control(session_id="s31", session_number=31)
    """
    handler = IndefiniteHandoff(session_id, session_number)
    return handler.robin_returns_control(reason="alfred_session_start")


# ---------------------------------------------------------------------------
# CLI -- for testing and manual operation
# ---------------------------------------------------------------------------

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Alfred-Robin Collaboration Protocol"
    )
    sub = parser.add_subparsers(dest="command")

    # timed-absence
    p_timed = sub.add_parser("timed", help="Initiate timed absence handoff")
    p_timed.add_argument("directive", help="What to work on")
    p_timed.add_argument("--hours", type=float, default=DEFAULT_TIMED_HOURS)

    # indefinite
    p_indef = sub.add_parser("indefinite", help="Initiate indefinite handoff")
    p_indef.add_argument("--context", default="")
    p_indef.add_argument("--priorities", nargs="*", default=[])

    # resume
    sub.add_parser("resume", help="Alfred resumes control")

    # progress
    sub.add_parser("progress", help="Check directive progress")

    # status
    sub.add_parser("status", help="Show bridge and coordination status")

    args = parser.parse_args()

    if args.command == "timed":
        result = handoff_timed_absence(args.directive, args.hours)
        print(json.dumps(result, indent=2, default=str))
    elif args.command == "indefinite":
        result = handoff_indefinite(args.context, args.priorities)
        print(json.dumps(result, indent=2, default=str))
    elif args.command == "resume":
        result = alfred_resumes_control()
        print(json.dumps(result, indent=2, default=str))
    elif args.command == "progress":
        handler = TimedAbsenceHandoff()
        result = handler.check_progress()
        print(json.dumps(result, indent=2, default=str))
    elif args.command == "status":
        bridge = check_bridge_health()
        activity = ActivityTracker()
        print(json.dumps({
            "bridge": bridge,
            "idle_seconds": round(activity.seconds_since_activity(), 1),
            "handoff_log_entries": len(_load_handoff_log()),
        }, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
