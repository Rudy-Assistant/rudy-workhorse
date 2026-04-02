"""
Lucius Hardcoded Paths Check — Mandate 3: Enforce protocol compliance.

Extracted from lucius_fox.py (Session 72, ADR-005 Phase 2b).
Scans codebase for hardcoded paths that should use rudy.paths.

Usage:
    from rudy.agents.lucius_hardcoded_paths import check_hardcoded_paths
    result = check_hardcoded_paths(codebase_root=Path("..."), rudy_pkg=Path("..."))
    findings = result["findings"]
"""

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("lucius.hardcoded_paths")

# Patterns that should NEVER appear in committed code
HARDCODED_PATH_PATTERNS = [
    r'C:\\Users\\ccimi\\Desktop',
    r'C:/Users/ccimi/Desktop',
    r"C:\\\\Users\\\\ccimi",
    r'~/Desktop/rudy-',
    r'r"C:\\Users',
    r"r'C:\\Users",
]

# Files that legitimately define/document path patterns
EXEMPT_FILES = {"rudy/paths.py", "rudy/agents/lucius_fox.py",
                "rudy/agents/lucius_hardcoded_paths.py"}


def check_hardcoded_paths(codebase_root, rudy_pkg):
    """Scan entire codebase for hardcoded paths that should use rudy.paths.

    Args:
        codebase_root: Path to repo root.
        rudy_pkg: Path to rudy/ package directory.

    Returns:
        dict with 'findings' list.
    """
    log.info("Checking for hardcoded paths...")
    findings = []

    for root, dirs, files in os.walk(rudy_pkg):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            fp = Path(root) / f
            rel = str(fp.relative_to(codebase_root))

            if rel in EXEMPT_FILES:
                continue

            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(content.split("\n"), 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if stripped.startswith('"""') or stripped.startswith("'''"):
                        continue
                    for pattern in HARDCODED_PATH_PATTERNS:
                        if re.search(pattern, line, re.IGNORECASE):
                            findings.append({
                                "type": "hardcoded_path",
                                "severity": "high",
                                "title": f"Hardcoded path: {rel}:{i}",
                                "detail": f"Line {i}: {stripped[:120]}",
                                "recommendation": "Import from rudy.paths",
                            })
                            break
            except Exception:
                pass

    # Also check scripts/
    scripts_dir = codebase_root / "scripts"
    if scripts_dir.exists():
        for fp in scripts_dir.glob("**/*.py"):
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(content.split("\n"), 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    for pattern in HARDCODED_PATH_PATTERNS:
                        if re.search(pattern, line, re.IGNORECASE):
                            rel = str(fp.relative_to(codebase_root))
                            findings.append({
                                "type": "hardcoded_path",
                                "severity": "medium",
                                "title": f"Hardcoded path in script: {rel}:{i}",
                                "detail": f"Line {i}: {stripped[:120]}",
                                "recommendation": "Import from rudy.paths or use dynamic detection",
                            })
                            break
            except Exception:
                pass

    log.info(f"Hardcoded paths check complete: {len(findings)} findings")
    return {"findings": findings}
