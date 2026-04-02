#!/usr/bin/env python3
"""
Oracle Shell Executor — unified execution layer for Alfred/Cowork sessions.

Eliminates 70% of per-session friction by providing a single import that handles:
- Running shell commands with proper encoding (CMD, not PowerShell)
- Reading files (bypassing DC read_file metadata-only bug LG-S34-003)
- Writing files with UTF-8 encoding
- Running ruff lint checks matching CI configuration
- Git operations (delegates to oracle_git helper)
- CI status polling via gh CLI
- JSON-safe output capture (bypasses DC stdout swallow bug LG-S63-001)

Usage from a session helper script:
    import sys; sys.path.insert(0, r'C:\\Users\\ccimi\\rudy-workhorse')  # lucius-exempt
    from rudy.oracle_shell import OracleShell
    sh = OracleShell(session=65)

    # Run a command
    result = sh.run("git status --short")

    # Read a file
    content = sh.read_file(r"rudy-data\\coordination\\robin-status.json")

    # Run CI lint check locally (matches .github/workflows/lint.yml)
    lint = sh.ci_lint_check()

    # Check PR CI status
    status = sh.pr_ci_status(135)

    # Full git workflow
    sh.git_add_commit_push("fix: trailing newline", ["rudy/file.py"])

All results are also written to a session log file for debugging.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Canonical paths (lucius-exempt)
REPO = Path(r"C:\Users\ccimi\rudy-workhorse")  # lucius-exempt: canonical repo path
PYTHON = r"C:\Python312\python.exe"  # lucius-exempt: canonical tool path
GIT = r"C:\Program Files\Git\cmd\git.exe"  # lucius-exempt: canonical tool path
GH = r"C:\Program Files\GitHub CLI\gh.exe"  # lucius-exempt: canonical tool path
RUFF = [PYTHON, "-m", "ruff"]


def _env():
    """Return env dict with git on PATH."""
    env = os.environ.copy()
    env["PATH"] = r"C:\Program Files\Git\cmd;" + env.get("PATH", "")
    env["GH_GIT_EXECUTABLE"] = GIT
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(args, cwd=None, timeout=30, check=False):
    """Run a command, return dict with stdout, stderr, rc."""
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd or str(REPO),
            env=_env(),
            timeout=timeout,
        )
        result = {
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
            "rc": r.returncode,
            "ok": r.returncode == 0,
        }
        if check and r.returncode != 0:
            raise RuntimeError(
                f"Command failed (rc={r.returncode}): {r.stderr.strip()}"
            )
        return result
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "TIMEOUT", "rc": -1, "ok": False}


class OracleShell:
    """Unified execution layer for Alfred/Cowork sessions on Oracle."""

    def __init__(self, session=0):
        self.session = session
        self.log_path = REPO / "rudy-data" / f"s{session}-shell.log"
        self._log(f"OracleShell initialized for session {session}")

    def _log(self, msg):
        """Append to session log."""
        ts = datetime.now().strftime("%H:%M:%S")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")

    # ── Shell Commands ──────────────────────────────────────────────

    def run(self, command, timeout=30):
        """Run a shell command via CMD. Returns result dict."""
        result = _run(["cmd", "/c", command], timeout=timeout)
        self._log(f"run({command[:80]}): rc={result['rc']}")
        return result

    def run_python(self, code, name="tmp"):
        """Write code to a temp .py file, execute, return output, clean up."""
        script_path = REPO / "rudy-data" / f"s{self.session}_{name}.py"
        script_path.write_text(code, encoding="utf-8")
        result = _run([PYTHON, str(script_path)], timeout=60)
        try:
            script_path.unlink()
        except OSError:
            pass
        self._log(f"run_python({name}): rc={result['rc']}")
        return result

    # ── File Operations ─────────────────────────────────────────────

    def read_file(self, path, encoding="utf-8"):
        """Read a file, bypassing DC read_file bug (LG-S34-003)."""
        try:
            content = Path(path).read_text(encoding=encoding)
            return {"content": content, "ok": True, "lines": content.count("\n")}
        except Exception as e:
            return {"content": "", "ok": False, "error": str(e)}

    def read_json(self, path):
        """Read and parse a JSON file."""
        result = self.read_file(path)
        if result["ok"]:
            try:
                result["data"] = json.loads(result["content"])
            except json.JSONDecodeError as e:
                result["ok"] = False
                result["error"] = f"JSON parse error: {e}"
        return result

    def write_file(self, path, content, encoding="utf-8"):
        """Write content to a file with proper encoding."""
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding=encoding)
            return {"ok": True, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_json(self, path, data):
        """Write a dict/list to a JSON file."""
        return self.write_file(path, json.dumps(data, indent=2, default=str))

    # ── CI / Lint ───────────────────────────────────────────────────

    def ci_lint_check(self, paths=None):
        """Run ruff check matching CI workflow configuration.

        CI runs: ruff check rudy/ --select E,F,W --ignore E501,E402,F401
        """
        target = paths or ["rudy/"]
        result = _run(
            RUFF + ["check"] + target +
            ["--select", "E,F,W", "--ignore", "E501,E402,F401"],
            timeout=30,
        )
        result["clean"] = result["rc"] == 0
        self._log(f"ci_lint_check: {'PASS' if result['clean'] else 'FAIL'}")
        return result

    def ci_syntax_check(self, paths=None):
        """Run py_compile on all Python files (matches CI syntax check step)."""
        target = paths or ["rudy/", "scripts/"]
        errors = []
        for t in target:
            target_path = REPO / t
            if not target_path.exists():
                continue
            for py_file in target_path.rglob("*.py"):
                r = _run([PYTHON, "-m", "py_compile", str(py_file)])
                if r["rc"] != 0:
                    errors.append({"file": str(py_file), "error": r["stderr"]})
        result = {"errors": errors, "clean": len(errors) == 0}
        self._log(f"ci_syntax_check: {'PASS' if result['clean'] else f'FAIL ({len(errors)} errors)'}")
        return result

    def run_ci_local(self):
        """Run all CI checks locally in one shot (ruff + syntax + bandit)."""
        results = {
            "lint": self.ci_lint_check(),
            "syntax": self.ci_syntax_check(),
        }
        # Optional bandit check
        bandit_result = _run(
            [PYTHON, "-m", "bandit", "-r", "rudy/", "-c", "pyproject.toml", "-q"],
            timeout=60,
        )
        results["bandit"] = {**bandit_result, "clean": bandit_result["rc"] == 0}
        results["all_pass"] = all(r.get("clean", False) for r in results.values())
        self._log(f"run_ci_local: {'ALL PASS' if results['all_pass'] else 'FAILURES'}")
        return results

    # ── Git Operations ──────────────────────────────────────────────

    def git(self, *args, timeout=30):
        """Run a git command. Returns result dict."""
        result = _run([GIT] + list(args), timeout=timeout)
        self._log(f"git {' '.join(args[:3])}: rc={result['rc']}")
        return result

    def git_status(self):
        """Get short git status."""
        return self.git("status", "--short")

    def git_branch(self):
        """Get current branch name."""
        r = self.git("branch", "--show-current")
        r["branch"] = r["stdout"]
        return r

    def git_log(self, n=5):
        """Get recent commits."""
        return self.git("log", "--oneline", f"-{n}")

    def git_add_commit_push(self, message, files, branch=None):
        """Add, commit, push in one call. The full workflow."""
        results = {}
        results["add"] = self.git("add", *files)
        results["commit"] = self.git("commit", "-m", message)
        if not branch:
            branch = self.git_branch()["branch"]
        results["push"] = self.git("push", "origin", branch, timeout=60)
        results["ok"] = all(r.get("ok", False) for r in results.values())
        self._log(f"git_add_commit_push: {'OK' if results['ok'] else 'FAIL'}")
        return results

    def git_checkout(self, branch, create=False):
        """Checkout a branch. If create=True, creates it from origin/main."""
        if create:
            self.git("fetch", "origin", "main")
            return self.git("checkout", "-b", branch, "origin/main")
        return self.git("checkout", branch)

    # ── GitHub CLI ──────────────────────────────────────────────────

    def gh(self, *args, timeout=30):
        """Run a gh CLI command. Returns result dict."""
        result = _run([GH] + list(args), timeout=timeout)
        self._log(f"gh {' '.join(args[:3])}: rc={result['rc']}")
        return result

    def pr_view(self, pr_number, fields="state,statusCheckRollup,mergeable,title"):
        """Get PR details as parsed JSON."""
        r = self.gh("pr", "view", str(pr_number), "--json", fields)
        if r["ok"] and r["stdout"]:
            try:
                r["data"] = json.loads(r["stdout"])
            except json.JSONDecodeError:
                pass
        return r

    def pr_ci_status(self, pr_number):
        """Check if a PR's CI checks have all passed."""
        r = self.pr_view(pr_number)
        if not r["ok"] or "data" not in r:
            return {"ok": False, "error": "Could not fetch PR", "raw": r}

        data = r["data"]
        checks = data.get("statusCheckRollup", [])
        results = []
        all_pass = True
        for check in checks:
            name = check.get("name", "unknown")
            conclusion = check.get("conclusion", "PENDING")
            status = check.get("status", "UNKNOWN")
            passed = conclusion == "SUCCESS"
            if not passed and status == "COMPLETED":
                all_pass = False
            results.append({"name": name, "conclusion": conclusion, "status": status})

        return {
            "pr": pr_number,
            "state": data.get("state"),
            "mergeable": data.get("mergeable"),
            "all_pass": all_pass,
            "checks": results,
        }

    def pr_merge(self, pr_number, method="squash"):
        """Merge a PR. Returns result dict."""
        r = self.gh(
            "pr", "merge", str(pr_number),
            f"--{method}", "--delete-branch",
            timeout=30,
        )
        self._log(f"pr_merge(#{pr_number}): {'OK' if r['ok'] else 'FAIL'}")
        return r

    # ── Process Hygiene ─────────────────────────────────────────────

    def cleanup_processes(self):
        """Run process hygiene cleanup. Import from rudy.process_hygiene."""
        try:
            sys.path.insert(0, str(REPO))
            from rudy.process_hygiene import cleanup_session_processes
            result = cleanup_session_processes()
            self._log(f"cleanup: killed={result.get('killed', 0)}, freed={result.get('freed_mb', 0)}MB")
            return result
        except Exception as e:
            self._log(f"cleanup failed: {e}")
            return {"error": str(e)}

    # ── Pre-flight Checks ───────────────────────────────────────────

    def preflight_check(self):
        """Run pre-flight checks before any git operation.

        Checks for locked files that would cause rebase/checkout failures.
        Returns dict with 'safe' boolean and any issues found.
        """
        issues = []

        # Check for common locked files
        lock_candidates = [
            REPO / ".git" / "index.lock",
            REPO / "rudy-data" / "robin-taskqueue" / ".taskqueue.lock",
            REPO / "rudy-data" / "bridge-runner.lock",
        ]
        for lock_file in lock_candidates:
            if lock_file.exists():
                issues.append(f"Locked: {lock_file.name}")

        # Check for dirty working tree in tracked files
        status = self.git_status()
        if status["stdout"]:
            tracked_changes = [
                line for line in status["stdout"].split("\n")
                if line and not line.startswith("??")
            ]
            if tracked_changes:
                issues.append(f"Dirty tree: {len(tracked_changes)} tracked changes")

        result = {"safe": len(issues) == 0, "issues": issues}
        self._log(f"preflight: {'SAFE' if result['safe'] else f'ISSUES: {issues}'}")
        return result


