"""
Lucius Reinvention Check — ADR-005 Mandate 4: Prevent wheel-reinvention.

Extracted from lucius_fox.py (Session 72, ADR-005 Phase 2b).
Scans codebase for custom code that duplicates standard tools.

Usage:
    from rudy.agents.lucius_reinvention_check import check_reinvention
    result = check_reinvention(codebase_root=Path("..."), rudy_pkg=Path("..."))
    findings = result["findings"]
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("lucius.reinvention_check")

# File-level co-occurrence patterns: when multiple strings appear in
# the same file, it strongly suggests reinvention of a standard tool.
REINVENTION_INDICATORS = [
    # Custom security scanning (bandit does all of these)
    (
        [r"\\beval\\s", "re.search"],
        "bandit",
        "Custom regex to detect eval() -- bandit B307 does this natively",
    ),
    (
        [r"\\bexec\\s", "re.search"],
        "bandit",
        "Custom regex to detect exec() -- bandit B102 does this natively",
    ),
    (
        ["security_patterns", "re.search", "finding"],
        "bandit",
        "Custom security pattern scanner -- bandit does this natively with 68+ checks",
    ),
    # Custom dependency version checking (pip-audit does this)
    (
        ["Check PyPI for latest version"],
        "pip-audit",
        "Manual dependency note -- pip-audit automates CVE checking",
    ),
    # Custom PR comment posting (reviewdog / Actions do this)
    (
        ["api.github.com", "issues", "comments", "urllib"],
        "reviewdog / GitHub Actions",
        "Custom PR comment posting -- reviewdog bridges any linter to PRs",
    ),
    # Custom dead-code detection
    (
        ["unused", "import", "AST", "remove"],
        "vulture / ruff F401",
        "Custom unused import detection -- ruff F401 already in CI",
    ),
]

# Files that define detection patterns (not consumers)
ECONOMIST_EXEMPT = {
    "rudy/agents/lucius_fox.py",
    "rudy/agents/lucius_reinvention_check.py",
    "rudy/paths.py",
}


def _scan_for_reinvention(rel_path, content_lower, indicators, is_ci=False):
    """Check a file's content against reinvention indicators.

    Uses co-occurrence matching: all required strings must appear in the
    file for the indicator to trigger.

    Returns:
        list of finding dicts.
    """
    findings = []
    for required_strings, tool, desc in indicators:
        if all(s.lower() in content_lower for s in required_strings):
            prefix = "CI script reinvention" if is_ci else "Possible reinvention"
            findings.append({
                "type": "reinvention",
                "severity": "medium",
                "title": f"{prefix}: {rel_path}",
                "detail": desc,
                "recommendation": (
                    f"Migrate to {tool}. "
                    "See ADR-005 and KNOWN_REPLACEMENTS registry. "
                    "Custom code should only exist where no standard tool applies."
                ),
            })
    return findings


def check_reinvention(codebase_root, rudy_pkg):
    """Scan codebase for patterns that reinvent standard tools.

    ADR-005: Every custom check, scanner, or utility must be justified
    against standard tool replacements.

    Args:
        codebase_root: Path to repo root.
        rudy_pkg: Path to rudy/ package directory.

    Returns:
        dict with 'findings' list.
    """
    log.info("Checking for wheel-reinvention (Mandate 4)...")
    findings = []

    for root, dirs, files in os.walk(rudy_pkg):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            fp = Path(root) / f
            rel = str(fp.relative_to(codebase_root))

            if rel in ECONOMIST_EXEMPT:
                continue

            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                content_lower = content.lower()
                findings.extend(
                    _scan_for_reinvention(rel, content_lower, REINVENTION_INDICATORS)
                )
            except Exception:
                pass

    # Also check scripts/ci/ for custom CI that overlaps with Actions
    ci_dir = codebase_root / "scripts" / "ci"
    if ci_dir.exists():
        for fp in ci_dir.glob("*.py"):
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                rel = str(fp.relative_to(codebase_root))
                content_lower = content.lower()
                findings.extend(
                    _scan_for_reinvention(
                        rel, content_lower, REINVENTION_INDICATORS, is_ci=True
                    )
                )
            except Exception:
                pass

    log.info(f"Reinvention check complete: {len(findings)} findings")
    return {"findings": findings}
