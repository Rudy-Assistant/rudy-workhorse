#!/usr/bin/env python3
"""
Oracle Git Helper — reusable git operations for Alfred sessions.

Eliminates per-session friction from DC stdout bugs and PowerShell quirks.
All operations use subprocess with explicit encoding and PATH injection.

Usage (from any Alfred session helper script):
    from oracle_git import OracleGit
    og = OracleGit()
    og.status()
    og.add(["rudy/file.py", "rudy/other.py"])
    og.commit("S63: Fix lint errors")
    og.push()

Or as CLI:
    python rudy-data/helpers/oracle_git.py status
    python rudy-data/helpers/oracle_git.py add rudy/file.py rudy/other.py
    python rudy-data/helpers/oracle_git.py commit "S63: Fix lint errors"
    python rudy-data/helpers/oracle_git.py push
    python rudy-data/helpers/oracle_git.py full-push "commit msg" file1 file2 ...
"""
import json
import os
import subprocess
import sys

REPO = r"C:\Users\ccimi\rudy-workhorse"  # lucius-exempt: canonical repo path
GIT = r"C:\Program Files\Git\cmd\git.exe"  # lucius-exempt: canonical tool path
GH = r"C:\Program Files\GitHub CLI\gh.exe"  # lucius-exempt: canonical tool path
LOG_FILE = os.path.join(REPO, "rudy-data", "oracle-git-log.txt")


def _env():
    """Return env dict with git on PATH for gh CLI compatibility."""
    env = os.environ.copy()
    env["PATH"] = r"C:\Program Files\Git\cmd;" + env.get("PATH", "")  # lucius-exempt: PATH setup
    env["GH_GIT_EXECUTABLE"] = GIT
    return env


def _run(args, check=False):
    """Run a command, return (stdout, stderr, returncode). Always UTF-8."""
    r = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        env=_env(),
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"Command failed (rc={r.returncode}): {r.stderr.strip()}")
    return r.stdout.strip(), r.stderr.strip(), r.returncode


class OracleGit:
    """Stateless git wrapper for Oracle. Every method returns a result dict."""

    def status(self):
        out, err, rc = _run([GIT, "status", "--short"])
        return {"output": out, "rc": rc}

    def log(self, n=5):
        out, err, rc = _run([GIT, "log", "--oneline", f"-{n}"])
        return {"output": out, "rc": rc}

    def branch(self):
        out, err, rc = _run([GIT, "branch", "--show-current"])
        return {"branch": out, "rc": rc}

    def diff_names(self, base="main"):
        out, err, rc = _run([GIT, "diff", "--name-only", f"origin/{base}...HEAD"])
        return {"files": out.split("\n") if out else [], "rc": rc}

    def add(self, files):
        """Stage specific files."""
        out, err, rc = _run([GIT, "add"] + list(files), check=True)
        return {"rc": rc}

    def commit(self, message):
        out, err, rc = _run([GIT, "commit", "-m", message])
        return {"output": out or err, "rc": rc}

    def push(self, branch=None):
        if not branch:
            branch = self.branch()["branch"]
        out, err, rc = _run([GIT, "push", "origin", branch])
        return {"output": out or err, "rc": rc}

    def full_push(self, message, files):
        """Add, commit, push in one call. Returns combined result."""
        results = {}
        results["add"] = self.add(files)
        results["commit"] = self.commit(message)
        results["push"] = self.push()
        return results

    def pr_view(self, pr_number):
        """Get PR status via gh CLI."""
        out, err, rc = _run([
            GH, "pr", "view", str(pr_number),
            "--repo", "Rudy-Assistant/rudy-workhorse",
            "--json", "state,statusCheckRollup,mergeable,title"
        ])
        if rc == 0 and out:
            return json.loads(out)
        return {"error": err, "rc": rc}

    def pr_merge(self, pr_number, method="squash"):
        """Merge a PR via gh CLI."""
        out, err, rc = _run([
            GH, "pr", "merge", str(pr_number),
            "--repo", "Rudy-Assistant/rudy-workhorse",
            f"--{method}", "--delete-branch"
        ])
        return {"output": out or err, "rc": rc}

    def ruff_check(self, files):
        """Run ruff lint on specified files."""
        out, err, rc = _run(
            [r"C:\Python312\python.exe", "-m", "ruff", "check"] + list(files)  # lucius-exempt: tool path
        )
        return {"output": out, "rc": rc, "clean": rc == 0}


def _log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{msg}\n")


def main():
    """CLI interface."""
    og = OracleGit()
    if len(sys.argv) < 2:
        print("Usage: oracle_git.py <command> [args...]")
        print("Commands: status, log, branch, add, commit, push, full-push, pr-view, pr-merge, ruff")
        sys.exit(1)

    cmd = sys.argv[1]
    result = {}
    if cmd == "status":
        result = og.status()
    elif cmd == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        result = og.log(n)
    elif cmd == "branch":
        result = og.branch()
    elif cmd == "add":
        result = og.add(sys.argv[2:])
    elif cmd == "commit":
        result = og.commit(sys.argv[2])
    elif cmd == "push":
        result = og.push(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "full-push":
        msg = sys.argv[2]
        files = sys.argv[3:]
        result = og.full_push(msg, files)
    elif cmd == "pr-view":
        result = og.pr_view(sys.argv[2])
    elif cmd == "pr-merge":
        method = sys.argv[3] if len(sys.argv) > 3 else "squash"
        result = og.pr_merge(sys.argv[2], method)
    elif cmd == "ruff":
        result = og.ruff_check(sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    print(json.dumps(result, indent=2))
    _log(f"{cmd}: {json.dumps(result)}")


if __name__ == "__main__":
    main()
