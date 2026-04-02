"""
Lucius Import Hygiene — Mandate 3: Enforce rudy.paths usage.

Extracted from lucius_fox.py (Session 72, ADR-005 Phase 2b).
Checks that modules use rudy.paths for path resolution instead of
constructing paths from __file__ or environment variables.

Usage:
    from rudy.agents.lucius_import_hygiene import check_import_hygiene
    result = check_import_hygiene(codebase_root=Path("..."), rudy_pkg=Path("..."))
    findings = result["findings"]
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("lucius.import_hygiene")


def check_import_hygiene(codebase_root, rudy_pkg):
    """Check that modules use rudy.paths for path resolution.

    Args:
        codebase_root: Path to repo root.
        rudy_pkg: Path to rudy/ package directory.

    Returns:
        dict with 'findings' list.
    """
    log.info("Checking import hygiene...")
    findings = []

    for root, dirs, files in os.walk(rudy_pkg):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py") or f == "paths.py":
                continue
            fp = Path(root) / f
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                rel = str(fp.relative_to(codebase_root))

                uses_file_path = "Path(__file__)" in content
                imports_rudy_paths = (
                    "from rudy.paths" in content or "import rudy.paths" in content
                )
                is_bootstrap = (
                    "sys.path.insert" in content and "Path(__file__)" in content
                )

                if uses_file_path and not imports_rudy_paths and not is_bootstrap:
                    findings.append({
                        "type": "import_hygiene",
                        "severity": "medium",
                        "title": f"{rel} uses Path(__file__) without rudy.paths",
                        "detail": "Module constructs paths from __file__ instead of importing canonical paths",
                        "recommendation": "Import from rudy.paths for consistency and portability",
                    })

                if ("USERPROFILE" in content or "os.path.expanduser" in content) and not imports_rudy_paths:
                    if f != "__init__.py":
                        findings.append({
                            "type": "import_hygiene",
                            "severity": "low",
                            "title": f"{rel} resolves home directory without rudy.paths",
                            "detail": "Uses USERPROFILE/expanduser directly",
                            "recommendation": "Use rudy.paths.HOME or rudy.paths.DESKTOP",
                        })

            except Exception:
                pass

    log.info(f"Import hygiene check complete: {len(findings)} findings")
    return {"findings": findings}
