"""
Alfred ↔ Robin Delegation via claude-peers-mcp — Session 27

Message schema for real-time task delegation between Alfred (Cloud) and
Robin (Local) through the claude-peers-mcp broker on localhost:7899.

Messages are JSON-encoded strings sent via the broker's text field.
Each message has an envelope with type, sender, timestamp, and payload.

Message Types:
    DELEGATE    — Alfred → Robin: Execute this task
    RESULT      — Robin → Alfred: Task execution result
    ESCALATE    — Robin → Alfred: I'm blocked, need help
    STATUS      — Either direction: Status update
    HEARTBEAT   — Either direction: I'm alive
    ACK         — Either direction: Message received

Integration:
    - Alfred calls delegate_to_robin() to send tasks
    - Robin's poll loop calls poll_and_dispatch() to receive and execute
    - Results flow back via send_result()
    - Escalations come back via send_escalation()

The message text field in claude-peers-mcp is a plain string.
We JSON-encode our structured messages into that field.

Lucius Gate: LG-??? — No new dependencies. Stdlib + requests only.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from rudy.paths import REPO_ROOT

log = logging.getLogger("peers.delegation")

BROKER_URL = "http://localhost:7899"

# ---------------------------------------------------------------------------
# Message Schema
# ---------------------------------------------------------------------------

# Valid message types
MSG_DELEGATE = "delegate"
MSG_RESULT = "result"
MSG_ESCALATE = "escalate"
MSG_STATUS = "status"
MSG_HEARTBEAT = "heartbeat"
MSG_ACK = "ack"

# Valid task types (maps to robin_taskqueue.py)
TASK_TYPES = [
    "audit", "browse", "profile", "code_quality",
    "git", "report", "handoff", "colab",
    # Extended types for delegation
    "shell", "skill_execute", "health_check", "security_scan",
]


def create_delegation_message(
    task_type: str,
    title: str,
    description: str = "",
    priority: int = 50,
    estimated_minutes: int = 5,
    command: Optional[str] = None,
    skill_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a DELEGATE message for Alfred → Robin.

    Returns JSON string to send via claude-peers-mcp send_message.

    Args:
        task_type: One of TASK_TYPES.
        title: Short task title.
        description: Detailed instructions.
        priority: 0=highest, 100=lowest. Default 50.
        estimated_minutes: Expected duration.
        command: Shell command to execute (for shell/audit tasks).
        skill_id: OpenSpace skill_id to execute (for skill_execute tasks).
        context: Additional context dict.
    """
    msg = {
        "type": MSG_DELEGATE,
        "id": f"del-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sender": "alfred",
        "task": {
            "type": task_type,
            "title": title,
            "description": description,
            "priority": priority,
            "estimated_minutes": estimated_minutes,
            "status": "pending",
        },
    }
    if command:
        msg["task"]["command"] = command
    if skill_id:
        msg["task"]["skill_id"] = skill_id
    if context:
        msg["context"] = context
    return json.dumps(msg)


def create_result_message(
    delegation_id: str,
    success: bool,
    output: str = "",
    error: str = "",
    duration_seconds: float = 0,
    findings: Optional[List[str]] = None,
) -> str:
    """Create a RESULT message for Robin → Alfred.

    Args:
        delegation_id: The delegation message ID being responded to.
        success: Whether the task succeeded.
        output: Task output/result text.
        error: Error message if failed.
        duration_seconds: How long execution took.
        findings: Any findings discovered during execution.
    """
    msg = {
        "type": MSG_RESULT,
        "id": f"res-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sender": "robin",
        "delegation_id": delegation_id,
        "success": success,
        "output": output[:2000],  # Cap output size for message transport
        "error": error[:500] if error else "",
        "duration_seconds": round(duration_seconds, 2),
    }
    if findings:
        msg["findings"] = findings[:20]  # Cap findings count
    return json.dumps(msg)


