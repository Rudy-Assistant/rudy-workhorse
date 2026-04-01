#!/usr/bin/env python3
"""
Robin <-> Alfred Coordination Protocol

Filesystem-based message passing for autonomous coordination between
Robin (local AI on Oracle) and Alfred (Claude in Cowork cloud sessions).

Protocol:
  Robin writes requests to:  rudy-data/alfred-inbox/{timestamp}-{type}.json
  Alfred reads inbox, processes, writes responses to: rudy-data/robin-inbox/{timestamp}-{type}.json
  Robin reads responses and acts on them.

  Both sides also share a status file:
    rudy-data/coordination/robin-status.json  -- Robin's current state
    rudy-data/coordination/alfred-status.json  -- Alfred's last-known state

Message Types:
  - "request"       : Robin asks Alfred for guidance or a cloud task
  - "report"        : Robin reports completed work or findings
  - "health"        : Periodic health check / status update
  - "escalation"    : Something Robin can't handle alone
  - "task"          : Alfred assigns work to Robin
  - "ack"           : Acknowledgment of received message
  - "task_ack"      : Robin acknowledges a delegated task (v2)
  - "task_complete" : Robin reports a specific task done with results (v2)
  - "finding"       : Robin reports a quality/security finding (v2)
  - "session_start" : Alfred announces session start with ID (v2)
  - "session_end"   : Alfred announces session end with summary (v2)

Usage (Robin side):
    from robin_alfred_protocol import RobinMailbox
    mailbox = RobinMailbox()
    mailbox.send_to_alfred("request", {
        "subject": "Need cloud API access for weather data",
        "details": "Batman asked for a weather dashboard...",
        "priority": "normal"
    })

    # Check for Alfred's responses
    messages = mailbox.check_inbox()
    for msg in messages:
        print(f"Alfred says: {msg['payload']}")
        mailbox.mark_read(msg['id'])
"""

import json
import os
import time
from datetime import datetime
from typing import Optional

# Shared sanitization (canonical: rudy/sanitize.py)
from rudy.sanitize import sanitize_str as _sanitize_str
from rudy.sanitize import validate_payload as _validate_payload
from rudy.sanitize import MAX_MESSAGE_AGE_HOURS


# Canonical paths
from rudy.paths import RUDY_DATA, ROBIN_INBOX  # noqa: E402

COORD_DIR = RUDY_DATA / "coordination"
ALFRED_INBOX = RUDY_DATA / "alfred-inbox"
ARCHIVE_DIR = COORD_DIR / "archive"

