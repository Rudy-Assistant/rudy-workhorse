"""
Lucius Diff Review -- Diff and file quality review.

Extracted from lucius_fox.py (ADR-005 Phase 2b, Session 71).
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from rudy.paths import REPO_ROOT

log = logging.getLogger("lucius_fox")

# Hardcoded path patterns (shared with lucius_fox)
HARDCODED_PATH_PATTERNS = [
    r"C:\\Users\\",
    r"/home/\w+/",
    r"~/Desktop",
    r"~/Documents",
    r'r"C:',
    r"r'C:",
]


def review_diff(
    diff_text: str,
    branch: str = "unknown",
    reviews_dir: Path = None,
    hardcoded_patterns: list = None,
) -> dict:
    """Review a git diff and produce a Lucius Review Record.

    Checks:
        1. Hardcoded paths (must use rudy.paths)
        2. Security anti-patterns (eval, exec, shell=True)
        3. Overly broad except clauses
        4. Missing docstrings on new functions/classes
        5. Dangerous git add patterns

    Args:
        diff_text: The git diff text to review.
        branch: Branch name for the review record.
        reviews_dir: Directory to save review records.
        hardcoded_patterns: Custom path patterns to check.

    Returns:
        dict with review_id, verdict, findings_count, and findings.
    """
    if reviews_dir is None:
        reviews_dir = REPO_ROOT / "vault" / "Reviews"
    if hardcoded_patterns is None:
        hardcoded_patterns = HARDCODED_PATH_PATTERNS

    reviews_dir.mkdir(parents=True, exist_ok=True)
    findings = []

    log.info("Reviewing diff for branch: %s", branch)
    review_id = f"LRR-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Parse added lines from diff
    added_lines = []
    current_file = ""
    for line in diff_text.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            added_lines.append((current_file, line[1:]))

    # Check 1: Hardcoded paths
    for filepath, line in added_lines:
        for pattern in hardcoded_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "type": "hardcoded_path",
                    "severity": "high",
                    "title": f"Hardcoded path in {filepath}",
                    "detail": f"Line: {line.strip()[:120]}",
                    "recommendation": "Import from rudy.paths instead of hardcoding",
                })

    # Check 2: Security anti-patterns
    security_patterns = [
        (r'\beval\s*\(', "eval() usage -- potential code injection"),
        (r'\bexec\s*\(', "exec() usage -- potential code injection"),
        (r'shell\s*=\s*True', "shell=True in subprocess -- potential injection"),
        (r'pickle\.loads?\(', "pickle.load -- potential deserialization attack"),
        (r'__import__\s*\(', "Dynamic __import__ -- review for necessity"),
    ]
    for filepath, line in added_lines:
        if not filepath.endswith(".py"):
            continue
        for pattern, desc in security_patterns:
            if re.search(pattern, line):
                findings.append({
                    "type": "security_concern",
                    "severity": "high",
                    "title": f"Security: {desc}",
                    "detail": f"File: {filepath}, Line: {line.strip()[:120]}",
                    "recommendation": "Review for necessity and add safety comment",
                })

    # Check 3: Overly broad exception handling
    for filepath, line in added_lines:
        if not filepath.endswith(".py"):
            continue
        stripped = line.strip()
        if stripped == "except:" or stripped == "except Exception:":
            findings.append({
                "type": "broad_except",
                "severity": "low",
                "title": f"Broad except clause in {filepath}",
                "detail": f"Line: {stripped}",
                "recommendation": "Catch specific exceptions where possible",
            })

    # Check 4: Missing docstrings on new functions/classes
    for filepath, line in added_lines:
        if not filepath.endswith(".py"):
            continue
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("class "):
            findings.append({
                "type": "review_hint",
                "severity": "info",
                "title": f"New definition in {filepath}",
                "detail": f"{stripped[:80]}",
                "recommendation": "Verify docstring and type hints are present",
            })

    # Check 5: git add -A (dangerous in Robin context)
    for filepath, line in added_lines:
        if "git add -A" in line or "git add ." in line:
            findings.append({
                "type": "dangerous_git",
                "severity": "high",
                "title": f"Unrestricted git add in {filepath}",
                "detail": f"Line: {line.strip()[:120]}",
                "recommendation": "Use explicit file paths instead of git add -A",
            })

    # Generate verdict
    high_count = sum(1 for f in findings if f.get("severity") == "high")
    verdict = "approve" if high_count == 0 else "request_changes"

    record = {
        "review_id": review_id,
        "timestamp": datetime.now().isoformat(),
        "branch": branch,
        "verdict": verdict,
        "findings_count": len(findings),
        "high_severity": high_count,
        "findings": findings,
    }

    review_file = reviews_dir / f"{review_id}.json"
    with open(review_file, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)

    log.info("Review verdict: %s", verdict)
    return record


def review_files(
    files: list,
    codebase_root: Path = None,
    reviews_dir: Path = None,
    hardcoded_patterns: list = None,
) -> dict:
    """Review specific files for quality issues.

    Runs quality checks on file contents directly.

    Args:
        files: List of file paths (relative to repo root) to review.
        codebase_root: Root of the rudy package.
        reviews_dir: Directory to save review records.
        hardcoded_patterns: Custom path patterns to check.

    Returns:
        dict with review_id, verdict, findings_count, and findings.
    """
    if codebase_root is None:
        codebase_root = REPO_ROOT / "rudy"
    if reviews_dir is None:
        reviews_dir = REPO_ROOT / "vault" / "Reviews"
    if hardcoded_patterns is None:
        hardcoded_patterns = HARDCODED_PATH_PATTERNS

    reviews_dir.mkdir(parents=True, exist_ok=True)
    findings = []

    log.info("Reviewing %d files...", len(files))

    for filepath in files:
        fp = codebase_root / filepath
        if not fp.exists():
            log.warning("File not found: %s", filepath)
            continue
        if not filepath.endswith(".py"):
            continue

        content = fp.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")

        # Check hardcoded paths
        for i, line in enumerate(lines, 1):
            for pattern in hardcoded_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append({
                        "type": "hardcoded_path",
                        "severity": "high",
                        "title": f"Hardcoded path in {filepath}:{i}",
                        "detail": f"Line {i}: {line.strip()[:120]}",
                        "recommendation": "Import from rudy.paths instead",
                    })

        # Check for functions without docstrings
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if (stripped.startswith("def ") or stripped.startswith("class ")) \
                    and not stripped.startswith("def _"):
                has_docstring = False
                for j in range(i, min(i + 3, len(lines))):
                    next_line = lines[j].strip()
                    if next_line.startswith('\"\"\"') or next_line.startswith("\'\'\'"):
                        has_docstring = True
                        break
                    if next_line and not next_line.startswith("#"):
                        break
                if not has_docstring:
                    findings.append({
                        "type": "missing_docstring",
                        "severity": "low",
                        "title": f"Missing docstring: {filepath}:{i}",
                        "detail": f"{stripped[:80]}",
                        "recommendation": "Add a docstring explaining purpose and parameters",
                    })

        # Check for imports not from rudy.paths when using path patterns
        if "Desktop" in content and "from rudy.paths" not in content:
            findings.append({
                "type": "path_import_missing",
                "severity": "medium",
                "title": f"{filepath} references 'Desktop' without importing rudy.paths",
                "detail": "File may have hardcoded path constructions",
                "recommendation": "Import paths from rudy.paths",
            })

    # Generate review record
    review_id = f"LRR-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    high_count = sum(1 for f in findings if f.get("severity") == "high")
    verdict = "approve" if high_count == 0 else "request_changes"

    record = {
        "review_id": review_id,
        "timestamp": datetime.now().isoformat(),
        "files_reviewed": files,
        "verdict": verdict,
        "findings_count": len(findings),
        "high_severity": high_count,
        "findings": findings,
    }

    review_file = reviews_dir / f"{review_id}.json"
    with open(review_file, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)

    log.info("File review %s: %s", review_id, verdict)
    return record
