"""Robin skill: Manage coordination files.

Handles alfred-status.json, session-branch.json, and bridge-heartbeat.json.
Alfred delegates coordination file updates to Robin.

Usage:
    python scripts/robin_coord_manager.py update-alfred --session N --status online|offline
    python scripts/robin_coord_manager.py update-branch --branch NAME --pr N --session N
    python scripts/robin_coord_manager.py show
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

COORD_DIR = Path(os.environ.get(
    "RUDY_DATA", str(Path.home() / "rudy-data")
)) / "coordination"


def update_alfred(session: int, status: str, last_action: str = ""):
    path = COORD_DIR / "alfred-status.json"
    data = {
        "status": status,
        "session": session,
        "since": datetime.now().isoformat(),
        "last_action": last_action,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Updated alfred-status: session={session}, status={status}")


def update_branch(branch: str, pr: int, session: int, note: str = ""):
    path = COORD_DIR / "session-branch.json"
    data = {
        "branch": branch,
        "pr": pr,
        "session": session,
        "note": note,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Updated session-branch: {branch}, PR #{pr}")


def show():
    for name in ["alfred-status.json", "session-branch.json", "bridge-heartbeat.json"]:
        path = COORD_DIR / name
        if path.exists():
            print(f"\n--- {name} ---")
            print(path.read_text(encoding="utf-8"))
        else:
            print(f"\n--- {name} --- NOT FOUND")


def main():
    parser = argparse.ArgumentParser(description="Coordination file manager")
    sub = parser.add_subparsers(dest="command")

    p_alfred = sub.add_parser("update-alfred")
    p_alfred.add_argument("--session", type=int, required=True)
    p_alfred.add_argument("--status", required=True, choices=["online", "offline"])
    p_alfred.add_argument("--last-action", default="")

    p_branch = sub.add_parser("update-branch")
    p_branch.add_argument("--branch", required=True)
    p_branch.add_argument("--pr", type=int, default=0)
    p_branch.add_argument("--session", type=int, required=True)
    p_branch.add_argument("--note", default="")

    sub.add_parser("show")

    args = parser.parse_args()
    if args.command == "update-alfred":
        update_alfred(args.session, args.status, args.last_action)
    elif args.command == "update-branch":
        update_branch(args.branch, args.pr, args.session, args.note)
    elif args.command == "show":
        show()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
