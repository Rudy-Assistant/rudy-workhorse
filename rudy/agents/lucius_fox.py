"""
Lucius Fox — The Batcave's Librarian, Gatekeeper, and Quality Conscience.

ADR-004 (2026-03-29): Lucius is the single source of truth for repository
structure, canonical documentation, and operational protocol compliance.

Four Mandates:
    1. The Library  — Know everything that exists (audit, inventory, locate)
    2. The Gate     — Nothing merges without review (diff review, quality checks)
    3. The Conscience — Enforce protocol compliance (hygiene, branch governance)
    4. The Economist — Prevent reinvention (build-vs-buy, ADR-005)

Execution model:
    lucius = LuciusFox()
    lucius.execute(mode="full_audit")       # Weekly scheduled audit
    lucius.execute(mode="review_diff", diff_text="...", branch="feat/x")
    lucius.execute(mode="review_files", files=["rudy/foo.py"])
    lucius.execute(mode="branch_governance")
    lucius.execute(mode="hygiene_check")
    lucius.execute(mode="locate", query="sentinel")

Lucius Review Record (LRR):
    Every review produces a JSON record in rudy-data/lucius-reviews/ with:
    - review_id, timestamp, verdict (approve/reject/request_changes)
    - findings (list), severity counts, recommendations

ADR-002: Built as AgentBase subclass. Uses existing infrastructure.
"""

import json
import os
import re
import subprocess
import sys

from datetime import datetime
from pathlib import Path

from rudy.paths import REPO_ROOT, RUDY_DATA, BATCAVE_VAULT
from . import AgentBase


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Patterns moved to lucius_hardcoded_paths.py (S72 extraction)
from rudy.agents.lucius_hardcoded_paths import HARDCODED_PATH_PATTERNS  # noqa: F401,E402

# Protected branches that Robin/automated agents must never push to
PROTECTED_BRANCHES = frozenset({"main", "master"})

# Known repo hygiene rules
REQUIRED_DOCS = [
    ("CLAUDE.md", "Institutional memory"),
    ("README.md", "Project README"),
    ("SOLE-SURVIVOR-PROTOCOL.md", "Recovery protocol"),
    ("docs/SESSION-HANDOFF.md", "Session handoff brief"),
]

# Ruff lint command (repo standard)
RUFF_ARGS = ["--select", "E,F,W", "--ignore", "E501,E402,F401"]

# ──────────────────────────────────────────────────────────────────────
# MANDATE 4: THE ECONOMIST — Build-vs-Buy Registry (ADR-005)
# ──────────────────────────────────────────────────────────────────────
# Maps common custom code patterns to their standard tool replacements.
# "KEEP" entries document justified custom implementations.
# "REPLACE" entries indicate custom code that should be migrated.
# "SLIM" entries indicate code that should delegate to standard tools.

KNOWN_REPLACEMENTS = {
    # Pattern: (standard tool, verdict, justification)

    # Security scanning
    "eval(": ("bandit B307", "REPLACE", "bandit detects eval/exec with context"),
    "exec(": ("bandit B102", "REPLACE", "bandit detects exec with context"),
    "shell=True": ("bandit B602", "REPLACE", "bandit detects subprocess injection"),
    "pickle.load": ("bandit B301", "REPLACE", "bandit detects pickle deserialization"),
    "__import__": ("bandit B302", "REPLACE", "bandit detects dynamic imports"),

    # Linting
    "except:": ("ruff E722", "REPLACE", "ruff already catches bare except"),
    "except Exception:": ("pylint W0703", "REPLACE", "pylint catches broad-except"),
    "missing docstring": ("ruff D100-D107", "REPLACE", "ruff pydocstyle checks"),

    # Dependency auditing
    "check PyPI for latest": ("pip-audit", "REPLACE", "pip-audit checks CVE databases directly"),
    "known CVEs": ("safety / pip-audit", "REPLACE", "dedicated CVE scanners"),

    # CI / PR review
    "parse unified diff": ("reviewdog", "SLIM", "reviewdog adapts any linter to PR comments"),
    "post PR comment": ("reviewdog / GitHub Actions", "SLIM", "standard CI integration pattern"),

    # Dead code
    "unused import": ("ruff F401 / vulture", "REPLACE", "ruff already catches unused imports"),

    # Complexity
    "cyclomatic complexity": ("radon / ruff C901", "REPLACE", "standard complexity tools"),

    # Justified custom code
    "rudy.paths": ("N/A", "KEEP", "repo-specific path constants, no generic equivalent"),
    "robin_alfred_protocol": ("N/A", "KEEP", "air-gapped filesystem IPC, no broker available"),
    "robin_taskqueue": ("N/A", "KEEP", "offline priority queue, Celery/RQ need daemon"),
    "batcave_memory": ("N/A", "KEEP", "confidence-tracked dedup learning, no standard equivalent"),
    "knowledge_base chromadb": ("N/A", "KEEP", "already uses standard tool (ChromaDB)"),
    "hardcoded path detection": ("semgrep custom rules", "SLIM", "Batcave-specific but could use semgrep syntax"),
}


