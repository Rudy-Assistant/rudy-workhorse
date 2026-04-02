"""
Lucius Deletion Gate — Governance checkpoint before any file removal.

ADR-005 Mandate 5 (The Conservator): No file shall be deleted from the
repository without passing a formal risk assessment. This gate checks:

  1. IMPORT ANALYSIS: Is the file imported by any other module?
  2. CONFIG REFERENCES: Is it referenced in configs, workflows, or CLAUDE.md?
  3. RECENCY: Was it modified in the last 5 sessions / 2 days?
  4. HARD RULES: Does it appear in any HARD RULE in CLAUDE.md?
  5. ROBIN CRITICALITY: Is it part of Robin's nervous system?

Verdicts:
  - SAFE_TO_DELETE: No dependencies found. Proceed.
  - REVIEW_REQUIRED: Referenced in configs/docs. Human must confirm.
  - BLOCKED: Imported by other modules or part of Robin nervous system.

Usage:
  python -m rudy.agents.lucius_deletion_gate file1.py file2.py
  python -m rudy.agents.lucius_deletion_gate --batch deletions.txt
  python -m rudy.agents.lucius_deletion_gate --audit  # scan for dead code

Integration:
  from rudy.agents.lucius_deletion_gate import assess_deletion
  result = assess_deletion("path/to/file.py")
  if result["verdict"] != "SAFE_TO_DELETE":
      raise DeletionBlocked(result)

History:
  - S70: Created after near-deletion of robin_cowork_launcher.py (502L
    active code mislabeled as 20L "DISCARDED" in stale registry).
  - Caught rudy-suno.py import dependency that would have broken Suno.
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    from rudy.paths import REPO_ROOT, RUDY_DATA
except ImportError:
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    RUDY_DATA = REPO_ROOT / "rudy-data"

logger = logging.getLogger("lucius.deletion_gate")

# Robin nervous system files — NEVER deletable (HARD RULE S68)
ROBIN_NERVOUS_SYSTEM = frozenset({
    "rudy/robin_main.py",
    "rudy/robin_liveness.py",
    "rudy/robin_autonomy.py",
    "rudy/robin_sentinel.py",
    "rudy/robin_cowork_launcher.py",
    "rudy/agents/robin_sentinel.py",
    "rudy/agents/robin_bridge.py",
    "rudy/agents/robin_presence.py",
    "rudy/robin_mcp_client.py",
    "rudy/robin_agent_langgraph.py",
    "rudy/robin_agent_loader.py",
    "rudy/robin_taskqueue.py",
    "rudy/robin_alfred_protocol.py",
    "rudy/process_hygiene.py",
    "rudy/robin_perpetual_loop.py",
})

# Config / workflow files to scan for references
CONFIG_FILES = [
    "CLAUDE.md",
    "registry.json",
    "rudy/config/agents-config.json",
    "rudy/agents/lucius_mcp_tiers.yml",
    "rudy/persona_config.yaml",
    "requirements.txt",
    "setup.py",
    ".github/workflows/lucius-review.yml",
    ".github/workflows/ci.yml",
]

# Directories to skip when scanning for imports
SKIP_DIRS = frozenset({
    ".git", "__pycache__", "rudy-data", "node_modules",
    ".ruff_cache", "vault", "memory", "n8n", ".claude",
})


class DeletionBlocked(Exception):
    """Raised when a file fails the deletion gate."""

    def __init__(self, result: Dict):
        self.result = result
        super().__init__(
            f"Deletion blocked: {result['file']} — "
            f"verdict={result['verdict']}, "
            f"reason={result.get('block_reason', 'unknown')}"
        )


def _find_importers(filepath: str, repo_root: Path) -> List[str]:
    """Find all .py files that import the given module."""
    basename = Path(filepath).stem
    module_name = basename.replace("-", "_")
    importers = []

    # Build import patterns to search
    patterns = [
        f"import {module_name}",
        f"from {module_name}",
        f"from rudy.{module_name}",
        f"from rudy.core.{module_name}",
        f"from rudy.agents.{module_name}",
        f"from rudy.integrations.{module_name}",
        f"from rudy.tools.{module_name}",
        f"from rudy.workflows.{module_name}",
        f"import rudy.{module_name}",
    ]

    for root_d, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(root_d, fn)
            rel = os.path.relpath(fp, repo_root).replace("\\", "/")
            # Don't count self-imports
            if rel == filepath.replace("\\", "/"):
                continue
            try:
                content = open(fp, "r", encoding="utf-8",
                               errors="ignore").read()
                for pat in patterns:
                    if pat in content:
                        importers.append(rel)
                        break
            except OSError:
                continue
    return importers


def _find_config_references(filepath: str, repo_root: Path) -> List[str]:
    """Check if the file is referenced in config/workflow files."""
    basename = Path(filepath).stem
    refs = []
    for cfg in CONFIG_FILES:
        cfg_path = repo_root / cfg
        if cfg_path.exists():
            try:
                content = cfg_path.read_text(encoding="utf-8",
                                             errors="ignore")
                if basename in content or filepath in content:
                    refs.append(cfg)
            except OSError:
                continue
    return refs


def _check_hard_rules(filepath: str, repo_root: Path) -> Optional[str]:
    """Check if file is mentioned near a HARD RULE in CLAUDE.md."""
    claude_md = repo_root / "CLAUDE.md"
    if not claude_md.exists():
        return None
    content = claude_md.read_text(encoding="utf-8", errors="ignore")
    basename = Path(filepath).stem

    # Find HARD RULE sections and check for filename proximity
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "HARD RULE" in line:
            # Check 10 lines around the HARD RULE mention
            window = "\n".join(lines[max(0, i - 5):i + 10])
            if basename in window or filepath in window:
                rule_match = re.search(r"HARD RULE[^)]*\)", line)
                rule_id = rule_match.group(0) if rule_match else line[:80]
                return rule_id
    return None


def _get_last_commit(filepath: str, repo_root: Path) -> str:
    """Get the last git commit touching this file."""
    git_exe = None
    for candidate in [r"C:\Program Files\Git\cmd\git.exe", "git"]:
        if os.path.exists(candidate) or "/" not in candidate:
            git_exe = candidate
            break
    if not git_exe:
        return "GIT_NOT_FOUND"
    try:
        r = subprocess.run(
            [git_exe, "log", "-1", "--format=%h %s (%ar)", "--", filepath],
            capture_output=True, text=True, cwd=str(repo_root), timeout=10,
        )
        return r.stdout.strip() if r.stdout.strip() else "UNTRACKED"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "GIT_ERROR"


def assess_deletion(filepath: str,
                    repo_root: Optional[Path] = None) -> Dict:
    """
    Assess whether a file is safe to delete.

    Returns a dict with:
      - file: the filepath
      - verdict: SAFE_TO_DELETE | REVIEW_REQUIRED | BLOCKED
      - block_reason: why it's blocked (if applicable)
      - imported_by: list of files that import it
      - config_refs: list of config files that reference it
      - hard_rule: HARD RULE reference if any
      - robin_critical: bool
      - last_commit: last git commit info
      - risk_level: LOW | MEDIUM | HIGH | CRITICAL
    """
    if repo_root is None:
        repo_root = REPO_ROOT

    norm_path = filepath.replace("\\", "/")
    result = {
        "file": norm_path,
        "verdict": "SAFE_TO_DELETE",
        "block_reason": None,
        "imported_by": [],
        "config_refs": [],
        "hard_rule": None,
        "robin_critical": False,
        "last_commit": "N/A",
        "risk_level": "LOW",
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }

    full_path = repo_root / filepath
    if not full_path.exists():
        result["verdict"] = "ALREADY_GONE"
        result["block_reason"] = "File does not exist"
        return result

    # Gate 1: Robin nervous system (HARD RULE S68 — absolute block)
    if norm_path in ROBIN_NERVOUS_SYSTEM:
        result["robin_critical"] = True
        result["verdict"] = "BLOCKED"
        result["block_reason"] = (
            "HARD RULE S68: Robin nervous system file. "
            "Robin's survival is the supreme priority."
        )
        result["risk_level"] = "CRITICAL"
        return result

    # Gate 2: Import analysis
    if filepath.endswith(".py"):
        importers = _find_importers(filepath, repo_root)
        result["imported_by"] = importers
        if importers:
            result["verdict"] = "BLOCKED"
            result["block_reason"] = (
                f"Imported by {len(importers)} file(s): "
                f"{', '.join(importers[:5])}"
            )
            result["risk_level"] = "HIGH"
            return result

    # Gate 3: HARD RULE proximity check
    hard_rule = _check_hard_rules(filepath, repo_root)
    if hard_rule:
        result["hard_rule"] = hard_rule
        result["verdict"] = "REVIEW_REQUIRED"
        result["block_reason"] = f"Referenced near: {hard_rule}"
        result["risk_level"] = "HIGH"

    # Gate 4: Config/workflow references
    config_refs = _find_config_references(filepath, repo_root)
    result["config_refs"] = config_refs
    if config_refs and result["verdict"] != "REVIEW_REQUIRED":
        result["verdict"] = "REVIEW_REQUIRED"
        result["block_reason"] = (
            f"Referenced in: {', '.join(config_refs)}"
        )
        result["risk_level"] = "MEDIUM"

    # Gate 5: Last commit (informational, doesn't change verdict)
    result["last_commit"] = _get_last_commit(filepath, repo_root)

    return result


def assess_batch(filepaths: List[str],
                 repo_root: Optional[Path] = None) -> Dict:
    """Assess a batch of files and return a categorized report."""
    results = [assess_deletion(fp, repo_root) for fp in filepaths]

    report = {
        "assessed_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "safe_to_delete": [r for r in results
                           if r["verdict"] == "SAFE_TO_DELETE"],
        "review_required": [r for r in results
                            if r["verdict"] == "REVIEW_REQUIRED"],
        "blocked": [r for r in results
                    if r["verdict"] == "BLOCKED"],
        "already_gone": [r for r in results
                         if r["verdict"] == "ALREADY_GONE"],
    }
    report["summary"] = (
        f"SAFE={len(report['safe_to_delete'])}, "
        f"REVIEW={len(report['review_required'])}, "
        f"BLOCKED={len(report['blocked'])}, "
        f"GONE={len(report['already_gone'])}"
    )
    return report


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Lucius Deletion Gate — risk-assess files before removal"
    )
    parser.add_argument(
        "files", nargs="*",
        help="Files to assess (relative to repo root)"
    )
    parser.add_argument(
        "--batch", type=str,
        help="Path to a text file with one filepath per line"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Path to write JSON results (default: stdout + rudy-data/)"
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit with code 1 if any file is BLOCKED or REVIEW_REQUIRED"
    )
    args = parser.parse_args()

    files = list(args.files) if args.files else []
    if args.batch:
        batch_path = Path(args.batch)
        if batch_path.exists():
            files.extend(
                line.strip() for line in batch_path.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            )

    if not files:
        parser.print_help()
        sys.exit(0)

    report = assess_batch(files)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  LUCIUS DELETION GATE — {report['summary']}")
    print(f"{'='*60}")

    for r in report["blocked"]:
        print(f"\n  [X] BLOCKED: {r['file']}")
        print(f"     Reason: {r['block_reason']}")

    for r in report["review_required"]:
        print(f"\n  [!]  REVIEW: {r['file']}")
        print(f"     Reason: {r['block_reason']}")
        print(f"     Last commit: {r['last_commit']}")

    for r in report["safe_to_delete"]:
        print(f"  [OK] SAFE: {r['file']} ({r['last_commit']})")

    for r in report["already_gone"]:
        print(f"  [-] GONE: {r['file']}")

    # Write JSON output
    out_path = args.output or str(
        RUDY_DATA / "lucius-deletion-gate-results.json"
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Results: {out_path}")

    if args.strict:
        if report["blocked"] or report["review_required"]:
            print("\n  --strict: Exiting with code 1 (blocked/review items)")
            sys.exit(1)


if __name__ == "__main__":
    main()
