#!/usr/bin/env python3

"""
Robin Bridge — Polls alfred-skills/docs/robin-tasks/ for pending tasks from Alfred.

This is the primary Alfred-to-Robin delegation channel. Alfred creates task files
in the GitHub repo with YAML frontmatter. Robin polls for pending tasks, claims them,
executes them, and writes results back.

Task file format:
 ---
 task: task-slug
 status: pending|claimed|completed|failed
 priority: critical|high|medium|low
 created: 2026-03-29T01:30:00Z
 created_by: alfred
 claimed_by: robin # Added when Robin claims
 completed_at: <iso> # Added when done
 ---
 # Task Title
 ... markdown body with steps, acceptance criteria, etc.

Usage:
 python -m rudy.agents.robin_bridge # Poll once
 python -m rudy.agents.robin_bridge --continuous # Poll every 5 minutes
 python -m rudy.agents.robin_bridge --status # Show task queue status
"""

import json
import logging
import os
import re
import sys
import time
from base64 import b64decode, b64encode
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Optional: keyring for secure token storage
try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

# Optional: httpx for async (fall back to urllib)
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    import urllib.request
    import urllib.error

log = logging.getLogger("robin_bridge")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALFRED_REPO = "Rudy-Assistant/alfred-skills"
TASKS_PATH = "docs/robin-tasks"
POLL_INTERVAL = 300  # 5 minutes
HOME = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
BRIDGE_LOG = HOME / "Desktop" / "rudy-logs" / "robin-bridge.log"


def _get_github_token() -> str:
    """Retrieve GitHub PAT from keyring or environment."""
    # Try keyring first (secure storage)
    if HAS_KEYRING:
        token = keyring.get_password("github", "rudy-assistant")
        if token:
            return token

    # Fall back to environment variable
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if token:
        return token

    # Fall back to .env file
    env_file = HOME / "Desktop" / "rudy-data" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GITHUB_TOKEN=") or line.startswith("GITHUB_PERSONAL_ACCESS_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    raise RuntimeError("No GitHub token found. Set via keyring, GITHUB_TOKEN env var, or rudy-data/.env")


# ---------------------------------------------------------------------------
# GitHub API Client (minimal, no dependencies beyond stdlib)
# ---------------------------------------------------------------------------

class GitHubAPI:
    """Minimal GitHub API client using httpx or urllib."""

    BASE = "https://api.github.com"

    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Robin-Bridge/1.0",
        }

    def get(self, path: str) -> dict:
        url = f"{self.BASE}{path}"
        if HAS_HTTPX:
            resp = httpx.get(url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        else:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())

    def put(self, path: str, data: dict) -> dict:
        url = f"{self.BASE}{path}"
        body = json.dumps(data).encode()
        if HAS_HTTPX:
            resp = httpx.put(url, headers=self.headers, content=body, timeout=30)
            resp.raise_for_status()
            return resp.json()
        else:
            req = urllib.request.Request(url, data=body, headers={**self.headers, "Content-Type": "application/json"}, method="PUT")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())

    def get_file(self, repo: str, path: str) -> tuple[str, str]:
        """Get file content and SHA. Returns (content_text, sha)."""
        data = self.get(f"/repos/{repo}/contents/{path}")
        raw = data["content"].replace("\n", "")
        content = b64decode(raw).decode("utf-8")
        return content, data["sha"]

    def update_file(self, repo: str, path: str, content: str, sha: str, message: str) -> dict:
        """Update a file in the repo."""
        encoded = b64encode(content.encode("utf-8")).decode("ascii")
        return self.put(f"/repos/{repo}/contents/{path}", {
            "message": message,
            "content": encoded,
            "sha": sha,
        })


# ---------------------------------------------------------------------------
# Task Parser
# ---------------------------------------------------------------------------

def parse_task(content: str) -> dict:
    """Parse a task file with YAML frontmatter."""
    # Extract YAML frontmatter between --- markers
    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if not match:
        return {"raw": content, "frontmatter": {}, "body": content}

    frontmatter_text = match.group(1)
    body = match.group(2).strip()

    # Simple YAML parser (no PyYAML dependency needed for key: value pairs)
    frontmatter: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip()

    return {"frontmatter": frontmatter, "body": body, "raw": content}


