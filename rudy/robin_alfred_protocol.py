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
  - "request"     : Robin asks Alfred for guidance or a cloud task
  - "report"      : Robin reports completed work or findings
  - "health"      : Periodic health check / status update
  - "escalation"  : Something Robin can't handle alone
  - "task"        : Alfred assigns work to Robin
  - "ack"         : Acknowledgment of received message

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
from pathlib import Path
from typing import Optional


RUDY_DATA = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop" / "rudy-data"
COORD_DIR = RUDY_DATA / "coordination"
ALFRED_INBOX = RUDY_DATA / "alfred-inbox"
ROBIN_INBOX = RUDY_DATA / "robin-inbox"
ARCHIVE_DIR = RUDY_DATA / "coordination" / "archive"

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
    """

    def __init__(self):
        self.status_file = COORD_DIR / "alfred-status.json"

    def update_status(self, state: str, session_id: str = "", details: str = ""):
        """Update Alfred's status file."""
        status = {
            "state": state,
            "updated_at": datetime.now().isoformat(),
            "session_id": session_id,
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
                    messages.append(msg)
            except (json.JSONDecodeError, OSError):
                continue
        return messages

    def respond_to_robin(self, msg_type: str, payload: dict, in_reply_to: str = "") -> str:
        """Send a response to Robin's inbox."""
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
    print("Testing Robin-Alfred Protocol...")
    robin = RobinMailbox()
    print(f"Robin status: {robin.status_file}")
    print(f"Alfred inbox: {ALFRED_INBOX}")
    print(f"Robin inbox: {ROBIN_INBOX}")

    # Send a test message
    msg_id = robin.send_to_alfred("health", {"test": True})
    print(f"Sent test message: {msg_id}")

    # Check Alfred's view
    alfred = AlfredMailbox()
    msgs = alfred.check_inbox()
    print(f"Alfred sees {len(msgs)} message(s)")

    for msg in msgs:
        print(f"  [{msg['type']}] {msg['payload']}")
        alfred.mark_read(msg['id'])

    print("Protocol test complete.")
