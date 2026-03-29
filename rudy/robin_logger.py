#!/usr/bin/env python3

"""
Robin Logger -- Autonomous logging to Notion after task completion.

Robin writes his own operational logs. Short, decisive, no fluff.
Each entry: timestamp, task, result, tools used, duration.

Target: Robin Operations Log page in Notion.
Page ID: 3327d3f7-e736-816d-8622-d884ccc0a3cd
"""

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("robin_logger")

# Robin Operations Log page in Notion
ROBIN_LOG_PAGE_ID = "3327d3f7-e736-816d-8622-d884ccc0a3cd"

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _get_notion_token() -> Optional[str]:
    """Get Notion token from robin-secrets.json or environment."""
    # Try robin-secrets.json first
    secrets_path = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop" / "rudy-data" / "robin-secrets.json"
    if secrets_path.exists():
        try:
            with open(secrets_path) as f:
                secrets = json.load(f)
            token = secrets.get("notion_token", "")
            if token and not token.startswith("PASTE"):
                return token
        except Exception:
            pass

    # Try environment
    token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_INTEGRATION_TOKEN")
    if token:
        return token

    # Try keyring
    try:
        import keyring
        token = keyring.get_password("notion", "robin")
        if token:
            return token
    except ImportError:
        pass

    return None


def _notion_request(method: str, path: str, token: str, data: dict = None) -> dict:
    """Make a Notion API request."""
    url = f"{NOTION_API_BASE}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


LOCAL_LOG_DIR = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop" / "rudy-logs"
LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_to_local_json(task, success, final_answer, total_steps=0,
                        total_tool_calls=0, duration_ms=0,
                        tools_used=None, error=None):
    """Write a task entry to local JSON log file (always succeeds)."""
    log_file = LOCAL_LOG_DIR / f"robin-ops-{datetime.now().strftime('%Y%m%d')}.json"
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "task": task,
        "success": success,
        "answer": final_answer[:500],
        "steps": total_steps,
        "tool_calls": total_tool_calls,
        "duration_ms": duration_ms,
        "tools": tools_used or [],
        "error": error,
    }
    
    # Append to daily log file
    entries = []
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text())
        except (json.JSONDecodeError, OSError):
            entries = []
    
    entries.append(entry)
    log_file.write_text(json.dumps(entries, indent=2, default=str))
    log.info("Local log: %s -> %s", task[:40], log_file.name)


def log_task_to_notion(
    task: str,
    success: bool,
    final_answer: str,
    total_steps: int = 0,
    total_tool_calls: int = 0,
    duration_ms: int = 0,
    tools_used: list[str] = None,
    error: str = None,
    page_id: str = ROBIN_LOG_PAGE_ID,
) -> bool:
    """
    Write a task completion entry to Robin's Notion log.

    Returns True if logged successfully, False otherwise.
    """
    token = _get_notion_token()
    now = datetime.now()

    # Always write to local JSON log (fallback + audit trail)
    _log_to_local_json(
        task=task, success=success, final_answer=final_answer,
        total_steps=total_steps, total_tool_calls=total_tool_calls,
        duration_ms=duration_ms, tools_used=tools_used, error=error,
    )

    if not token:
        log.info("No Notion token -- logged to local JSON only")
        return True  # local log succeeded
    status_emoji = "\u2705" if success else "\u274c"
    duration_str = f"{duration_ms / 1000:.1f}s" if duration_ms else "?"

    # Build tools summary
    tools_str = ", ".join(tools_used) if tools_used else "none"

    # Truncate final answer for log
    answer_preview = final_answer[:300]
    if len(final_answer) > 300:
        answer_preview += "..."

    blocks = [
        # Heading: timestamp + status
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {
                    "content": f"{now.strftime('%Y-%m-%d %H:%M')} {status_emoji} {task[:80]}"
                }}],
            },
        },
        # Details
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {
                    "content": (
                        f"Steps: {total_steps} | Tools: {total_tool_calls} | "
                        f"Duration: {duration_str} | Used: {tools_str}"
                    )
                }}],
            },
        },
        # Result
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {
                    "content": f"Result: {answer_preview}"
                }}],
            },
        },
    ]

    # Add error block if failed
    if error:
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {
                    "content": f"\u26a0\ufe0f Error: {error}"
                }}],
            },
        })

    # Divider
    blocks.append({"object": "block", "type": "divider", "divider": {}})

    try:
        _notion_request("PATCH", f"/blocks/{page_id}/children", token, {"children": blocks})
        log.info("Logged task to Notion: %s", task[:60])
        return True
    except Exception as e:
        log.warning("Failed to log to Notion: %s", e)
        return False


def log_nightwatch_checkin(
    status: str = "alive",
    tasks_pending: int = 0,
    notes: str = "",
    page_id: str = ROBIN_LOG_PAGE_ID,
) -> bool:
    """Write a periodic night-watch check-in to Notion."""
    token = _get_notion_token()
    
    # Local log always
    _log_to_local_json(
        task=f"nightwatch-checkin: {status}",
        success=True,
        final_answer=notes or status,
    )
    
    if not token:
        return True  # local log succeeded

    now = datetime.now()
    blocks = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {
                    "content": (
                        f"\U0001f4a4 Night Watch {now.strftime('%H:%M')} -- "
                        f"Status: {status} | Pending: {tasks_pending}"
                        + (f" | {notes}" if notes else "")
                    )
                }}],
            },
        },
    ]

    try:
        _notion_request("PATCH", f"/blocks/{page_id}/children", token, {"children": blocks})
        return True
    except Exception:
        return False