def update_frontmatter(content: str, updates: dict[str, str]) -> str:
    """Update frontmatter fields in a task file."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if not match:
        return content

    lines = match.group(1).splitlines()
    body = match.group(2)

    # Update existing keys
    updated_keys = set()
    new_lines = []
    for line in lines:
        if ":" in line:
            key = line.split(":")[0].strip()
            if key in updates:
                new_lines.append(f"{key}: {updates[key]}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Add new keys
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}: {value}")

    return "---\n" + "\n".join(new_lines) + "\n---\n" + body


# ---------------------------------------------------------------------------
# Robin Bridge
# ---------------------------------------------------------------------------

class RobinBridge:
    """Polls GitHub for pending tasks and executes them."""

    def __init__(self):
        self.token = _get_github_token()
        self.api = GitHubAPI(self.token)
        self.log = logging.getLogger("robin_bridge")

    def poll_and_execute(self) -> dict:
        """Poll for pending tasks, claim and execute them."""
        results = {"timestamp": datetime.now().isoformat(), "tasks_found": 0, "tasks_completed": 0, "errors": []}

        try:
            # List files in robin-tasks directory
            data = self.api.get(f"/repos/{ALFRED_REPO}/contents/{TASKS_PATH}")
            task_files = [f for f in data if f["name"].endswith(".md") and f["name"] != "README.md"]
            results["tasks_found"] = len(task_files)

            for file_info in task_files:
                try:
                    content, sha = self.api.get_file(ALFRED_REPO, file_info["path"])
                    task = parse_task(content)
                    fm = task["frontmatter"]

                    if fm.get("status") != "pending":
                        continue

                    self.log.info("Found pending task: %s (%s priority)",
                                  fm.get("task", file_info["name"]),
                                  fm.get("priority", "medium"))

                    # Claim the task
                    claimed_content = update_frontmatter(content, {
                        "status": "claimed",
                        "claimed_by": "robin",
                        "claimed_at": datetime.now().isoformat(),
                    })
                    self.api.update_file(
                        ALFRED_REPO, file_info["path"], claimed_content, sha,
                        f"Robin claims task: {fm.get('task', 'unknown')}",
                    )

                    # Execute the task
                    task_result = self._execute_task(fm, task["body"])

                    # Update with result
                    new_status = "completed" if task_result.get("success") else "failed"
                    # Re-fetch to get updated SHA after claim
                    _, new_sha = self.api.get_file(ALFRED_REPO, file_info["path"])
                    result_text = json.dumps(task_result, indent=2)
                    completed_content = update_frontmatter(claimed_content, {
                        "status": new_status,
                        "completed_at": datetime.now().isoformat(),
                    })
                    # Append result to body
                    completed_content = f"{completed_content.rstrip()}\n\n## Result (Robin — {datetime.now().isoformat()})\n```json\n{result_text}\n```\n"

                    self.api.update_file(
                        ALFRED_REPO, file_info["path"], completed_content, new_sha,
                        f"Robin {'completed' if task_result.get('success') else 'failed'}: {fm.get('task', 'unknown')}",
                    )

                    if task_result.get("success"):
                        results["tasks_completed"] += 1
                    else:
                        results["errors"].append(f"{fm.get('task')}: {task_result.get('error', 'unknown')}")

                except Exception as e:
                    self.log.error("Error processing task %s: %s", file_info["name"], e)
                    results["errors"].append(f"{file_info['name']}: {str(e)}")

        except Exception as e:
            self.log.error("Failed to poll tasks: %s", e)
            results["errors"].append(f"poll_error: {str(e)}")

        return results

    def _execute_task(self, frontmatter: dict, body: str) -> dict:
        """
        Execute a task based on its content.

        For now, Robin can execute tasks that involve:
        - Running shell commands (PowerShell, Python)
        - Configuring services
        - File operations

        Complex tasks that require AI reasoning will be routed to Ollama.
        """
        task_slug = frontmatter.get("task", "unknown")
        self.log.info("Executing task: %s", task_slug)

        # Route to specific handlers based on task slug
        handlers = {
            "configure-github-mcp-token": self._handle_configure_mcp_token,
            "upgrade-pat-scopes": self._handle_upgrade_pat_scopes,
            "robin-notion-integration": self._handle_notion_integration,
        }

        handler = handlers.get(task_slug)
        if handler:
            return handler(body)

        # For unknown tasks, try to extract and run steps, or consult local LLM
        return self._handle_generic_task(task_slug, body)

    def _handle_configure_mcp_token(self, body: str) -> dict:
        """Configure GitHub MCP with valid PAT."""
        try:
            token = self.token  # Use the same token Robin already has

            # Find MCP config locations
            mcp_configs = [
                Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
                HOME / ".claude" / "mcp.json",
                HOME / "Desktop" / "rudy-workhorse" / ".claude" / "mcp.json",
            ]

            configured = []
            for config_path in mcp_configs:
                if config_path.exists():
                    try:
                        with open(config_path) as f:
                            config = json.load(f)

                        # Find github MCP server entry and set token
                        servers = config.get("mcpServers", config.get("servers", {}))
                        for name, server in servers.items():
                            if "github" in name.lower():
                                env = server.setdefault("env", {})
                                env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
                                configured.append(str(config_path))

                        with open(config_path, "w") as f:
                            json.dump(config, f, indent=2)
                    except Exception as e:
                        self.log.warning("Could not update %s: %s", config_path, e)

            if configured:
                return {"success": True, "configured": configured}
            else:
                return {"success": False, "error": "No MCP config files found with GitHub server entry"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_upgrade_pat_scopes(self, body: str) -> dict:
        """This requires web UI interaction — delegate to Human Behavior Simulation."""
        # This task needs Robin's human simulation capabilities to navigate GitHub settings
        # For now, document what needs to happen and mark as needing human sim
        return {
            "success": False,
            "error": "Requires Human Behavior Simulation to navigate GitHub token settings UI",
            "needs": "human_simulation",
            "steps_identified": [
                "Navigate to github.com/settings/tokens",
                "Find existing fine-grained token",
                "Edit permissions to add pull_requests:write",
                "Save and copy new token value",
            ],
        }

    def _handle_notion_integration(self, body: str) -> dict:
        """Set up Notion integration for Robin."""
        return {
            "success": False,
            "error": "Requires creating Notion integration at notion.so/my-integrations — needs Human Behavior Simulation",
            "needs": "human_simulation",
        }

    def _handle_generic_task(self, slug: str, body: str) -> dict:
        """Handle unknown tasks — try local LLM for interpretation."""
        try:
            from rudy.local_ai import ask_local
            response = ask_local(
                f"You are Robin, a local AI agent. Analyze this task and determine if it can be executed "
                f"automatically or needs human interaction:\n\nTask: {slug}\n\n{body[:2000]}",
                role="ops",
            )
            return {
                "success": False,
                "error": "Generic task — LLM analysis only",
                "llm_analysis": response[:1000] if response else "No LLM response",
                "needs": "manual_review",
            }
        except Exception:
            return {
                "success": False,
                "error": f"Unknown task type: {slug} — no handler and no local LLM available",
            }

    def get_queue_status(self) -> dict:
        """Get current status of all tasks in the queue."""
        try:
            data = self.api.get(f"/repos/{ALFRED_REPO}/contents/{TASKS_PATH}")
            tasks = []
            for f in data:
                if f["name"].endswith(".md") and f["name"] != "README.md":
                    content, _ = self.api.get_file(ALFRED_REPO, f["path"])
                    task = parse_task(content)
                    fm = task["frontmatter"]
                    tasks.append({
                        "file": f["name"],
                        "task": fm.get("task", "unknown"),
                        "status": fm.get("status", "unknown"),
                        "priority": fm.get("priority", "medium"),
                        "created_by": fm.get("created_by", "unknown"),
                    })
            return {"tasks": tasks, "total": len(tasks),
                    "pending": sum(1 for t in tasks if t["status"] == "pending")}
        except Exception as e:
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [Bridge] %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(BRIDGE_LOG),
            logging.StreamHandler(),
        ],
    )

    args = sys.argv[1:]
    bridge = RobinBridge()

    if "--status" in args:
        status = bridge.get_queue_status()
        print(json.dumps(status, indent=2))
        return

    if "--continuous" in args:
        log.info("Robin Bridge entering continuous polling mode")
        while True:
            try:
                result = bridge.poll_and_execute()
                if result.get("tasks_completed", 0) > 0:
                    log.info("Completed %d tasks", result["tasks_completed"])
                time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error("Poll cycle error: %s", e)
                time.sleep(60)
        return

    # Default: single poll
    result = bridge.poll_and_execute()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
