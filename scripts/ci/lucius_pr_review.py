#!/usr/bin/env python3
"""
Lucius Fox CI — Batcave-specific PR checks.

ADR-005 COMPLIANT: Security scanning delegated to bandit. PR commenting
delegated to reviewdog. Dependency auditing delegated to pip-audit.

This script handles ONLY Batcave-specific checks that have no standard
tool equivalent:
  1. Hardcoded path detection (Batcave user paths)  # lucius-exempt: docstring
  2. Import hygiene (direct path construction vs rudy.paths)

Usage:
    python scripts/ci/lucius_pr_review.py              # diffs HEAD against origin/main
    python scripts/ci/lucius_pr_review.py --base main   # explicit base
    GITHUB_TOKEN=... PR_NUMBER=42 python scripts/ci/lucius_pr_review.py  # post comment
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime


# ── Batcave-specific path patterns (no standard tool equivalent) ──────
# SAFETY: These are detection PATTERNS, not actual path usage.

HARDCODED_PATH_PATTERNS = [  # SAFETY: detection patterns, not path usage
    r'C:\\Users\\ccimi\\Desktop',   # lucius-exempt: detection pattern
    r'C:/Users/ccimi/Desktop',      # lucius-exempt: detection pattern
    r"C:\\\\Users\\\\ccimi",        # lucius-exempt: detection pattern
    r'~/Desktop/rudy-',             # lucius-exempt: detection pattern
    r'r"C:\\Users',                 # lucius-exempt: detection pattern
    r"r'C:\\Users",                 # lucius-exempt: detection pattern
]

# Safety comments that exempt a line from findings
SAFETY_EXEMPTIONS = [
    "lucius-exempt",
    "# SAFETY:",
    "# nosec",
    "detection pattern",
]


def parse_diff(diff_text: str) -> list[tuple[str, int, str]]:
    """Parse unified diff into (filepath, line_number, line_content) tuples."""
    results = []
    current_file = ""
    line_num = 0
    for line in diff_text.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("@@"):
            match = re.search(r'\+(\d+)', line)
            line_num = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            results.append((current_file, line_num, line[1:]))
            line_num += 1
        elif not line.startswith("-"):
            line_num += 1
    return results


def is_exempt(line: str) -> bool:
    """Check if a line has a safety exemption comment."""
    return any(exemption.lower() in line.lower() for exemption in SAFETY_EXEMPTIONS)


def check_hardcoded_paths(added_lines: list) -> list[dict]:
    """Check for hardcoded Batcave paths that should use rudy.paths."""
    findings = []
    for filepath, line_num, line in added_lines:
        # Only check Python files — docs/markdown may reference paths legitimately
        if not filepath.endswith(".py"):
            continue
        if is_exempt(line):
            continue
        for pattern in HARDCODED_PATH_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "type": "hardcoded_path",
                    "severity": "high",
                    "file": filepath,
                    "line": line_num,
                    "title": "Hardcoded path detected",
                    "detail": line.strip()[:120],
                    "recommendation": "Import from rudy.paths instead of hardcoding",
                })
    return findings


def check_import_hygiene(added_lines: list) -> list[dict]:
    """Check for direct path construction that should use rudy.paths."""
    findings = []
    for filepath, line_num, line in added_lines:
        if not filepath.endswith(".py"):
            continue
        if filepath.endswith("rudy/paths.py"):
            continue
        if is_exempt(line):
            continue
        # SAFETY: detection pattern for direct path construction
        if re.search(r'Path\s*\(\s*["\'].*Desktop', line.strip()):
            findings.append({
                "type": "import_hygiene",
                "severity": "medium",
                "file": filepath,
                "line": line_num,
                "title": "Direct path construction (should use rudy.paths)",
                "detail": line.strip()[:120],
                "recommendation": "Use DESKTOP, REPO_ROOT, etc. from rudy.paths",
            })
    return findings


def get_diff(base: str = "main") -> str:
    """Get the diff between HEAD and the base branch."""
    for ref in [f"origin/{base}", base]:
        try:
            result = subprocess.run(
                ["git", "diff", f"{ref}...HEAD"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except Exception:
            continue

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass

    return ""


def format_report(findings: list) -> str:
    """Format findings into a markdown report."""
    high = sum(1 for f in findings if f["severity"] == "high")
    medium = sum(1 for f in findings if f["severity"] == "medium")
    total = len(findings)

    verdict = "APPROVED" if high == 0 else "CHANGES REQUESTED"
    icon = "\u2705" if high == 0 else "\u274c"

    lines = [
        f"## {icon} Lucius Review — Batcave Paths: {verdict}",
        f"**Findings:** {total} total ({high} high, {medium} medium)",
        "",
        "*Security scanning by bandit. Dependency audit by pip-audit. "
        "This check covers Batcave-specific path hygiene only (ADR-005).*",
        "",
    ]

    if not findings:
        lines.append("No Batcave path issues found. Clean diff.")
    else:
        for sev in ["high", "medium"]:
            sev_findings = [f for f in findings if f["severity"] == sev]
            if not sev_findings:
                continue
            lines.append(f"### {sev.upper()} ({len(sev_findings)})")
            for f in sev_findings:
                loc = f"{f['file']}:{f['line']}" if f.get("line") else f["file"]
                lines.append(f"- **{f['title']}** (`{loc}`)")
                lines.append(f"  `{f['detail']}`")
                if f.get("recommendation"):
                    lines.append(f"  *Recommendation:* {f['recommendation']}")
            lines.append("")

    lines.append(f"\n---\n*Lucius Fox CI (ADR-005 compliant) — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    return "\n".join(lines)


def post_pr_comment(report: str) -> bool:
    """Post the review as a PR comment via GitHub API."""
    token = os.environ.get("GITHUB_TOKEN")
    pr_number = os.environ.get("PR_NUMBER")
    repo = os.environ.get("GITHUB_REPOSITORY", "Rudy-Assistant/rudy-workhorse")

    if not token or not pr_number:
        return False

    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    data = json.dumps({"body": report}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status == 201
    except Exception as e:
        print(f"Warning: Failed to post PR comment: {e}", file=sys.stderr)
        return False


def main():
    base = "main"
    if "--base" in sys.argv:
        idx = sys.argv.index("--base")
        if idx + 1 < len(sys.argv):
            base = sys.argv[idx + 1]

    print(f"Lucius CI (ADR-005): Batcave path check against {base}...")

    diff_text = get_diff(base)
    if not diff_text:
        print("No diff found — nothing to review.")
        sys.exit(0)

    added_lines = parse_diff(diff_text)
    print(f"Parsed {len(added_lines)} added lines from diff.")

    # Run Batcave-specific checks only (security delegated to bandit)
    findings = []
    findings.extend(check_hardcoded_paths(added_lines))
    findings.extend(check_import_hygiene(added_lines))

    report = format_report(findings)
    print(report)

    # Post as PR comment if credentials available
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("PR_NUMBER"):
        if post_pr_comment(report):
            print("Posted review comment to PR.")
        else:
            print("Failed to post PR comment.", file=sys.stderr)

    # Exit non-zero if HIGH findings exist
    high_count = sum(1 for f in findings if f["severity"] == "high")
    if high_count > 0:
        print(f"\nBLOCKED: {high_count} high-severity finding(s). Fix before merging.")
        sys.exit(1)
    else:
        print("\nPASS: No Batcave path issues.")
        sys.exit(0)


if __name__ == "__main__":
    main()