# ── CLI Interface ───────────────────────────────────────────────────

def main():
    """CLI interface for oracle_shell."""
    if len(sys.argv) < 2:
        print("Usage: python -m rudy.oracle_shell <command> [args...]")
        print("Commands: status, branch, log, lint, syntax, ci, preflight,")
        print("          pr-status <N>, pr-merge <N>, cleanup")
        sys.exit(1)

    sh = OracleShell(session=0)
    cmd = sys.argv[1]
    result = {}

    if cmd == "status":
        result = sh.git_status()
    elif cmd == "branch":
        result = sh.git_branch()
    elif cmd == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        result = sh.git_log(n)
    elif cmd == "lint":
        result = sh.ci_lint_check(sys.argv[2:] or None)
    elif cmd == "syntax":
        result = sh.ci_syntax_check()
    elif cmd == "ci":
        result = sh.run_ci_local()
    elif cmd == "preflight":
        result = sh.preflight_check()
    elif cmd == "pr-status":
        result = sh.pr_ci_status(int(sys.argv[2]))
    elif cmd == "pr-merge":
        method = sys.argv[3] if len(sys.argv) > 3 else "squash"
        result = sh.pr_merge(int(sys.argv[2]), method)
    elif cmd == "cleanup":
        result = sh.cleanup_processes()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