def create_escalation_message(
    delegation_id: str,
    reason: str,
    blocker_type: str = "capability",
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Create an ESCALATE message for Robin → Alfred.

    Args:
        delegation_id: The delegation being escalated.
        reason: Why Robin can't complete the task.
        blocker_type: One of: capability, permission, error, timeout.
        context: Additional context about the blocker.
    """
    msg = {
        "type": MSG_ESCALATE,
        "id": f"esc-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sender": "robin",
        "delegation_id": delegation_id,
        "reason": reason,
        "blocker_type": blocker_type,
    }
    if context:
        msg["context"] = context
    return json.dumps(msg)


def create_status_message(
    sender: str,
    status: str,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a STATUS message (either direction).

    Args:
        sender: "alfred" or "robin".
        status: Free-text status string.
        details: Additional status details.
    """
    msg = {
        "type": MSG_STATUS,
        "id": f"sts-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sender": sender,
        "status": status,
    }
    if details:
        msg["details"] = details
    return json.dumps(msg)


def parse_message(text: str) -> Optional[Dict[str, Any]]:
    """Parse a claude-peers-mcp message text into structured form.

    Returns None if the message is not a valid delegation protocol message.
    """
    try:
        msg = json.loads(text)
        if isinstance(msg, dict) and "type" in msg:
            return msg
    except (json.JSONDecodeError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Broker HTTP helpers (for direct use without MCP)
# ---------------------------------------------------------------------------

def _post(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """POST to the broker. Import isolation: requests inside function."""
    import requests
    try:
        r = requests.post(f"{BROKER_URL}/{endpoint}", json=data, timeout=5)
        return r.json()
    except Exception as e:
        log.error("Broker POST %s failed: %s", endpoint, e)
        return {"error": str(e)}


def register_peer(
    pid: int,
    cwd: str,
    summary: str,
    git_root: Optional[str] = None,
    tty: Optional[str] = None,
) -> Optional[str]:
    """Register with the broker. Returns peer_id or None."""
    result = _post("register", {
        "pid": pid,
        "cwd": cwd,
        "git_root": git_root or cwd,
        "tty": tty,
        "summary": summary,
    })
    return result.get("id")


def send_to_peer(from_id: str, to_id: str, message_text: str) -> bool:
    """Send a message to a peer. Returns True on success."""
    result = _post("send-message", {
        "from_id": from_id,
        "to_id": to_id,
        "text": message_text,
    })
    return result.get("ok", False)


def poll_messages(peer_id: str) -> List[Dict[str, Any]]:
    """Poll for new messages. Returns list of parsed delegation messages."""
    result = _post("poll-messages", {"id": peer_id})
    messages = []
    for raw_msg in result.get("messages", []):
        parsed = parse_message(raw_msg.get("text", ""))
        if parsed:
            parsed["_broker_msg_id"] = raw_msg.get("id")
            parsed["_from_peer"] = raw_msg.get("from_id")
            messages.append(parsed)
    return messages


def list_peers(
    cwd: str,
    scope: str = "machine",
    git_root: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List registered peers."""
    return _post("list-peers", {
        "scope": scope,
        "cwd": cwd,
        "git_root": git_root or cwd,
    })


# ---------------------------------------------------------------------------
# High-level delegation API
# ---------------------------------------------------------------------------

def delegate_to_robin(
    alfred_peer_id: str,
    robin_peer_id: str,
    task_type: str,
    title: str,
    **kwargs,
) -> Optional[str]:
    """Alfred delegates a task to Robin via claude-peers-mcp.

    Returns the delegation message ID, or None on failure.
    """
    msg_text = create_delegation_message(task_type, title, **kwargs)
    msg_data = json.loads(msg_text)

    success = send_to_peer(alfred_peer_id, robin_peer_id, msg_text)
    if success:
        log.info("Delegated to Robin: [%s] %s (id=%s)", task_type, title, msg_data["id"])
        return msg_data["id"]
    else:
        log.error("Failed to delegate to Robin: [%s] %s", task_type, title)
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Alfred ↔ Robin Delegation Protocol")
    parser.add_argument("command", choices=["status", "peers", "test-delegate", "test-parse"])
    parser.add_argument("--cwd", default=str(REPO_ROOT))
    args = parser.parse_args()

    if args.command == "status":
        import requests
        try:
            requests.get(f"{BROKER_URL}/list-peers", timeout=3)
            print(f"Broker: ONLINE at {BROKER_URL}")
        except Exception:
            print(f"Broker: OFFLINE at {BROKER_URL}")
            return

        peers = list_peers(args.cwd)
        if isinstance(peers, list):
            print(f"Peers: {len(peers)}")
            for p in peers:
                print(f"  {p['id']} ({p['summary']}) - PID {p['pid']}")
        else:
            print(f"Peers: {peers}")

    elif args.command == "test-delegate":
        msg = create_delegation_message(
            task_type="health_check",
            title="Oracle health check",
            description="Run full system health check and report CPU, RAM, disk usage.",
            priority=20,
            estimated_minutes=2,
            command="Get-ComputerInfo | Select-Object CsProcessors, OsTotalVisibleMemorySize, OsFreePhysicalMemory",
        )
        print("Delegation message:")
        print(json.dumps(json.loads(msg), indent=2))

    elif args.command == "test-parse":
        # Round-trip test
        msg = create_delegation_message("audit", "Test audit", description="Test")
        parsed = parse_message(msg)
        print(f"Parse OK: {parsed is not None}")
        print(f"Type: {parsed['type']}")
        print(f"Task: {parsed['task']['title']}")

        result = create_result_message(parsed["id"], True, output="All clear")
        parsed_result = parse_message(result)
        print(f"Result parse OK: {parsed_result is not None}")
        print(f"Success: {parsed_result['success']}")


if __name__ == "__main__":
    main()