class LuciusFox(AgentBase):
    """Lucius Fox — Librarian, Gatekeeper, Quality Conscience."""

    name = "lucius-fox"
    version = "2.0"

    REVIEWS_DIR = RUDY_DATA / "lucius-reviews"
    AUDIT_DIR = RUDY_DATA / "lucius-audits"
    CODEBASE_ROOT = REPO_ROOT
    RUDY_PKG = REPO_ROOT / "rudy"

    # Known agent modules (the "Bat Family" roster)
    KNOWN_AGENTS = [
        "sentinel", "security_agent", "research_intel",
        "operations_monitor", "system_master", "task_master",
        "robin_bridge", "robin_presence", "robin_sentinel",
    ]

    def __init__(self):
        super().__init__()
        self.REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        self.AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        self.findings = []

    # ================================================================
    # DISPATCH
    # ================================================================

    def run(self, mode="full_audit", **kwargs):
        """Run Lucius in the specified mode.

        Modes:
            full_audit        — Complete codebase audit (all 4 mandates)
            review_diff       — Review a git diff for quality (Gate mandate)
            review_files      — Review specific files (Gate mandate)
            branch_governance — Audit branch state (Gate mandate)
            hygiene_check     — Check codebase hygiene rules (Conscience + Economist)
            locate            — Find an artifact in the codebase (Library mandate)
            proposal_review   — Review a new module proposal (Gate + Economist)
            dependency_check  — Check dependencies only
            reinvention_check — Check for wheel-reinvention (Economist mandate, ADR-005)
            skills_check      — Recommend relevant skills/tools for a task (ADR-004)
            plan              — Impact analysis before multi-file changes (ADR-004)
        """
        if mode == "full_audit":
            self._audit_code_inventory()
            self._audit_duplication()
            self._audit_dependencies()
            self._audit_agent_health()
            self._audit_documentation()
            self._check_hardcoded_paths()
            self._check_reinvention()
            self._generate_audit_report()

        elif mode == "review_diff":
            diff_text = kwargs.get("diff_text", "")
            branch = kwargs.get("branch", "unknown")
            self._review_diff(diff_text, branch)

        elif mode == "review_files":
            files = kwargs.get("files", [])
            self._review_files(files)

        elif mode == "branch_governance":
            self._audit_branches()

        elif mode == "hygiene_check":
            self._check_hardcoded_paths()
            self._check_lint()
            self._check_import_hygiene()
            self._check_reinvention()
            self._audit_documentation()
            self._generate_audit_report()

        elif mode == "reinvention_check":
            self._check_reinvention()
            self._generate_audit_report()

        elif mode == "locate":
            query = kwargs.get("query", "")
            return self._locate_artifact(query)

        elif mode == "proposal_review":
            proposal = kwargs.get("proposal", {})
            self._review_proposal(proposal)

        elif mode == "dependency_check":
            self._audit_dependencies()
            self._generate_audit_report()

        elif mode == "skills_check":
            task = kwargs.get("task", "")
            return self._skills_check(task)

        elif mode == "plan":
            files = kwargs.get("files", [])
            description = kwargs.get("description", "")
            return self._plan_impact(files, description)

        self.summarize(f"Lucius {mode} complete: {len(self.findings)} findings")

    # ================================================================
    # MANDATE 1: THE LIBRARY — Know Everything That Exists
    # ================================================================

    def _audit_code_inventory(self):
        """Scan all Python files -- delegated to lucius_audit_inventory.py (S74)."""
        from rudy.agents.lucius_audit_inventory import audit_code_inventory  # lucius-exempt
        inventory = audit_code_inventory(
            rudy_pkg=self.RUDY_PKG,
            codebase_root=self.CODEBASE_ROOT,
            log=self.log,
            warn_fn=self.warn,
        )
        self.status["code_inventory"] = {
            "files": inventory["total_files"],
            "lines": inventory["total_lines"],
        }
        self._inventory = inventory

    def _extract_imports(self, content):
        """Extract imports -- delegated to lucius_audit_inventory.py (S74)."""
        from rudy.agents.lucius_audit_inventory import extract_imports  # lucius-exempt
        return extract_imports(content)

    def _locate_artifact(self, query: str) -> dict:
        """Find files, docs, or agents matching a query string.

        Uses the Lucius Registry (Phase 2) when available for fast lookups,
        falling back to filesystem walk if the registry isn't built.

        Returns a dict of matches grouped by category.
        """
        self.log.info(f"Locating artifact: '{query}'")

        # Try registry-backed search first (fast path: <0.1s)
        try:
            from rudy.agents.lucius_registry import query_registry
            registry_results = query_registry(query)
            if registry_results and "error" not in registry_results[0]:
                # Convert registry results to legacy format + enhanced results
                results = {
                    "python_files": [],
                    "docs": [],
                    "scripts": [],
                    "agents": [],
                    "skills": [],
                    "mcps": [],
                    "scheduled_tasks": [],
                    "registry_hits": registry_results,
                }
                for r in registry_results:
                    if r["type"] == "module" and r.get("path", "").endswith(".py"):
                        results["python_files"].append(r["path"])
                    elif r["type"] == "agent":
                        results["agents"].append({
                            "name": r["name"],
                            "status": r.get("status", "unknown"),
                        })
                    elif r["type"] == "skill":
                        results["skills"].append(r["name"])
                    elif r["type"] == "mcp":
                        results["mcps"].append(r["name"])
                    elif r["type"] == "scheduled_task":
                        results["scheduled_tasks"].append(r["name"])
                total = sum(
                    len(v) for k, v in results.items()
                    if k != "registry_hits" and isinstance(v, list)
                )
                self.action(f"Located {total} matches for '{query}' (via registry)")
                return results
        except ImportError:
            pass  # Fall through to filesystem walk
        except Exception as e:
            self.log.warning(f"Registry query failed, falling back to filesystem: {e}")
        query_lower = query.lower()
        results = {"python_files": [], "docs": [], "scripts": [], "agents": []}

        # Search Python files
        for root, dirs, files in os.walk(self.CODEBASE_ROOT):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "node_modules", "vault"}]
            for f in files:
                if query_lower in f.lower():
                    fp = Path(root) / f
                    rel = str(fp.relative_to(self.CODEBASE_ROOT))
                    if f.endswith(".py"):
                        results["python_files"].append(rel)
                    elif f.endswith(".md"):
                        results["docs"].append(rel)
                    elif f.endswith((".ps1", ".bat", ".sh")):
                        results["scripts"].append(rel)

        # Search file contents for query
        for root, dirs, files in os.walk(self.RUDY_PKG):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py"):
                    continue
                fp = Path(root) / f
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                    if query_lower in content.lower():
                        rel = str(fp.relative_to(self.CODEBASE_ROOT))
                        if rel not in results["python_files"]:
                            results["python_files"].append(rel)
                except Exception:
                    pass

        # Check agents
        for agent in self.KNOWN_AGENTS:
            if query_lower in agent:
                status = self.read_status(agent)
                results["agents"].append({
                    "name": agent,
                    "status": status.get("status", "unknown"),
                    "last_run": status.get("last_run", "never"),
                })

        total = sum(len(v) for v in results.values())
        self.action(f"Located {total} matches for '{query}'")
        return results

    def _audit_duplication(self):
        """Find duplication -- delegated to lucius_audit_inventory.py (S74)."""
        from rudy.agents.lucius_audit_inventory import audit_duplication  # lucius-exempt
        inventory = self._inventory if hasattr(self, "_inventory") else None
        self.findings.extend(audit_duplication(inventory, log=self.log))

    def _audit_dependencies(self):
        """Check Python package dependencies -- delegated to lucius_dependency_audit.py."""
        from rudy.agents.lucius_dependency_audit import audit_dependencies  # lucius-exempt
        self.log.info("Auditing dependencies (via pip-audit)...")
        dep_findings = audit_dependencies(codebase_root=self.CODEBASE_ROOT)
        self.findings.extend(dep_findings)

    def _audit_agent_health(self):
        """Check agent health -- delegated to lucius_audit_governance.py (S74)."""
        from rudy.agents.lucius_audit_governance import audit_agent_health  # lucius-exempt
        self.findings.extend(audit_agent_health(
            known_agents=self.KNOWN_AGENTS,
            read_status_fn=self.read_status,
            log=self.log,
        ))

    def _audit_documentation(self):
        """Check docs -- delegated to lucius_audit_governance.py (S74)."""
        from rudy.agents.lucius_audit_governance import audit_documentation  # lucius-exempt
        self.findings.extend(audit_documentation(
            codebase_root=self.CODEBASE_ROOT,
            log=self.log,
        ))

    # ================================================================
    # MANDATE 2: THE GATE — Nothing Merges Without Review
    # ================================================================

    def _review_diff(self, diff_text: str, branch: str = "unknown") -> dict:
        """Review a git diff. Delegated to lucius_diff_review."""
        from rudy.agents.lucius_diff_review import review_diff
        result = review_diff(
            diff_text=diff_text,
            branch=branch,
            reviews_dir=self.REVIEWS_DIR,
        )
        # Sync findings back to self
        self.findings.extend(result.get("findings", []))
        self.action(f"Review {result.get('review_id', '?')}: {result.get('verdict', '?')}")
        return result

    def _review_files(self, files: list) -> dict:
        """Review files for quality. Delegated to lucius_diff_review."""
        from rudy.agents.lucius_diff_review import review_files
        result = review_files(
            files=files,
            codebase_root=self.CODEBASE_ROOT,
            reviews_dir=self.REVIEWS_DIR,
        )
        # Sync findings back to self
        self.findings.extend(result.get("findings", []))
        self.action(f"File review {result.get('review_id', '?')}: {result.get('verdict', '?')}")
        return result

    def _audit_branches(self) -> dict:
        """Audit branches -- delegated to lucius_audit_governance.py (S74)."""
        from rudy.agents.lucius_audit_governance import audit_branches  # lucius-exempt
        result, findings = audit_branches(
            codebase_root=self.CODEBASE_ROOT,
            log=self.log,
            warn_fn=self.warn,
        )
        self.findings.extend(findings)
        self.action(f"Branch audit: {len(result['branches'])} branches found")
        return result

    def _review_proposal(self, proposal):
        """Review a new module/dependency proposal -- delegated to lucius_proposal_review.py."""
        from rudy.agents.lucius_proposal_review import review_proposal  # lucius-exempt
        inventory = self._inventory if hasattr(self, "_inventory") else None
        record = review_proposal(
            proposal=proposal,
            inventory=inventory,
            reviews_dir=self.REVIEWS_DIR,
        )
        self.action(f"Proposal review: {record['verdict']}")
        return record

    # ================================================================
    # MANDATE 3: THE CONSCIENCE — Enforce Protocol Compliance
    # ================================================================

    def _check_hardcoded_paths(self):
        """Scan for hardcoded paths. Delegated to lucius_hardcoded_paths."""
        from rudy.agents.lucius_hardcoded_paths import check_hardcoded_paths
        result = check_hardcoded_paths(
            codebase_root=self.CODEBASE_ROOT,
            rudy_pkg=self.RUDY_PKG,
        )
        self.findings.extend(result.get('findings', []))
        self.action("Hardcoded paths check complete")
    def _check_lint(self):
        """Run ruff linter and capture findings."""
        self.log.info("Running ruff lint check...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", str(self.RUDY_PKG)] + RUFF_ARGS + ["--output-format=json"],
                capture_output=True, text=True, timeout=60,
                cwd=str(self.CODEBASE_ROOT), encoding="utf-8", errors="replace"
            )
            if result.stdout:
                try:
                    lint_results = json.loads(result.stdout)
                    for item in lint_results[:20]:  # Cap at 20 findings
                        self.findings.append({
                            "type": "lint_error",
                            "severity": "low",
                            "title": f"Lint: {item.get('code', '?')} in {item.get('filename', '?')}:{item.get('location', {}).get('row', '?')}",
                            "detail": item.get("message", ""),
                            "recommendation": "Fix lint error",
                        })
                except json.JSONDecodeError:
                    # Non-JSON output means either clean or ruff not installed
                    if result.returncode != 0:
                        self.warn(f"Ruff output not JSON: {result.stdout[:200]}")
            if result.returncode == 0:
                self.action("Ruff lint: all checks passed")
        except FileNotFoundError:
            self.warn("Ruff not installed — skipping lint check")
        except subprocess.TimeoutExpired:
            self.warn("Ruff timed out")

    def _check_import_hygiene(self):
        """Check import hygiene. Delegated to lucius_import_hygiene."""
        from rudy.agents.lucius_import_hygiene import check_import_hygiene
        result = check_import_hygiene(
            codebase_root=self.CODEBASE_ROOT,
            rudy_pkg=self.RUDY_PKG,
        )
        self.findings.extend(result.get('findings', []))
        self.action("Import hygiene check complete")
    def _check_reinvention(self):
        """Scan for wheel-reinvention. Delegated to lucius_reinvention_check."""
        from rudy.agents.lucius_reinvention_check import check_reinvention
        result = check_reinvention(
            codebase_root=self.CODEBASE_ROOT,
            rudy_pkg=self.RUDY_PKG,
        )
        self.findings.extend(result.get('findings', []))
        self.action("Reinvention check complete (Mandate 4 / ADR-005)")

    def _scan_for_reinvention(self, rel_path, content_lower, indicators, is_ci=False):
        """Backward compat wrapper. Delegated to lucius_reinvention_check."""
        from rudy.agents.lucius_reinvention_check import _scan_for_reinvention
        return _scan_for_reinvention(rel_path, content_lower, indicators, is_ci=is_ci)
    def _generate_audit_report(self):
        """Write structured audit report -- delegated to lucius_audit_report.py."""
        from rudy.agents.lucius_audit_report import generate_audit_report  # lucius-exempt
        report = generate_audit_report(
            findings=self.findings,
            status=self.status,
            version=self.version,
            audit_dir=self.AUDIT_DIR,
        )
        self.action(f"Audit report written: {report['audit_id']}")
        return report


    # ================================================================
    # SESSION CHECKPOINT (HARD RULE #5 — Session 22)
    # ================================================================

    def session_checkpoint(
        self,
        session_number: int,
        context_pct: float,
        status: str = "",
    ) -> str:
        """Generate context eval line -- delegated to lucius_session_checkpoint.py (S74)."""
        from rudy.agents.lucius_session_checkpoint import session_checkpoint as _checkpoint  # lucius-exempt
        return _checkpoint(
            session_number=session_number,
            context_pct=context_pct,
            status=status,
            audit_dir=self.AUDIT_DIR,
            log=self.log,
        )

    # ================================================================
    # ADR-004 TOOLKIT: lucius:skills-check (extracted S72)
    # ================================================================

    # CAPABILITY_INDEX moved to lucius_skills_check.py
    from rudy.agents.lucius_skills_check import CAPABILITY_INDEX  # noqa: F811,E303

    def _skills_check(self, task: str) -> dict:
        """lucius:skills-check -- delegated to lucius_skills_check.py."""
        from rudy.agents.lucius_skills_check import skills_check
        result = skills_check(task=task)
        self.action(f"Skills check: {result.get('total_matches', 0)} recommendations")
        return result

    def _plan_impact(self, files: list, description: str = "") -> dict:
        """lucius:plan -- Impact analysis. Delegated to lucius_plan_impact."""
        from rudy.agents.lucius_plan_impact import plan_impact
        result = plan_impact(
            files=files,
            description=description,
            codebase_root=self.CODEBASE_ROOT,
            known_agents=self.KNOWN_AGENTS,
        )
        if "summary" in result:
            self.action(f"Impact analysis: {result['risk']} risk for {len(files)} files")
        return result

# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Lucius Fox — Batcave Quality Gate")
    parser.add_argument("mode", nargs="?", default="full_audit",
                        choices=["full_audit", "hygiene_check", "branch_governance",
                                 "review_files", "locate", "dependency_check",
                                 "reinvention_check", "skills_check", "plan"],
                        help="Operating mode")
    parser.add_argument("--files", nargs="*", help="Files to review/analyze (for review_files or plan mode)")
    parser.add_argument("--query", type=str, help="Search query (for locate mode)")
    parser.add_argument("--task", type=str, help="Task description (for skills_check mode)")
    parser.add_argument("--description", type=str, help="Change description (for plan mode)")
    args = parser.parse_args()

    lucius = LuciusFox()
    kwargs = {}
    if args.mode == "review_files" and args.files:
        kwargs["files"] = args.files
    elif args.mode == "locate" and args.query:
        kwargs["query"] = args.query
    elif args.mode == "skills_check" and args.task:
        kwargs["task"] = args.task
    elif args.mode == "plan" and args.files:
        kwargs["files"] = args.files
        if args.description:
            kwargs["description"] = args.description

    result = lucius.execute(mode=args.mode, **kwargs)
    if result and isinstance(result, dict) and "summary" in result:
        print(result["summary"])