# Ensure directories exist
for d in [COORD_DIR, ALFRED_INBOX, ROBIN_INBOX, ARCHIVE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class RobinMailbox:
    """Robin's side of the coordination protocol."""

    def __init__(self):
        self.status_file = COORD_DIR / "robin-status.json"
        self._update_status("online")

    def _update_status(self, state: str, details: str = ""):
        """Update Robin's status file."""
        status = {
            "state": state,
            "updated_at": datetime.now().isoformat(),
            "pid": os.getpid(),
            "model": self._get_model(),
            "details": details,
        }
        with open(self.status_file, "w") as f:
            json.dump(status, f, indent=2)

    def _get_model(self) -> str:
        """Read current model from config."""
        try:
            with open(RUDY_DATA / "robin-secrets.json") as f:
                return json.load(f).get("ollama_model", "unknown")
        except Exception:
            return "unknown"

    def send_to_alfred(self, msg_type: str, payload: dict, priority: str = "normal") -> str:
        """
        Send a message to Alfred's inbox.
        Returns the message ID.
        """
        # Validate inputs (Protocol Salvage fix)
        msg_type = _sanitize_str(msg_type, max_length=50)
        priority = _sanitize_str(priority, max_length=20)
        payload = _validate_payload(payload)
        msg_id = f"{int(time.time())}-{msg_type}"
        message = {
            "id": msg_id,
            "from": "robin",
            "to": "alfred",
            "type": msg_type,
            "priority": priority,
            "timestamp": datetime.now().isoformat(),
            "payload": payload,
            "status": "unread",
        }
        filepath = ALFRED_INBOX / f"{msg_id}.json"
        with open(filepath, "w") as f:
            json.dump(message, f, indent=2)
        return msg_id

    def check_inbox(self) -> list:
        """Check Robin's inbox for messages from Alfred."""
        messages = []
        for f in sorted(ROBIN_INBOX.glob("*.json")):
            try:
                with open(f) as fh:
                    msg = json.load(fh)
                if msg.get("status") == "unread":
                    # TTL check — skip expired messages (Protocol Salvage fix)
                    msg_ts = msg.get("timestamp", "")
                    if msg_ts:
                        try:
                            age = (datetime.now() - datetime.fromisoformat(msg_ts)).total_seconds()
                            if age > MAX_MESSAGE_AGE_HOURS * 3600:
                                continue  # Message expired
                        except (ValueError, TypeError):
                            pass
                    messages.append(msg)
            except (json.JSONDecodeError, OSError):
                continue
        return messages

    def mark_read(self, msg_id: str):
        """Mark a message as read and archive it."""
        for f in ROBIN_INBOX.glob(f"{msg_id}*.json"):
            try:
                with open(f) as fh:
                    msg = json.load(fh)
                msg["status"] = "read"
                msg["read_at"] = datetime.now().isoformat()
                # Archive
                archive_path = ARCHIVE_DIR / f.name
                with open(archive_path, "w") as fh:
                    json.dump(msg, fh, indent=2)
                f.unlink()
            except Exception:
                continue

    def get_alfred_status(self) -> Optional[dict]:
        """Check Alfred's last known status."""
        status_file = COORD_DIR / "alfred-status.json"
        try:
            with open(status_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def request_help(self, subject: str, details: str, priority: str = "normal") -> str:
        """Convenience: send a help request to Alfred."""
        return self.send_to_alfred("request", {
            "subject": subject,
            "details": details,
        }, priority=priority)

    def report_work(self, subject: str, summary: str, files_changed: list = None) -> str:
        """Convenience: report completed work to Alfred."""
        return self.send_to_alfred("report", {
            "subject": subject,
            "summary": summary,
            "files_changed": files_changed or [],
        })

    def escalate(self, issue: str, context: str, severity: str = "medium") -> str:
        """Convenience: escalate an issue to Alfred."""
        return self.send_to_alfred("escalation", {
            "issue": issue,
            "context": context,
            "severity": severity,
        }, priority="high")

    def acknowledge_task(self, task_msg_id: str, eta_minutes: int = 0) -> str:
        """Acknowledge receipt of a delegated task from Alfred.

        Robin should call this immediately upon receiving a task message,
        so Alfred knows the task was received and Robin is working on it.

        Args:
            task_msg_id: The message ID of the task being acknowledged
            eta_minutes: Estimated time to completion (0 = unknown)
        """
        return self.send_to_alfred("task_ack", {
            "task_id": task_msg_id,
            "acknowledged_at": datetime.now().isoformat(),
            "eta_minutes": eta_minutes,
            "status": "in_progress",
        }, priority="normal")

    def report_task_complete(self, task_msg_id: str, result: str,
                             files_changed: list = None,
                             success: bool = True) -> str:
        """Report completion of a delegated task.

        Args:
            task_msg_id: The original task message ID
            result: Human-readable summary of what was done
            files_changed: List of files modified
            success: Whether the task completed successfully
        """
        return self.send_to_alfred("task_complete", {
            "task_id": task_msg_id,
            "completed_at": datetime.now().isoformat(),
            "success": success,
            "result": result,
            "files_changed": files_changed or [],
        }, priority="normal")

    def report_finding(self, title: str, severity: str, detail: str,
                       source: str = "robin") -> str:
        """Report a quality or security finding to Alfred.

        Robin should report findings discovered during nightwatch or
        autonomous operations so Alfred can track and act on them.
        """
        return self.send_to_alfred("finding", {
            "title": title,
            "severity": severity,
            "detail": detail,
            "source": source,
            "discovered_at": datetime.now().isoformat(),
        }, priority="high" if severity == "high" else "normal")


    def offer_help(self, context: str, what_noticed: str, suggested_action: str = "") -> str:
        """Proactively offer help to Alfred when Robin notices struggle.

        Session 33 directive: Robin should be assertive about offering help.
        Don't wait to be asked -- if you notice Alfred struggling, speak up.

        Triggers for offering help:
            - Alfred's status shows repeated errors
            - Alfred is doing local I/O that Robin should handle
            - A delegation failed and Alfred hasn't retried
            - Alfred has been idle for a while (possible stuck)

        Args:
            context: What Robin was doing when it noticed the issue.
            what_noticed: What signal triggered the offer (e.g., "Alfred running local git ops").
            suggested_action: What Robin proposes to do about it.

        Returns:
            Message ID of the help offer.
        """
        return self.send_to_alfred("help_offer", {
            "context": context,
            "what_noticed": what_noticed,
            "suggested_action": suggested_action or "Let me handle this -- it's a local task.",
            "robin_capabilities": [
                "filesystem scans", "git operations", "npm/node tasks",
                "health checks", "security scans", "shell commands",
                "port checks", "service management",
            ],
            "note": "Robin is offering help proactively. Accept or redirect.",
        }, priority="normal")

    def log_friction(self, context: str, what_went_wrong: str,
                     workaround: str = "", severity: str = "low") -> str:
        """Log a friction point for system improvement.

        Session 33 directive: Robin should document friction points
        whenever something doesn't work smoothly. These feed into
        system improvement prioritization.

        Args:
            context: What Robin was trying to do.
            what_went_wrong: Description of the friction.
            workaround: How Robin worked around it (if applicable).
            severity: low/medium/high -- how much this slowed things down.

        Returns:
            Message ID of the friction report.
        """
        import json
        from datetime import datetime
        from rudy.paths import RUDY_DATA

        # Persist locally
        friction_file = RUDY_DATA / "coordination" / "friction-log.json"
        existing = []
        if friction_file.exists():
            try:
                existing = json.loads(friction_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        entry = {
            "timestamp": datetime.now().isoformat(),
            "source": "robin",
            "context": context,
            "friction": what_went_wrong,
            "workaround": workaround,
            "severity": severity,
        }
        existing.append(entry)
        friction_file.write_text(
            json.dumps(existing[-100:], indent=2, default=str),
            encoding="utf-8",
        )

        # Also send to Alfred for awareness
        return self.send_to_alfred("friction_report", {
            **entry,
            "note": "Robin logged this friction point. Consider addressing in next session.",
        }, priority="normal" if severity == "low" else "high")

    def remind_alfred_to_document(self, what_happened: str) -> str:
        """Remind Alfred to document a friction point or finding.

        Session 33 directive: Robin should remind Alfred when it notices
        Alfred encountered something worth documenting but didn't log it.

        Args:
            what_happened: Description of what Alfred should document.

        Returns:
            Message ID of the reminder.
        """
        return self.send_to_alfred("documentation_reminder", {
            "what_happened": what_happened,
            "suggestion": "Please log this as a friction point or finding for improvement.",
            "note": "Robin noticed this should be documented. Filing as a reminder.",
        }, priority="normal")

    def detect_alfred_struggle(self) -> dict:
        """Check Alfred's status for signs of struggle.

        Returns a dict with:
            - struggling: bool
            - signals: list of detected struggle signals
            - recommendation: what Robin should do

        Robin should call this periodically (e.g., every heartbeat cycle)
        and call offer_help() if struggling is True.
        """
        alfred_status = self.get_alfred_status()
        if not alfred_status:
            return {"struggling": False, "signals": ["Alfred status unavailable"], "recommendation": "wait"}

        signals = []
        state = alfred_status.get("state", "unknown")
        details = alfred_status.get("details", "")
        updated = alfred_status.get("updated_at", "")

        # Signal: Alfred has been offline for a while
        if state == "offline":
            signals.append("Alfred is offline")

        # Signal: Alfred's details mention errors
        error_keywords = ["error", "fail", "timeout", "blocked", "stuck", "retry"]
        if any(kw in details.lower() for kw in error_keywords):
            signals.append(f"Alfred status mentions issues: {details[:100]}")

        # Signal: Alfred status is stale (>10 minutes old)
        if updated:
            try:
                from datetime import datetime
                last_update = datetime.fromisoformat(updated)
                age_seconds = (datetime.now() - last_update).total_seconds()
                if age_seconds > 600:
                    signals.append(f"Alfred status is stale ({age_seconds:.0f}s old)")
            except (ValueError, TypeError):
                pass

        struggling = len(signals) > 0
        recommendation = "offer_help" if struggling else "standby"

        return {
            "struggling": struggling,
            "signals": signals,
            "recommendation": recommendation,
            "alfred_state": state,
        }

    def send_health(self):
        """Send a periodic health update to Alfred."""
        try:
            import psutil
            health = {
                "cpu_pct": psutil.cpu_percent(interval=0.5),
                "ram_pct": psutil.virtual_memory().percent,
                "disk_free_gb": round(psutil.disk_usage("C:\\").free / (1024**3), 1),
            }
        except ImportError:
            health = {"note": "psutil not available"}

        return self.send_to_alfred("health", {
            "model": self._get_model(),
            "nightwatch_pid": os.getpid(),
            "system": health,
        })


class AlfredMailbox:
    """
    Alfred's side of the coordination protocol.
    Used by Alfred (Claude) when reading Robin's messages and responding.

    v2 additions:
      - Session awareness: tracks session_id and start_time
      - Session lifecycle messages (session_start, session_end)
      - Finding reporting for quality gate integration
    """

    def __init__(self, session_id: str = "", session_number: int = 0):
        self.status_file = COORD_DIR / "alfred-status.json"
        self.session_id = session_id or f"cowork-{int(time.time())}"
        self.session_number = session_number
        self.session_start = datetime.now()

    def update_status(self, state: str, details: str = ""):
        """Update Alfred's status file with session context."""
        status = {
            "state": state,
            "updated_at": datetime.now().isoformat(),
            "session_id": self.session_id,
            "session_number": self.session_number,
            "session_start": self.session_start.isoformat(),
            "uptime_minutes": round(
                (datetime.now() - self.session_start).total_seconds() / 60, 1
            ),
            "details": details,
        }
        with open(self.status_file, "w") as f:
            json.dump(status, f, indent=2)

    def check_inbox(self) -> list:
        """Check Alfred's inbox for messages from Robin."""
        messages = []
        for f in sorted(ALFRED_INBOX.glob("*.json")):
            try:
                with open(f) as fh:
                    msg = json.load(fh)
                if msg.get("status") == "unread":
                    # TTL check — skip expired messages (Protocol Salvage fix)
                    msg_ts = msg.get("timestamp", "")
                    if msg_ts:
                        try:
                            age = (datetime.now() - datetime.fromisoformat(msg_ts)).total_seconds()
                            if age > MAX_MESSAGE_AGE_HOURS * 3600:
                                continue  # Message expired
                        except (ValueError, TypeError):
                            pass
                    messages.append(msg)
            except (json.JSONDecodeError, OSError):
                continue
        return messages

    def respond_to_robin(self, msg_type: str, payload: dict, in_reply_to: str = "") -> str:
        """Send a response to Robin's inbox."""
        # Validate inputs (Protocol Salvage fix)
        msg_type = _sanitize_str(msg_type, max_length=50)
        payload = _validate_payload(payload)
        msg_id = f"{int(time.time())}-{msg_type}"
        message = {
            "id": msg_id,
            "from": "alfred",
            "to": "robin",
            "type": msg_type,
            "in_reply_to": in_reply_to,
            "timestamp": datetime.now().isoformat(),
            "payload": payload,
            "status": "unread",
        }
        filepath = ROBIN_INBOX / f"{msg_id}.json"
        with open(filepath, "w") as f:
            json.dump(message, f, indent=2)
        return msg_id

    def assign_task(self, task: str, details: str, deadline: str = "") -> str:
        """Assign a task to Robin."""
        return self.respond_to_robin("task", {
            "task": task,
            "details": details,
            "deadline": deadline,
        })

    def acknowledge(self, original_msg_id: str, note: str = "Received") -> str:
        """Acknowledge a message from Robin."""
        return self.respond_to_robin("ack", {
            "note": note,
        }, in_reply_to=original_msg_id)

    def announce_session_start(self, priorities: list = None) -> str:
        """Announce session start so Robin knows Alfred is online.

        Args:
            priorities: List of session priority strings (e.g. ["P0: CI", "P1: Protocol"])
        """
        self.update_status("online", f"Session {self.session_number} started")
        return self.respond_to_robin("session_start", {
            "session_id": self.session_id,
            "session_number": self.session_number,
            "started_at": self.session_start.isoformat(),
            "priorities": priorities or [],
        })

    def announce_session_end(self, summary: str, prs_merged: list = None,
                             next_priorities: list = None) -> str:
        """Announce session end with summary for Robin's awareness.

        Args:
            summary: Human-readable session summary
            prs_merged: List of PR numbers merged this session
            next_priorities: Priorities for next session
        """
        self.update_status("offline", f"Session {self.session_number} ended")
        return self.respond_to_robin("session_end", {
            "session_id": self.session_id,
            "session_number": self.session_number,
            "ended_at": datetime.now().isoformat(),
            "duration_minutes": round(
                (datetime.now() - self.session_start).total_seconds() / 60, 1
            ),
            "summary": summary,
            "prs_merged": prs_merged or [],
            "next_priorities": next_priorities or [],
        })

    def report_finding(self, title: str, severity: str, detail: str,
                       source: str = "lucius") -> str:
        """Report a quality/security finding for Robin to track.

        Used when Alfred discovers issues that Robin should monitor or
        include in nightwatch reports.
        """
        return self.respond_to_robin("finding", {
            "title": title,
            "severity": severity,
            "detail": detail,
            "source": source,
            "session_id": self.session_id,
        })

    def mark_read(self, msg_id: str):
        """Mark a message as read and archive it."""
        for f in ALFRED_INBOX.glob(f"{msg_id}*.json"):
            try:
                with open(f) as fh:
                    msg = json.load(fh)
                msg["status"] = "read"
                msg["read_at"] = datetime.now().isoformat()
                archive_path = ARCHIVE_DIR / f.name
                with open(archive_path, "w") as fh:
                    json.dump(msg, fh, indent=2)
                f.unlink()
            except Exception:
                continue

    def get_robin_status(self) -> Optional[dict]:
        """Check Robin's current status."""
        try:
            with open(COORD_DIR / "robin-status.json") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None


# Quick test
if __name__ == "__main__":
    print("Testing Robin-Alfred Protocol v2...")
    robin = RobinMailbox()
    print(f"Robin status: {robin.status_file}")
    print(f"Alfred inbox: {ALFRED_INBOX}")
    print(f"Robin inbox: {ROBIN_INBOX}")

    # Test basic message
    msg_id = robin.send_to_alfred("health", {"test": True})
    print(f"Sent test health: {msg_id}")

    # Test Alfred session awareness
    alfred = AlfredMailbox(session_id="test-session", session_number=15)
    print(f"Alfred session: {alfred.session_id} (#{alfred.session_number})")

    # Test session lifecycle
    alfred.announce_session_start(priorities=["P0: CI integration", "P1: Protocol v2"])
    print("Session start announced")

    # Test task delegation + ack flow
    task_id = alfred.assign_task("Run hygiene check", "Execute lucius:hygiene_check")
    print(f"Task assigned: {task_id}")

    robin_msgs = robin.check_inbox()
    for msg in robin_msgs:
        if msg["type"] == "task":
            ack_id = robin.acknowledge_task(msg["id"], eta_minutes=5)
            print(f"Task acknowledged: {ack_id}")
            # Simulate completion
            done_id = robin.report_task_complete(msg["id"], "Hygiene check passed: 0 findings")
            print(f"Task complete: {done_id}")
        robin.mark_read(msg["id"])

    # Test finding reporting
    finding_id = robin.report_finding("Stale log files", "low", "3 log files > 30 days old")
    print(f"Finding reported: {finding_id}")

    # Alfred reads everything
    msgs = alfred.check_inbox()
    print(f"Alfred sees {len(msgs)} message(s)")
    for msg in msgs:
        print(f"  [{msg['type']}] {msg['payload'].get('subject', msg['payload'].get('task_id', msg['payload'].get('title', '?')))}")
        alfred.mark_read(msg["id"])

    alfred.announce_session_end("Test session complete", prs_merged=[28], next_priorities=["Continue testing"])
    print("Session end announced")

    print("Protocol v2 test complete.")
