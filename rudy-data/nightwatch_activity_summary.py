"""Nightwatch Activity Summary -- generates a report of recent activity.

Called by robin_taskqueue.py task_type="report" during night shift.
Outputs a summary to stdout (captured by _execute_command).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(r"C:\Users\ccimi\rudy-workhorse")
RUDY_DATA = REPO / "rudy-data"


def recent_commits(hours=24):
    """Get commits from the last N hours."""
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    try:
        r = subprocess.run(
            ["git", "log", "--since=" + since, "--oneline", "--no-decorate"],
            capture_output=True, text=True, timeout=15,
            cwd=str(REPO), encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().split("\n")
    except Exception:
        pass
    return []


def recent_sessions():
    """Check for recent handoff files."""
    handoffs_dir = REPO / "vault" / "Handoffs"
    if not handoffs_dir.exists():
        return []
    recent = []
    cutoff = datetime.now() - timedelta(hours=24)
    for f in sorted(handoffs_dir.glob("Session-*-Handoff.md"), reverse=True)[:5]:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime > cutoff:
            recent.append({"file": f.name, "modified": mtime.isoformat()})
    return recent


def robin_status():
    """Quick Robin health summary."""
    status_file = RUDY_DATA / "robin-status.json"
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            return {
                "state": data.get("state", "unknown"),
                "last_update": data.get("last_update", "unknown"),
            }
        except Exception:
            pass
    return {"state": "unknown"}


def main():
    report = {
        "generated_at": datetime.now().isoformat(),
        "recent_commits_24h": len(recent_commits()),
        "commits": recent_commits()[:10],
        "recent_sessions": recent_sessions(),
        "robin": robin_status(),
    }
    print(json.dumps(report, indent=2))
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
