"""
Session State — machine-readable continuity between Cowork sessions.

Problem: When a Cowork session hits context compaction or expires, the next
session starts cold. Prose handoff docs (SESSION-HANDOFF.md) help but are
lossy — exact code context, decision rationale, and task priorities are lost.

Solution: A structured session-state.json that captures:
  1. Active tasks with priority scores
  2. Recent git activity (last N commits, current branch, dirty files)
  3. CI status (last known pass/fail)
  4. Agent health snapshot (from health_check contracts)
  5. Key file edit history (what was touched and why)
  6. Pending decisions and blockers

The next session reads this file in <2000 tokens and reconstructs working
context without needing to re-explore the codebase.

Usage:
    # At end of session:
    from rudy.session_state import SessionState
    state = SessionState()
    state.capture()   # snapshots current state
    state.save()      # writes to session-state.json

    # At start of next session:
    state = SessionState.load()
    print(state.briefing())  # human-readable summary
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
DATA_DIR = DESKTOP / "rudy-data"
STATE_FILE = DATA_DIR / "session-state.json"
LOGS_DIR = DESKTOP / "rudy-logs"


class SessionState:
    """Structured session state for continuity between Cowork sessions."""

    def __init__(self):
        self.data = {
            "version": 1,
            "captured_at": "",
            "git": {
                "branch": "",
                "last_commits": [],
                "dirty_files": [],
                "remote_url": "",
            },
            "ci": {
                "lint_status": "unknown",
                "test_status": "unknown",
                "last_checked": "",
            },
            "tasks": [],
            "agents": {},
            "recent_edits": [],
            "blockers": [],
            "notes": [],
        }

    def capture(self, repo_dir: Optional[str] = None):
        """Snapshot the current state of the workspace."""
        self.data["captured_at"] = datetime.now().isoformat()
        self._capture_git(repo_dir)
        self._capture_agents()
        return self

    def _capture_git(self, repo_dir: Optional[str] = None):
        """Capture git state."""
        cwd = repo_dir or str(DESKTOP / "rudy-workhorse")
        try:
            # Current branch
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5, cwd=cwd
            )
            self.data["git"]["branch"] = result.stdout.strip()

            # Last 5 commits
            result = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                capture_output=True, text=True, timeout=5, cwd=cwd
            )
            self.data["git"]["last_commits"] = [
                line.strip() for line in result.stdout.strip().splitlines()
            ]

            # Dirty files
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5, cwd=cwd
            )
            self.data["git"]["dirty_files"] = [
                line.strip() for line in result.stdout.strip().splitlines()
                if line.strip()
            ]

            # Remote URL (sanitize token if present)
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5, cwd=cwd
            )
            url = result.stdout.strip()
            # Strip any embedded tokens
            if "@" in url and "x-access-token" in url:
                url = url.split("@")[-1]
                url = f"https://{url}"
            self.data["git"]["remote_url"] = url

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    def _capture_agents(self):
        """Capture agent health from status files."""
        if not LOGS_DIR.exists():
            return
        for status_file in LOGS_DIR.glob("*-status.json"):
            try:
                with open(status_file, encoding="utf-8") as f:
                    status = json.load(f)
                agent_name = status.get("agent", status_file.stem.replace("-status", ""))
                self.data["agents"][agent_name] = {
                    "status": status.get("status", "unknown"),
                    "last_run": status.get("last_run", "never"),
                    "alerts": len(status.get("critical_alerts", [])),
                    "summary": status.get("summary", "")[:200],
                }
            except (json.JSONDecodeError, OSError):
                pass

    def add_task(self, description: str, priority: int = 5, status: str = "pending"):
        """Add a task to the session state."""
        self.data["tasks"].append({
            "description": description,
            "priority": priority,
            "status": status,
            "added": datetime.now().isoformat(),
        })
        return self

    def add_edit(self, file_path: str, reason: str):
        """Record a file edit for context."""
        self.data["recent_edits"].append({
            "file": file_path,
            "reason": reason,
            "when": datetime.now().isoformat(),
        })
        # Keep only last 20 edits
        self.data["recent_edits"] = self.data["recent_edits"][-20:]
        return self

    def add_blocker(self, description: str):
        """Record a blocker."""
        self.data["blockers"].append({
            "description": description,
            "added": datetime.now().isoformat(),
        })
        return self

    def add_note(self, note: str):
        """Add a freeform note for next session."""
        self.data["notes"].append(note)
        return self

    def set_ci_status(self, lint: str = "unknown", test: str = "unknown"):
        """Update CI status."""
        self.data["ci"]["lint_status"] = lint
        self.data["ci"]["test_status"] = test
        self.data["ci"]["last_checked"] = datetime.now().isoformat()
        return self

    def save(self, path: Optional[Path] = None):
        """Write state to JSON file."""
        target = path or STATE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, default=str)
        return self

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "SessionState":
        """Load state from JSON file."""
        target = path or STATE_FILE
        state = cls()
        if target.exists():
            try:
                with open(target, encoding="utf-8") as f:
                    state.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return state

    def briefing(self) -> str:
        """Generate a concise human-readable briefing for session start.

        Designed to be <2000 tokens so it fits in initial context.
        """
        lines = [f"Session State (captured {self.data.get('captured_at', 'unknown')})"]
        lines.append("")

        # Git
        git = self.data.get("git", {})
        if git.get("branch"):
            lines.append(f"Branch: {git['branch']}")
        if git.get("last_commits"):
            lines.append("Recent commits:")
            for c in git["last_commits"][:5]:
                lines.append(f"  {c}")
        if git.get("dirty_files"):
            lines.append(f"Uncommitted changes: {len(git['dirty_files'])} files")

        # CI
        ci = self.data.get("ci", {})
        if ci.get("lint_status") != "unknown" or ci.get("test_status") != "unknown":
            lines.append(f"\nCI: lint={ci.get('lint_status')} test={ci.get('test_status')}")

        # Tasks
        tasks = self.data.get("tasks", [])
        pending = [t for t in tasks if t.get("status") != "completed"]
        if pending:
            lines.append(f"\nPending tasks ({len(pending)}):")
            for t in sorted(pending, key=lambda x: -x.get("priority", 0))[:10]:
                lines.append(f"  [{t.get('priority', '?')}] {t['description']}")

        # Agents
        agents = self.data.get("agents", {})
        if agents:
            lines.append("\nAgent health:")
            for name, info in agents.items():
                icon = {"healthy": "OK", "error": "ERR", "stale": "STALE"}.get(
                    info.get("status", "?"), "?"
                )
                lines.append(f"  {icon} {name}: {info.get('summary', '')[:80]}")

        # Blockers
        blockers = self.data.get("blockers", [])
        if blockers:
            lines.append(f"\nBlockers ({len(blockers)}):")
            for b in blockers:
                lines.append(f"  - {b['description']}")

        # Notes
        notes = self.data.get("notes", [])
        if notes:
            lines.append("\nNotes:")
            for n in notes[-5:]:
                lines.append(f"  - {n}")

        return "\n".join(lines)
