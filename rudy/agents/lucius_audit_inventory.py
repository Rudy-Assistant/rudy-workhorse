"""
Lucius Fox — Code Inventory & Duplication Audit (ADR-005 Phase 2b, S74).

Extracted from lucius_fox.py to reduce monolith size.
Backward-compat: LuciusFox._audit_code_inventory() and _audit_duplication()
delegate here via thin wrappers.
"""

import os
import re

from datetime import datetime
from pathlib import Path


def extract_imports(content: str) -> list:
    """Extract import statements from Python file content."""
    imports = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("import ") or line.startswith("from "):
            # Strip inline comments
            if " #" in line:
                line = line[: line.index(" #")].strip()
            imports.append(line)
    return imports


def audit_code_inventory(
    rudy_pkg: Path,
    codebase_root: Path,
    log=None,
    warn_fn=None,
) -> dict:
    """Scan all Python files, categorize, measure.

    Returns:
        dict with keys: modules, total_files, total_lines
    """
    if log:
        log.info("Auditing code inventory...")
    inventory = {"modules": {}, "total_files": 0, "total_lines": 0}

    for root, dirs, files in os.walk(rudy_pkg):
        dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
        for f in files:
            if not f.endswith(".py"):
                continue
            fp = Path(root) / f
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                lines = content.count("\n") + 1
                doc = ""
                if '"""' in content:
                    parts = content.split('"""')
                    if len(parts) >= 3:
                        doc = parts[1].strip()[:200]

                rel = str(fp.relative_to(codebase_root))
                inventory["modules"][rel] = {
                    "lines": lines,
                    "size_bytes": fp.stat().st_size,
                    "docstring": doc,
                    "has_tests": "test" in f.lower() or "assert" in content,
                    "imports": extract_imports(content),
                    "last_modified": datetime.fromtimestamp(
                        fp.stat().st_mtime
                    ).isoformat(),
                }
                inventory["total_files"] += 1
                inventory["total_lines"] += lines
            except Exception as e:
                if warn_fn:
                    warn_fn(f"Could not read {fp}: {e}")

    if log:
        log.info(
            "Inventory: %d files, %d lines",
            inventory["total_files"],
            inventory["total_lines"],
        )
    return inventory


def audit_duplication(inventory: dict, log=None) -> list:
    """Find files with overlapping purpose or duplicated code.

    Args:
        inventory: dict from audit_code_inventory()

    Returns:
        list of finding dicts
    """
    if log:
        log.info("Auditing for duplication...")
    findings = []
    if not inventory or not inventory.get("modules"):
        return findings

    name_groups = {}
    for path in inventory["modules"]:
        base = Path(path).stem.lower()
        key = base.replace("robin_", "").replace("rudy_", "")
        name_groups.setdefault(key, []).append(path)

    for key, paths in name_groups.items():
        if len(paths) > 1:
            findings.append({
                "type": "duplication_suspect",
                "severity": "medium",
                "title": f"Possible duplication: {key}",
                "detail": f"Multiple files with similar purpose: {paths}",
                "recommendation": (
                    "Review for consolidation or document why both are needed"
                ),
                "paths": paths,
            })

    for path, info in inventory["modules"].items():
        for imp in info["imports"]:
            if "robin_sentinel" in imp and "agents/sentinel" in path:
                findings.append({
                    "type": "import_overlap",
                    "severity": "low",
                    "title": "Cross-import between sentinel variants",
                    "detail": f"{path} imports from robin_sentinel",
                    "recommendation": "Consolidate sentinel functionality",
                })

    return findings
