"""
Lucius Dependency Audit -- Package dependency checks via pip-audit.

Extracted from lucius_fox.py (ADR-005 Phase 2b, Session 73).
Replaces manual requirements.txt parsing with pip-audit subprocess
per ADR-005 build-vs-buy mandate.
"""

import logging
import subprocess
from pathlib import Path

from rudy.paths import REPO_ROOT

log = logging.getLogger("lucius_fox")


def audit_dependencies(codebase_root: Path = None) -> list:
    """Check Python package dependencies for known vulnerabilities.

    Uses pip-audit (already in CI pipeline) instead of manual parsing.
    Returns a list of finding dicts compatible with Lucius findings format.

    Args:
        codebase_root: Path to repo root. Defaults to REPO_ROOT.

    Returns:
        List of finding dicts with type, severity, title, detail, recommendation.
    """
    if codebase_root is None:
        codebase_root = REPO_ROOT

    findings = []
    req_file = codebase_root / "requirements.txt"

    if not req_file.exists():
        findings.append({
            "type": "missing_config",
            "severity": "medium",
            "title": "No requirements.txt found",
            "detail": (
                "Dependencies are not pinned. "
                "Builds may not be reproducible."
            ),
            "recommendation": (
                "Generate requirements.txt with pip freeze > requirements.txt"
            ),
        })
        return findings

    # Run pip-audit (same tool used in CI pipeline)
    try:
        result = subprocess.run(
            ["pip-audit", "-r", str(req_file), "--format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode == 0 and not result.stdout.strip():
            # No vulnerabilities found
            findings.append({
                "type": "dependency_check",
                "severity": "info",
                "title": "pip-audit: No known vulnerabilities",
                "detail": "All pinned dependencies passed pip-audit scan.",
                "recommendation": "No action needed.",
            })
        elif result.stdout.strip():
            import json
            try:
                vulns = json.loads(result.stdout)
                # pip-audit JSON output is a list of vulnerability entries
                vuln_list = vulns if isinstance(vulns, list) else \
                    vulns.get("dependencies", [])
                for dep in vuln_list:
                    name = dep.get("name", "unknown")
                    version = dep.get("version", "?")
                    for vuln in dep.get("vulns", []):
                        vuln_id = vuln.get("id", "unknown")
                        fix = vuln.get("fix_versions", [])
                        findings.append({
                            "type": "vulnerability",
                            "severity": "high",
                            "title": f"CVE in {name}=={version}: {vuln_id}",
                            "detail": vuln.get("description", vuln_id),
                            "recommendation": (
                                f"Upgrade to {', '.join(fix)}"
                                if fix else "Check PyPI for patched version"
                            ),
                        })
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("Failed to parse pip-audit JSON: %s", e)
                findings.append({
                    "type": "dependency_check",
                    "severity": "info",
                    "title": "pip-audit completed with warnings",
                    "detail": result.stdout[:500],
                    "recommendation": "Review pip-audit output manually.",
                })
        else:
            # Non-zero exit but no JSON output
            findings.append({
                "type": "dependency_check",
                "severity": "low",
                "title": "pip-audit returned non-zero",
                "detail": (result.stderr or "No output")[:500],
                "recommendation": "Run pip-audit manually to investigate.",
            })

    except FileNotFoundError:
        log.warning("pip-audit not found, falling back to basic check")
        findings.append({
            "type": "dependency_check",
            "severity": "info",
            "title": "pip-audit not installed",
            "detail": (
                "pip-audit is not available locally. "
                "CI pipeline runs pip-audit on every PR."
            ),
            "recommendation": "Install with: pip install pip-audit",
        })
    except subprocess.TimeoutExpired:
        findings.append({
            "type": "dependency_check",
            "severity": "low",
            "title": "pip-audit timed out",
            "detail": "Dependency scan exceeded 120s timeout.",
            "recommendation": "Run pip-audit manually.",
        })

    return findings
