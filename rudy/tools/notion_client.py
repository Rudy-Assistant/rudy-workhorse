#!/usr/bin/env python3
"""
Notion Client for Robin — Read/write access to the Bat Family's shared knowledge.

Robin uses this to:
- Read Bat Family Directives for standing instructions
- Write health check results to the Watchdog Health Log
- Update the Batcave Operations Hub with Oracle system status
- Log completed tasks and session results

Requires a Notion integration token stored in Windows Credential Manager
via keyring: keyring.set_password("notion", "robin", "<token>")

Key Notion Page IDs (from Alfred Session 2):
- Batcave Operations Hub: 3327d3f7-e736-81b1-8c48-d300c31a7883
- Bat Family Directives:  3327d3f7-e736-81b5-8293-faa7d9c5ed7d
- Alfred Session Log:     3327d3f7-e736-81ff-ab82-d73d2f106a61
- Workhorse Command Center: 32f7d3f7-e736-81fc-aa01-d378d347d427
- Watchdog Health Log:    3327d3f7-e736-8109-bf96-f79796545a73
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    import urllib.request
    import urllib.error

log = logging.getLogger("notion_client")

# ---------------------------------------------------------------------------
# Page IDs
# ---------------------------------------------------------------------------
PAGES = {
    "batcave_hub": "3327d3f7-e736-81b1-8c48-d300c31a7883",
    "directives": "3327d3f7-e736-81b5-8293-faa7d9c5ed7d",
    "session_log": "3327d3f7-e736-81ff-ab82-d73d2f106a61",
    "command_center": "32f7d3f7-e736-81fc-aa01-d378d347d427",
    "health_log": "3327d3f7-e736-8109-bf96-f79796545a73",
}


def _get_notion_token() -> str:
    """Retrieve Notion integration token from keyring or environment."""
    if HAS_KEYRING:
        token = keyring.get_password("notion", "robin")
        if token:
            return token

    token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_INTEGRATION_TOKEN")
    if token:
        return token

    # Fall back to .env
    env_file = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop" / "rudy-data" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("NOTION_TOKEN=") or line.startswith("NOTION_INTEGRATION_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    raise RuntimeError(
        "No Notion token found. Create integration at notion.so/my-integrations, "
        "then: keyring.set_password('notion', 'robin', '<token>')"
    )


class NotionAPI:
    """Minimal Notion API client."""

    BASE = "https://api.notion.com/v1"
    VERSION = "2022-06-28"

    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": self.VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        url = f"{self.BASE}{path}"
        body = json.dumps(data).encode() if data else None

        if HAS_HTTPX:
            resp = getattr(httpx, method.lower())(url, headers=self.headers, content=body, timeout=30)
            resp.raise_for_status()
            return resp.json()
        else:
            req = urllib.request.Request(url, data=body, headers=self.headers, method=method.upper())
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())

    def get_page(self, page_id: str) -> dict:
        return self._request("GET", f"/pages/{page_id}")

    def get_blocks(self, block_id: str) -> list[dict]:
        """Get all child blocks of a page/block."""
        blocks = []
        cursor = None
        while True:
            path = f"/blocks/{block_id}/children"
            if cursor:
                path += f"?start_cursor={cursor}"
            data = self._request("GET", path)
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return blocks

    def append_blocks(self, page_id: str, blocks: list[dict]) -> dict:
        """Append blocks to a page."""
        return self._request("PATCH", f"/blocks/{page_id}/children", {"children": blocks})


class NotionClient:
    """High-level Notion operations for Robin."""

    def __init__(self):
        self.token = _get_notion_token()
        self.api = NotionAPI(self.token)

    def read_directives(self) -> str:
        """Read the Bat Family Directives page content."""
        blocks = self.api.get_blocks(PAGES["directives"])
        return self._blocks_to_text(blocks)

    def append_health_log(self, assessment: dict) -> None:
        """Append a health check entry to the Watchdog Health Log."""
        now = datetime.now()
        healthy = assessment.get("all_healthy", False)
        online = assessment.get("online", False)

        status_emoji = "\u2705" if healthy else "\u26a0\ufe0f"
        status_text = "NOMINAL" if healthy else "DEGRADED"
        connectivity = "ONLINE" if online else "OFFLINE"

        # Build action summary
        actions = []
        for phase in assessment.get("phases", {}).values():
            actions.extend(phase.get("actions", []))

        blocks = [
            self._heading(f"{now.strftime('%Y-%m-%d %I:%M %p ET')} — {status_emoji} {status_text}"),
            self._paragraph(f"**Status:** {status_text} | **Connectivity:** {connectivity}"),
        ]

        if actions:
            blocks.append(self._paragraph(f"**Actions taken:** {'; '.join(actions)}"))

        if assessment.get("degraded_systems"):
            blocks.append(self._paragraph(
                f"**Degraded systems:** {', '.join(assessment['degraded_systems'])}"
            ))

        blocks.append(self._paragraph(
            f"**Boot duration:** {assessment.get('boot_duration_seconds', '?')}s | "
            f"**Source:** Robin Sentinel"
        ))
        blocks.append(self._divider())

        self.api.append_blocks(PAGES["health_log"], blocks)
        log.info("Health log updated in Notion")

    def update_oracle_status(self, status: dict) -> None:
        """Update the Batcave Operations Hub with Oracle's current status."""
        # This appends a status update block; in the future we could
        # update specific sections of the page
        blocks = [
            self._heading(f"Oracle Status — {datetime.now().strftime('%Y-%m-%d %I:%M %p')}"),
            self._paragraph(json.dumps(status, indent=2)[:1900]),  # Notion block limit
            self._divider(),
        ]
        self.api.append_blocks(PAGES["batcave_hub"], blocks)

    def log_night_shift(self, results: dict) -> None:
        """Log night shift activity to the session log."""
        blocks = [
            self._heading(f"Robin Night Shift — {datetime.now().strftime('%Y-%m-%d')}"),
            self._paragraph(f"**Started:** {results.get('started', '?')}"),
            self._paragraph(f"**Ended:** {results.get('ended', '?')}"),
        ]

        if results.get("tasks_completed"):
            blocks.append(self._paragraph(
                f"**Tasks completed:** {', '.join(str(t) for t in results['tasks_completed'])}"
            ))

        if results.get("errors"):
            blocks.append(self._paragraph(
                f"**Errors:** {'; '.join(results['errors'])}"
            ))

        blocks.append(self._divider())
        self.api.append_blocks(PAGES["session_log"], blocks)

    # -----------------------------------------------------------------------
    # Block builders
    # -----------------------------------------------------------------------

    @staticmethod
    def _heading(text: str, level: int = 3) -> dict:
        key = f"heading_{level}"
        return {
            "object": "block",
            "type": key,
            key: {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]],
        }

    @staticmethod
    def _paragraph(text: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]],
        }

    @staticmethod
    def _divider() -> dict:
        return {"object": "block", "type": "divider", "divider": {}}

    @staticmethod
    def _blocks_to_text(blocks: list[dict]) -> str:
        """Extract plain text from Notion blocks."""
        lines = []
        for block in blocks:
            btype = block.get("type", "")
            content = block.get(btype, {})
            rich_text = content.get("rich_text", [])
            text = "".join(rt.get("plain_text", "") for rt in rich_text)
            if text:
                lines.append(text)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [Notion] %(message)s")

    args = sys.argv[1:]
    client = NotionClient()

    if "--read-directives" in args:
        text = client.read_directives()
        print(text)
    elif "--test" in args:
        # Write a test entry to health log
        test_assessment = {
            "all_healthy": True,
            "online": True,
            "boot_duration_seconds": 2.1,
            "phases": {},
        }
        client.append_health_log(test_assessment)
        print("Test entry written to Watchdog Health Log")
    else:
        print("Usage:")
        print("  --read-directives  Read Bat Family Directives")
        print("  --test             Write test entry to health log")


if __name__ == "__main__":
    main()
