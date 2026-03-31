#!/usr/bin/env python3
"""
oracle-git-ops.py -- Reliable Git/GitHub CLI for Cowork (Alfred) Sessions

Solves the recurring Oracle tooling difficulties documented in Session 28:
1. Desktop Commander read_file returns metadata-only
2. Desktop Commander start_process output never captured
3. gh CLI cannot find git in PATH
4. Windows-MCP Shell returns CLIXML instead of output
5. Python subprocess output capture via PowerShell is unreliable

DESIGN PRINCIPLES:
- ALL output written to a JSON file (never relies on stdout capture)
- PATH always set correctly so gh can find git
- Uses `gh api` for PR operations (most reliable path)
- Single CLI entry point: C:\\Python312\\python.exe oracle-git-ops.py <cmd> [args]
- Read results via: [System.IO.File]::ReadAllText("C:\\Users\\ccimi\\oracle-git-output.json")

USAGE FROM COWORK SESSION:
    # Step 1: Run command
    C:\\Python312\\python.exe C:\\Users\\ccimi\\rudy-workhorse\\oracle-git-ops.py status

    # Step 2: Read output
    [System.IO.File]::ReadAllText("C:\\Users\\ccimi\\oracle-git-output.json")

COMMANDS:
    status                          - Git status + branch + recent log
    branch <name>                   - Create and checkout new branch
    checkout <name>                 - Switch to existing branch
    commit <message> [files...]     - Stage files and commit (no files = stage all)
    push [branch]                   - Push to origin (optional target branch)
    pull                            - Pull from origin on current branch
    diff [--staged]                 - Show diff (optionally staged only)
    log [n]                         - Show last n commits (default 10)
    pr-create <title> <body> [base] - Create PR via gh api
    pr-merge <number> [method]      - Merge PR (squash/merge/rebase, default squash)
    pr-view <number>                - View PR details
    pr-list [state]                 - List PRs (open/closed/all, default open)
    pr-checks <number>              - Check CI status for a PR
    pr-review <number>              - Get review status for a PR
"""

import subprocess
import json
import sys
import os
import tempfile
from datetime import datetime
from pathlib import Path

# === Configuration ===
REPO_OWNER = "Rudy-Assistant"
REPO_NAME = "rudy-workhorse"
REPO_SLUG = f"{REPO_OWNER}/{REPO_NAME}"
REPO_DIR = r"C:\Users\ccimi\rudy-workhorse"
GIT_CMD = r"C:\Program Files\Git\cmd\git.exe"
GH_CMD = r"C:\Program Files\GitHub CLI\gh.exe"
OUTPUT_FILE = r"C:\Users\ccimi\oracle-git-output.json"


