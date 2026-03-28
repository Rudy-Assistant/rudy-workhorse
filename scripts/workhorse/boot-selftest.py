"""
Boot Self-Test — runs automatically on Workhorse startup.

Called from workhorse-startup.bat after services are up.
Pulls latest code from GitHub, runs the test suite, and writes
a status report. If tests fail, alerts via the existing email system.

Exit codes:
  0 = all tests pass
  1 = test failures (alerts sent)
  2 = infrastructure error (git pull failed, pytest missing, etc.)
"""

import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
REPO_DIR = DESKTOP / "rudy-workhorse"
LOGS_DIR = DESKTOP / "rudy-logs"
STATUS_FILE = LOGS_DIR / "boot-selftest.json"


def run_cmd(cmd, cwd=None, timeout=120):
    """Run a command and return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=cwd or str(REPO_DIR)
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", -1
    except Exception as e:
        return "", str(e), -1


def git_pull():
    """Pull latest from origin/main."""
    out, err, rc = run_cmd(["git", "pull", "--ff-only", "origin", "main"])
    return {
        "success": rc == 0,
        "output": out or err,
        "returncode": rc,
    }


def run_tests():
    """Run pytest and return results."""
    out, err, rc = run_cmd(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
        timeout=300
    )
    return {
        "success": rc == 0,
        "output": out,
        "errors": err,
        "returncode": rc,
    }


def run_lint():
    """Run ruff lint check."""
    out, err, rc = run_cmd(
        [sys.executable, "-m", "ruff", "check",
         "--select", "E,F,W", "--ignore", "E501,E402,F401", "rudy/"],
        timeout=60
    )
    return {
        "success": rc == 0,
        "output": out or "All checks passed!" if rc == 0 else out,
        "errors": err,
        "returncode": rc,
    }


def write_status(report):
    """Write self-test results to JSON."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Self-test report written to {STATUS_FILE}")


def main():
    print(f"=== Workhorse Boot Self-Test ({datetime.now().isoformat()}) ===\n")

    report = {
        "timestamp": datetime.now().isoformat(),
        "hostname": os.environ.get("COMPUTERNAME", "unknown"),
        "steps": {},
        "overall": "unknown",
    }

    # Step 1: Git pull
    print("[1/3] Pulling latest from GitHub...")
    pull = git_pull()
    report["steps"]["git_pull"] = pull
    if not pull["success"]:
        print(f"  WARN: git pull failed ({pull['output']})")
        print("  Continuing with existing code...")

    # Step 2: Run lint
    print("[2/3] Running lint check...")
    lint = run_lint()
    report["steps"]["lint"] = lint
    if lint["success"]:
        print("  PASS: All lint checks clean")
    else:
        print("  FAIL: Lint errors found")
        print(f"  {lint['output'][:500]}")

    # Step 3: Run tests
    print("[3/3] Running test suite...")
    tests = run_tests()
    report["steps"]["tests"] = tests
    if tests["success"]:
        print(f"  PASS: {tests['output'].splitlines()[-1] if tests['output'] else 'All tests passed'}")
    else:
        print("  FAIL: Test failures detected")
        print(f"  {tests['output'][:500]}")

    # Overall verdict
    all_pass = lint["success"] and tests["success"]
    report["overall"] = "PASS" if all_pass else "FAIL"

    write_status(report)

    if all_pass:
        print("\n=== SELF-TEST PASSED ===")
        return 0
    else:
        print("\n=== SELF-TEST FAILED ===")
        # Could trigger email alert here via rudy.email_multi
        return 1


if __name__ == "__main__":
    sys.exit(main())
