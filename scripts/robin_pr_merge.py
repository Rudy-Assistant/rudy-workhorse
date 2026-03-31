#!/usr/bin/env python3
"""
Robin PR/Merge Skill — Automated CI fix and merge pipeline.

Batman directive (Session 35): This is Robin's job, not Alfred's.
Alfred should never burn cloud tokens on lint fixes, CI monitoring,
or merge mechanics. This script handles the full lifecycle.

Usage:
    python scripts/robin_pr_merge.py [--pr NUMBER] [--auto-fix] [--merge]

Phases:
    1. LINT  — Run ruff, auto-fix if --auto-fix
    2. PUSH  — Commit fixes and push
    3. WAIT  — Poll CI until all checks pass (or timeout)
    4. MERGE — Squash-merge if --merge and CI green
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)

# CI check names we expect to pass
EXPECTED_CHECKS = {"lint", "batcave-paths", "bandit", "pip-audit", "smoke-test"}
MAX_CI_WAIT_SEC = 600  # 10 minutes
CI_POLL_INTERVAL = 30  # seconds


def run(cmd, check=False, timeout=30):
    """Run a command and return (returncode, stdout, stderr)."""
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        print(f"FAIL: {' '.join(cmd)}")
        print(r.stderr[:500])
        sys.exit(1)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def get_current_branch():
    _, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return branch


def get_open_pr():
    """Find the open PR for the current branch, if any."""
    _, out, _ = run(["gh", "pr", "view", "--json", "number,state,title"])
    if out:
        try:
            data = json.loads(out)
            if data.get("state") == "OPEN":
                return data
        except json.JSONDecodeError:
            pass
    return None


# ---- Phase 1: Lint ----

def phase_lint(auto_fix=False):
    """Run ruff lint. Optionally auto-fix."""
    print("\n=== Phase 1: Lint Check ===")
    ruff_cmd = [sys.executable, "-m", "ruff", "check", "rudy/",
                "--select", "E,F,W", "--ignore", "E501,E402,F401"]

    code, out, err = run(ruff_cmd)
    if code == 0:
        print("PASS: All lint checks clean")
        return True

    print(f"LINT ISSUES:\n{out or err}")

    if auto_fix:
        print("Attempting auto-fix with ruff --fix...")
        fix_cmd = ruff_cmd + ["--fix"]
        run(fix_cmd)
        # Re-check
        code2, out2, _ = run(ruff_cmd)
        if code2 == 0:
            print("AUTO-FIX: All issues resolved")
            return True
        else:
            print(f"REMAINING ISSUES (manual fix needed):\n{out2}")
            return False
    return False


# ---- Phase 2: Commit & Push ----

def phase_push(session_num=0):
    """Stage lint fixes, commit, and push."""
    print("\n=== Phase 2: Commit & Push ===")
    _, status, _ = run(["git", "status", "--porcelain"])
    if not status:
        print("Nothing to commit")
        return True

    # Stage only Python files in rudy/
    run(["git", "add", "rudy/"])

    msg = (f"Session {session_num}: Auto-fix lint issues (Robin)\n\n"
           f"Automated by robin_pr_merge.py\n\n"
           f"Co-Authored-By: Robin <robin@batcave.local>")

    code, out, err = run(["git", "commit", "-m", msg])
    if code != 0:
        print(f"Commit failed: {err}")
        return False
    print(f"Committed: {out.split(chr(10))[0]}")

    branch = get_current_branch()
    code, out, err = run(["git", "push", "origin", branch], timeout=60)
    if code != 0:
        print(f"Push failed: {err}")
        return False
    print(f"Pushed to {branch}")
    return True


# ---- Phase 3: Wait for CI ----

def phase_wait_ci(pr_number=None):
    """Poll CI checks until all pass or timeout."""
    print("\n=== Phase 3: Wait for CI ===")
    target = f"{pr_number}" if pr_number else ""
    start = time.time()

    while time.time() - start < MAX_CI_WAIT_SEC:
        cmd = ["gh", "pr", "checks"]
        if target:
            cmd.append(target)

        code, out, _ = run(cmd, timeout=30)
        if code != 0 and not out:
            print("  Waiting for checks to start...")
            time.sleep(CI_POLL_INTERVAL)
            continue

        lines = [l for l in out.strip().split("\n") if l.strip()]
        results = {}
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 2:
                name = parts[0].strip()
                status = parts[1].strip().lower()
                results[name] = status

        passed = sum(1 for v in results.values() if v == "pass")
        failed = sum(1 for v in results.values() if v == "fail")
        pending = sum(1 for v in results.values() if v not in ("pass", "fail"))

        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] {passed} pass, {failed} fail, {pending} pending")

        if failed > 0:
            print("FAIL: CI has failures:")
            for name, status in results.items():
                if status == "fail":
                    print(f"  FAIL: {name}")
            return False

        if pending == 0 and passed > 0:
            print(f"PASS: All {passed} checks green!")
            return True

        time.sleep(CI_POLL_INTERVAL)

    print(f"TIMEOUT: CI did not complete in {MAX_CI_WAIT_SEC}s")
    return False


# ---- Phase 4: Merge ----

def phase_merge(pr_number=None):
    """Squash-merge the PR."""
    print("\n=== Phase 4: Merge ===")
    cmd = ["gh", "pr", "merge", "--squash"]
    if pr_number:
        cmd.append(str(pr_number))

    code, out, err = run(cmd, timeout=60)
    if code == 0:
        print("MERGED successfully!")
        # Switch to main and pull
        run(["git", "checkout", "main"])
        run(["git", "pull", "origin", "main"], timeout=60)
        return True
    else:
        print(f"Merge failed: {err}")
        return False


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(
        description="Robin PR/Merge Skill — automated CI fix and merge")
    parser.add_argument("--pr", type=int, help="PR number (auto-detects if omitted)")
    parser.add_argument("--auto-fix", action="store_true",
                        help="Auto-fix lint issues with ruff --fix")
    parser.add_argument("--merge", action="store_true",
                        help="Merge PR after CI passes")
    parser.add_argument("--session", type=int, default=0,
                        help="Session number for commit messages")
    parser.add_argument("--lint-only", action="store_true",
                        help="Only run lint, don't push/wait/merge")
    args = parser.parse_args()

    branch = get_current_branch()
    print(f"Robin PR/Merge Skill")
    print(f"  Branch: {branch}")
    print(f"  Auto-fix: {args.auto_fix}")
    print(f"  Merge: {args.merge}")

    # Detect PR
    pr_num = args.pr
    if not pr_num:
        pr = get_open_pr()
        if pr:
            pr_num = pr["number"]
            print(f"  PR: #{pr_num} ({pr['title']})")
        else:
            print("  PR: none found for this branch")

    # Phase 1
    lint_ok = phase_lint(auto_fix=args.auto_fix)
    if args.lint_only:
        sys.exit(0 if lint_ok else 1)

    # Phase 2: push if there are fixes
    if args.auto_fix:
        phase_push(session_num=args.session)

    # Phase 3: wait for CI
    if pr_num:
        ci_ok = phase_wait_ci(pr_num)
    else:
        print("SKIP: No PR to check CI against")
        ci_ok = lint_ok

    # Phase 4: merge
    if args.merge and ci_ok and pr_num:
        phase_merge(pr_num)
    elif args.merge and not ci_ok:
        print("SKIP MERGE: CI not green")
    elif not args.merge:
        print("SKIP MERGE: --merge not specified")

    # Summary
    print(f"\n{'='*40}")
    print(f"Lint: {'PASS' if lint_ok else 'FAIL'}")
    if pr_num:
        print(f"CI: {'PASS' if ci_ok else 'FAIL'}")
    print(f"{'='*40}")
    sys.exit(0 if (lint_ok and ci_ok) else 1)


if __name__ == "__main__":
    main()