def get_env():
    """Get environment with PATH fixed for gh to find git."""
    env = os.environ.copy()
    git_dir = r"C:\Program Files\Git\cmd"
    if git_dir not in env.get("PATH", ""):
        env["PATH"] = git_dir + ";" + env.get("PATH", "")
    env["GH_GIT_EXEC_PATH"] = git_dir
    # Prevent Unicode issues on Windows cmd
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_git(*args, timeout=60):
    """Run a git command and return (success, stdout, stderr)."""
    cmd = [GIT_CMD] + list(args)
    try:
        r = subprocess.run(
            cmd,
            capture_output=True, text=True,
            cwd=REPO_DIR, env=get_env(),
            timeout=timeout
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def run_gh_api(endpoint, method="GET", fields=None, jq_filter=None, timeout=30):
    """Run gh api command (most reliable path for GitHub operations)."""
    cmd = [GH_CMD, "api"]
    if method != "GET":
        cmd += ["-X", method]
    cmd.append(endpoint)
    if fields:
        for key, val in fields.items():
            cmd += ["--field", f"{key}={val}"]
    if jq_filter:
        cmd += ["--jq", jq_filter]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True, text=True,
            env=get_env(), timeout=timeout
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def write_output(data):
    """Write output as JSON to the output file."""
    result = {
        "timestamp": datetime.now().isoformat(),
        "success": data.get("success", False),
        "command": " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "none",
        **data
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    # Also print for cases where stdout IS captured
    print(json.dumps(result, indent=2, ensure_ascii=False))


# === Commands ===

def cmd_status():
    """Git status + branch + recent log."""
    ok_branch, branch, _ = run_git("branch", "--show-current")
    ok_status, status, _ = run_git("status", "--short")
    ok_log, log_out, _ = run_git("log", "--oneline", "-5")
    ok_remote, remote, _ = run_git("remote", "-v")

    write_output({
        "success": True,
        "branch": branch,
        "changes": [l for l in status.split("\n") if l] if status else [],
        "recent_commits": [l for l in log_out.split("\n") if l] if log_out else [],
        "remotes": [l for l in remote.split("\n") if l] if remote else [],
    })


def cmd_branch(name):
    """Create and checkout a new branch."""
    ok, out, err = run_git("checkout", "-b", name)
    write_output({
        "success": ok,
        "branch": name,
        "output": out,
        "error": err if not ok else "",
    })


def cmd_checkout(name):
    """Switch to existing branch."""
    ok, out, err = run_git("checkout", name)
    write_output({
        "success": ok,
        "branch": name,
        "output": out,
        "error": err if not ok else "",
    })


def cmd_commit(message, files=None):
    """Stage files and commit."""
    if files:
        for f in files:
            run_git("add", f)
    else:
        run_git("add", "-A")

    ok, out, err = run_git("commit", "-m", message)
    # Get the new commit hash
    _, commit_hash, _ = run_git("rev-parse", "--short", "HEAD")

    write_output({
        "success": ok,
        "message": message,
        "commit": commit_hash if ok else "",
        "output": out,
        "error": err if not ok else "",
        "files_staged": files or ["all"],
    })


def cmd_push(branch=None):
    """Push to origin."""
    if branch:
        ok, out, err = run_git("push", "origin", f"HEAD:{branch}", timeout=120)
    else:
        ok, out, err = run_git("push", "origin", "HEAD", timeout=120)
        if not ok and "no upstream" in err.lower():
            # Try setting upstream
            _, current_branch, _ = run_git("branch", "--show-current")
            ok, out, err = run_git("push", "-u", "origin", current_branch, timeout=120)

    write_output({
        "success": ok,
        "target_branch": branch or "current",
        "output": out,
        "error": err if not ok else "",
    })


def cmd_pull():
    """Pull from origin."""
    ok, out, err = run_git("pull", "origin", timeout=120)
    write_output({
        "success": ok,
        "output": out + ("\n" + err if err else ""),
        "error": "" if ok else err,
    })


def cmd_diff(staged=False):
    """Show diff."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    ok, out, err = run_git(*args)
    write_output({
        "success": ok,
        "diff": out,
        "staged": staged,
        "error": err if not ok else "",
    })


def cmd_log(count=10):
    """Show recent commits."""
    ok, out, _ = run_git("log", f"--oneline", f"-{count}")
    write_output({
        "success": ok,
        "commits": [l for l in out.split("\n") if l] if out else [],
        "count": count,
    })


def cmd_pr_create(title, body, base="main"):
    """Create a PR via gh api."""
    _, head_branch, _ = run_git("branch", "--show-current")

    ok, out, err = run_gh_api(
        f"repos/{REPO_SLUG}/pulls",
        method="POST",
        fields={
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base,
        },
        jq_filter="{number,html_url,title,state,head_ref: .head.ref}",
    )

    if ok:
        try:
            pr_data = json.loads(out)
        except json.JSONDecodeError:
            pr_data = {"raw": out}
    else:
        pr_data = {}

    write_output({
        "success": ok,
        "pr": pr_data,
        "head": head_branch,
        "base": base,
        "error": err if not ok else "",
    })


def cmd_pr_merge(number, method="squash"):
    """Merge a PR via gh api."""
    ok, out, err = run_gh_api(
        f"repos/{REPO_SLUG}/pulls/{number}/merge",
        method="PUT",
        fields={"merge_method": method},
    )

    if ok:
        try:
            merge_data = json.loads(out)
        except json.JSONDecodeError:
            merge_data = {"raw": out}
    else:
        merge_data = {}

    write_output({
        "success": ok,
        "pr_number": number,
        "method": method,
        "merge": merge_data,
        "error": err if not ok else "",
    })


def cmd_pr_view(number):
    """View PR details via gh api."""
    ok, out, err = run_gh_api(
        f"repos/{REPO_SLUG}/pulls/{number}",
        jq_filter="{number,title,state,mergeable,mergeable_state,user:.user.login,created_at,updated_at,html_url,additions,deletions,changed_files,head_ref:.head.ref,base_ref:.base.ref}",
    )

    if ok:
        try:
            pr_data = json.loads(out)
        except json.JSONDecodeError:
            pr_data = {"raw": out}
    else:
        pr_data = {}

    write_output({
        "success": ok,
        "pr": pr_data,
        "error": err if not ok else "",
    })


def cmd_pr_list(state="open"):
    """List PRs via gh api."""
    ok, out, err = run_gh_api(
        f"repos/{REPO_SLUG}/pulls?state={state}&per_page=20",
        jq_filter="[.[] | {number,title,state,user:.user.login,created_at,head_ref:.head.ref}]",
    )

    if ok:
        try:
            prs = json.loads(out)
        except json.JSONDecodeError:
            prs = [{"raw": out}]
    else:
        prs = []

    write_output({
        "success": ok,
        "state_filter": state,
        "prs": prs,
        "count": len(prs),
        "error": err if not ok else "",
    })


def cmd_pr_checks(number):
    """Check CI status for a PR via gh api."""
    # First get the head SHA
    ok, out, _ = run_gh_api(
        f"repos/{REPO_SLUG}/pulls/{number}",
        jq_filter=".head.sha",
    )
    if not ok:
        write_output({"success": False, "error": f"Could not get PR head SHA: {out}"})
        return

    sha = out.strip().strip('"')

    # Get check runs for that SHA
    ok, out, err = run_gh_api(
        f"repos/{REPO_SLUG}/commits/{sha}/check-runs",
        jq_filter="[.check_runs[] | {name,status,conclusion}]",
    )

    if ok:
        try:
            checks = json.loads(out)
        except json.JSONDecodeError:
            checks = [{"raw": out}]
    else:
        checks = []

    all_pass = all(c.get("conclusion") == "success" for c in checks if isinstance(c, dict))

    write_output({
        "success": ok,
        "pr_number": number,
        "sha": sha,
        "checks": checks,
        "all_passing": all_pass,
        "error": err if not ok else "",
    })


def cmd_pr_review(number):
    """Get review status for a PR."""
    ok, out, err = run_gh_api(
        f"repos/{REPO_SLUG}/pulls/{number}/reviews",
        jq_filter="[.[] | {user:.user.login,state,submitted_at}]",
    )

    if ok:
        try:
            reviews = json.loads(out)
        except json.JSONDecodeError:
            reviews = [{"raw": out}]
    else:
        reviews = []

    write_output({
        "success": ok,
        "pr_number": number,
        "reviews": reviews,
        "error": err if not ok else "",
    })


# === CLI Entry Point ===

def main():
    if len(sys.argv) < 2:
        write_output({
            "success": False,
            "error": "No command specified",
            "usage": "oracle-git-ops.py <command> [args...]",
            "commands": [
                "status", "branch", "checkout", "commit", "push", "pull",
                "diff", "log", "pr-create", "pr-merge", "pr-view",
                "pr-list", "pr-checks", "pr-review",
            ],
        })
        return

    cmd = sys.argv[1].lower()

    try:
        if cmd == "status":
            cmd_status()
        elif cmd == "branch":
            if len(sys.argv) < 3:
                write_output({"success": False, "error": "Usage: branch <name>"})
            else:
                cmd_branch(sys.argv[2])
        elif cmd == "checkout":
            if len(sys.argv) < 3:
                write_output({"success": False, "error": "Usage: checkout <name>"})
            else:
                cmd_checkout(sys.argv[2])
        elif cmd == "commit":
            if len(sys.argv) < 3:
                write_output({"success": False, "error": "Usage: commit <message> [files...]"})
            else:
                msg = sys.argv[2]
                files = sys.argv[3:] if len(sys.argv) > 3 else None
                cmd_commit(msg, files)
        elif cmd == "push":
            branch = sys.argv[2] if len(sys.argv) > 2 else None
            cmd_push(branch)
        elif cmd == "pull":
            cmd_pull()
        elif cmd == "diff":
            staged = "--staged" in sys.argv
            cmd_diff(staged)
        elif cmd == "log":
            count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            cmd_log(count)
        elif cmd == "pr-create":
            if len(sys.argv) < 4:
                write_output({"success": False, "error": "Usage: pr-create <title> <body> [base]"})
            else:
                base = sys.argv[4] if len(sys.argv) > 4 else "main"
                cmd_pr_create(sys.argv[2], sys.argv[3], base)
        elif cmd == "pr-merge":
            if len(sys.argv) < 3:
                write_output({"success": False, "error": "Usage: pr-merge <number> [method]"})
            else:
                method = sys.argv[3] if len(sys.argv) > 3 else "squash"
                cmd_pr_merge(int(sys.argv[2]), method)
        elif cmd == "pr-view":
            if len(sys.argv) < 3:
                write_output({"success": False, "error": "Usage: pr-view <number>"})
            else:
                cmd_pr_view(int(sys.argv[2]))
        elif cmd == "pr-list":
            state = sys.argv[2] if len(sys.argv) > 2 else "open"
            cmd_pr_list(state)
        elif cmd == "pr-checks":
            if len(sys.argv) < 3:
                write_output({"success": False, "error": "Usage: pr-checks <number>"})
            else:
                cmd_pr_checks(int(sys.argv[2]))
        elif cmd == "pr-review":
            if len(sys.argv) < 3:
                write_output({"success": False, "error": "Usage: pr-review <number>"})
            else:
                cmd_pr_review(int(sys.argv[2]))
        else:
            write_output({
                "success": False,
                "error": f"Unknown command: {cmd}",
                "commands": [
                    "status", "branch", "checkout", "commit", "push", "pull",
                    "diff", "log", "pr-create", "pr-merge", "pr-view",
                    "pr-list", "pr-checks", "pr-review",
                ],
            })
    except Exception as e:
        write_output({
            "success": False,
            "error": f"Unhandled exception: {type(e).__name__}: {e}",
            "command": cmd,
        })


if __name__ == "__main__":
    main()
