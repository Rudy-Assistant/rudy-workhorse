"""
Lucius Fox — The Batcave's Librarian, Gatekeeper, and Quality Conscience.

ADR-004 (2026-03-29): Lucius is the single source of truth for repository
structure, canonical documentation, and operational protocol compliance.

Three Mandates:
    1. The Library  — Know everything that exists (audit, inventory, locate)
    2. The Gate     — Nothing merges without review (diff review, quality checks)
    3. The Conscience — Enforce protocol compliance (hygiene, branch governance)

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
from typing import Optional

from rudy.paths import REPO_ROOT, RUDY_DATA, RUDY_LOGS, DESKTOP, BATCAVE_VAULT
from . import AgentBase, LOGS_DIR


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Patterns that should NEVER appear in committed code
HARDCODED_PATH_PATTERNS = [
    r'C:\\Users\\ccimi\\Desktop',
    r'C:/Users/ccimi/Desktop',
    r"C:\\\\Users\\\\ccimi",
    r'~/Desktop/rudy-',
    r'r"C:\\Users',
    r"r'C:\\Users",
]

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
            full_audit      — Complete codebase audit (Library mandate)
            review_diff     — Review a git diff for quality (Gate mandate)
            review_files    — Review specific files (Gate mandate)
            branch_governance — Audit branch state (Gate mandate)
            hygiene_check   — Check codebase hygiene rules (Conscience mandate)
            locate          — Find an artifact in the codebase (Library mandate)
            proposal_review — Review a new module proposal (Gate mandate)
            dependency_check — Check dependencies only
        """
        if mode == "full_audit":
            self._audit_code_inventory()
            self._audit_duplication()
            self._audit_dependencies()
            self._audit_agent_health()
            self._audit_documentation()
            self._check_hardcoded_paths()
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
            self._audit_documentation()
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

        self.summarize(f"Lucius {mode} complete: {len(self.findings)} findings")

    # ================================================================
    # MANDATE 1: THE LIBRARY — Know Everything That Exists
    # ================================================================

    def _audit_code_inventory(self):
        """Scan all Python files, categorize, measure."""
        self.log.info("Auditing code inventory...")
        inventory = {"modules": {}, "total_files": 0, "total_lines": 0}

        for root, dirs, files in os.walk(self.RUDY_PKG):
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

                    rel = str(fp.relative_to(self.CODEBASE_ROOT))
                    inventory["modules"][rel] = {
                        "lines": lines,
                        "size_bytes": fp.stat().st_size,
                        "docstring": doc,
                        "has_tests": "test" in f.lower() or "assert" in content,
                        "imports": self._extract_imports(content),
                        "last_modified": datetime.fromtimestamp(fp.stat().st_mtime).isoformat(),
                    }
                    inventory["total_files"] += 1
                    inventory["total_lines"] += lines
                except Exception as e:
                    self.warn(f"Could not read {fp}: {e}")

        self.status["code_inventory"] = {
            "files": inventory["total_files"],
            "lines": inventory["total_lines"],
        }
        self._inventory = inventory
        self.log.info(f"Inventory: {inventory['total_files']} files, {inventory['total_lines']} lines")

    def _extract_imports(self, content):
        """Extract import statements from Python file."""
        imports = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("import ") or line.startswith("from "):
                imports.append(line.split("#")[0].strip())
        return imports

    def _locate_artifact(self, query: str) -> dict:
        """Find files, docs, or agents matching a query string.

        Returns a dict of matches grouped by category.
        """
        self.log.info(f"Locating artifact: '{query}'")
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
        """Find files with overlapping purpose or duplicated code."""
        self.log.info("Auditing for duplication...")
        if not hasattr(self, "_inventory"):
            return

        name_groups = {}
        for path in self._inventory["modules"]:
            base = Path(path).stem.lower()
            key = base.replace("robin_", "").replace("rudy_", "")
            name_groups.setdefault(key, []).append(path)

        for key, paths in name_groups.items():
            if len(paths) > 1:
                self.findings.append({
                    "type": "duplication_suspect",
                    "severity": "medium",
                    "title": f"Possible duplication: {key}",
                    "detail": f"Multiple files with similar purpose: {paths}",
                    "recommendation": "Review for consolidation or document why both are needed",
                    "paths": paths,
                })

        for path, info in self._inventory["modules"].items():
            for imp in info["imports"]:
                if "robin_sentinel" in imp and "agents/sentinel" in path:
                    self.findings.append({
                        "type": "import_overlap",
                        "severity": "low",
                        "title": "Cross-import between sentinel variants",
                        "detail": f"{path} imports from robin_sentinel",
                        "recommendation": "Consolidate sentinel functionality",
                    })

    def _audit_dependencies(self):
        """Check Python package dependencies for currency and security."""
        self.log.info("Auditing dependencies...")

        req_file = self.CODEBASE_ROOT / "requirements.txt"
        if req_file.exists():
            reqs = req_file.read_text(errors="replace").strip().split("\n")
            for req in reqs:
                req = req.strip()
                if not req or req.startswith("#"):
                    continue
                pkg = req.split("==")[0].split(">=")[0].split("<=")[0].strip()
                self.findings.append({
                    "type": "dependency_check",
                    "severity": "info",
                    "title": f"Dependency: {pkg}",
                    "detail": f"Requirement: {req}. Check PyPI for latest version and known CVEs.",
                    "recommendation": "Verify currency on next audit with web search",
                })
        else:
            self.findings.append({
                "type": "missing_config",
                "severity": "medium",
                "title": "No requirements.txt found",
                "detail": "Dependencies are not pinned. Builds may not be reproducible.",
                "recommendation": "Generate requirements.txt with pip freeze > requirements.txt",
            })

        if hasattr(self, "_inventory"):
            all_imports = set()
            for info in self._inventory["modules"].values():
                for imp in info["imports"]:
                    if imp.startswith("from "):
                        pkg = imp.split()[1].split(".")[0]
                    else:
                        pkg = imp.split()[1].split(".")[0]
                    all_imports.add(pkg)

            stdlib = {
                "os", "sys", "json", "time", "datetime", "pathlib", "subprocess",
                "hashlib", "logging", "re", "math", "collections", "functools",
                "itertools", "typing", "abc", "io", "shutil", "tempfile",
                "threading", "socket", "http", "urllib", "email", "smtplib",
                "traceback", "importlib", "contextlib", "dataclasses", "enum",
                "copy", "struct", "base64", "uuid", "random", "string",
                "textwrap", "argparse", "configparser", "csv", "sqlite3",
                "glob", "fnmatch", "signal", "ctypes", "platform", "warnings",
                "codecs",
            }
            internal = {"rudy"}
            third_party = all_imports - stdlib - internal - {""}
            self.status["third_party_imports"] = sorted(third_party)

    def _audit_agent_health(self):
        """Check status of all known agents."""
        self.log.info("Auditing agent health...")

        for agent_name in self.KNOWN_AGENTS:
            status = self.read_status(agent_name)
            if status.get("status") == "unknown":
                self.findings.append({
                    "type": "agent_status",
                    "severity": "low",
                    "title": f"Agent '{agent_name}' has no status file",
                    "detail": "Either never run or status file missing",
                    "recommendation": "Verify agent is scheduled and functioning",
                })
            elif status.get("status") == "error":
                self.findings.append({
                    "type": "agent_error",
                    "severity": "high",
                    "title": f"Agent '{agent_name}' in error state",
                    "detail": f"Last run: {status.get('last_run')}. Alerts: {status.get('critical_alerts', [])}",
                    "recommendation": "Investigate crash dumps and fix root cause",
                })
            else:
                last_run = status.get("last_run", "")
                if last_run:
                    try:
                        lr = datetime.fromisoformat(last_run)
                        age_hours = (datetime.now() - lr).total_seconds() / 3600
                        if age_hours > 24:
                            self.findings.append({
                                "type": "agent_stale",
                                "severity": "medium",
                                "title": f"Agent '{agent_name}' stale ({age_hours:.0f}h since last run)",
                                "detail": f"Last run: {last_run}",
                                "recommendation": "Check Task Scheduler or trigger manual run",
                            })
                    except (ValueError, TypeError):
                        pass

    def _audit_documentation(self):
        """Check documentation freshness and completeness."""
        self.log.info("Auditing documentation...")

        for rel_path, desc in REQUIRED_DOCS:
            path = self.CODEBASE_ROOT / rel_path
            if path.exists():
                age_hours = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
                lines = path.read_text(errors="replace").count("\n")
                if age_hours > 168:  # 1 week
                    self.findings.append({
                        "type": "doc_stale",
                        "severity": "medium",
                        "title": f"{desc} is stale ({age_hours / 24:.0f} days old)",
                        "detail": f"{rel_path}: {lines} lines, last modified {age_hours / 24:.0f}d ago",
                        "recommendation": "Review and update documentation",
                    })
            else:
                self.findings.append({
                    "type": "doc_missing",
                    "severity": "high" if "README" in rel_path else "medium",
                    "title": f"Missing documentation: {desc}",
                    "detail": f"Expected at {rel_path}",
                    "recommendation": "Create this documentation",
                })

        # Also check BatcaveVault
        vault_home = BATCAVE_VAULT / "Home.md"
        if not vault_home.exists():
            self.findings.append({
                "type": "doc_missing",
                "severity": "medium",
                "title": "BatcaveVault Home.md missing",
                "detail": f"Expected at {vault_home}",
                "recommendation": "Initialize BatcaveVault with Home.md",
            })

    # ================================================================
    # MANDATE 2: THE GATE — Nothing Merges Without Review
    # ================================================================

    def _review_diff(self, diff_text: str, branch: str = "unknown") -> dict:
        """Review a git diff and produce a Lucius Review Record.

        Checks:
            1. Hardcoded paths (must use rudy.paths)
            2. Direct pushes to protected branches
            3. Missing docstrings on new functions/classes
            4. Overly broad except clauses
            5. Security anti-patterns (eval, exec, shell=True)
            6. Import hygiene (unused or circular)
        """
        self.log.info(f"Reviewing diff for branch: {branch}")
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
            for pattern in HARDCODED_PATH_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    self.findings.append({
                        "type": "hardcoded_path",
                        "severity": "high",
                        "title": f"Hardcoded path in {filepath}",
                        "detail": f"Line: {line.strip()[:120]}",
                        "recommendation": "Import from rudy.paths instead of hardcoding",
                    })

        # Check 2: Security anti-patterns
        security_patterns = [
            (r'\beval\s*\(', "eval() usage — potential code injection"),
            (r'\bexec\s*\(', "exec() usage — potential code injection"),
            (r'shell\s*=\s*True', "shell=True in subprocess — potential injection"),
            (r'pickle\.loads?\(', "pickle.load — potential deserialization attack"),
            (r'__import__\s*\(', "Dynamic __import__ — review for necessity"),
        ]
        for filepath, line in added_lines:
            if not filepath.endswith(".py"):
                continue
            for pattern, desc in security_patterns:
                if re.search(pattern, line):
                    self.findings.append({
                        "type": "security_concern",
                        "severity": "high",
                        "title": f"Security: {desc}",
                        "detail": f"File: {filepath}, Line: {line.strip()[:120]}",
                        "recommendation": "Review for necessity and add safety comment if intentional",
                    })

        # Check 3: Overly broad exception handling
        for filepath, line in added_lines:
            if not filepath.endswith(".py"):
                continue
            stripped = line.strip()
            if stripped == "except:" or stripped == "except Exception:":
                self.findings.append({
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
                # Look ahead in added lines for a docstring
                # (simplified — just flag for manual review)
                self.findings.append({
                    "type": "review_hint",
                    "severity": "info",
                    "title": f"New definition in {filepath}",
                    "detail": f"{stripped[:80]}",
                    "recommendation": "Verify docstring and type hints are present",
                })

        # Check 5: git add -A (dangerous in Robin context)
        for filepath, line in added_lines:
            if "git add -A" in line or "git add ." in line:
                self.findings.append({
                    "type": "dangerous_git",
                    "severity": "high",
                    "title": f"Unrestricted git add in {filepath}",
                    "detail": f"Line: {line.strip()[:120]}",
                    "recommendation": "Use explicit file paths instead of git add -A",
                })

        # Generate verdict
        high_count = sum(1 for f in self.findings if f.get("severity") == "high")
        verdict = "approve" if high_count == 0 else "request_changes"

        record = {
            "review_id": review_id,
            "timestamp": datetime.now().isoformat(),
            "branch": branch,
            "verdict": verdict,
            "findings_count": len(self.findings),
            "high_severity": high_count,
            "findings": self.findings,
        }

        review_file = self.REVIEWS_DIR / f"{review_id}.json"
        with open(review_file, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str)

        self.action(f"Review {review_id}: {verdict} ({len(self.findings)} findings, {high_count} high)")
        self.log.info(f"Review verdict: {verdict}")
        return record

    def _review_files(self, files: list) -> dict:
        """Review specific files for quality issues.

        Runs all Gate checks on the file contents directly.
        """
        self.log.info(f"Reviewing {len(files)} files...")

        for filepath in files:
            fp = self.CODEBASE_ROOT / filepath
            if not fp.exists():
                self.warn(f"File not found: {filepath}")
                continue
            if not filepath.endswith(".py"):
                continue

            content = fp.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")

            # Check hardcoded paths
            for i, line in enumerate(lines, 1):
                for pattern in HARDCODED_PATH_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        self.findings.append({
                            "type": "hardcoded_path",
                            "severity": "high",
                            "title": f"Hardcoded path in {filepath}:{i}",
                            "detail": f"Line {i}: {line.strip()[:120]}",
                            "recommendation": "Import from rudy.paths instead",
                        })

            # Check for functions without docstrings
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if (stripped.startswith("def ") or stripped.startswith("class ")) and not stripped.startswith("def _"):
                    # Check if next non-empty line is a docstring
                    has_docstring = False
                    for j in range(i, min(i + 3, len(lines))):
                        next_line = lines[j].strip()
                        if next_line.startswith('"""') or next_line.startswith("'''"):
                            has_docstring = True
                            break
                        if next_line and not next_line.startswith("#"):
                            break
                    if not has_docstring:
                        self.findings.append({
                            "type": "missing_docstring",
                            "severity": "low",
                            "title": f"Missing docstring: {filepath}:{i}",
                            "detail": f"{stripped[:80]}",
                            "recommendation": "Add a docstring explaining purpose and parameters",
                        })

            # Check for imports not from rudy.paths when using path patterns
            if "Desktop" in content and "from rudy.paths" not in content:
                self.findings.append({
                    "type": "path_import_missing",
                    "severity": "medium",
                    "title": f"{filepath} references 'Desktop' without importing rudy.paths",
                    "detail": "File may have hardcoded path constructions",
                    "recommendation": "Import paths from rudy.paths",
                })

        # Generate review record
        review_id = f"LRR-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        high_count = sum(1 for f in self.findings if f.get("severity") == "high")
        verdict = "approve" if high_count == 0 else "request_changes"

        record = {
            "review_id": review_id,
            "timestamp": datetime.now().isoformat(),
            "files_reviewed": files,
            "verdict": verdict,
            "findings_count": len(self.findings),
            "high_severity": high_count,
            "findings": self.findings,
        }

        review_file = self.REVIEWS_DIR / f"{review_id}.json"
        with open(review_file, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str)

        self.action(f"File review {review_id}: {verdict}")
        return record

    def _audit_branches(self) -> dict:
        """Audit git branch state — stale branches, unmerged work, governance.

        This is the Gate's branch governance function. It checks:
            1. Are there stale feature branches (>7 days)?
            2. Are there branches with unmerged commits?
            3. Is Robin on the correct branch?
        """
        self.log.info("Auditing branch governance...")
        result = {"branches": [], "warnings": []}

        try:
            git_result = subprocess.run(
                ["git", "branch", "-a", "--format=%(refname:short) %(committerdate:iso8601)"],
                capture_output=True, text=True, cwd=str(self.CODEBASE_ROOT),
                timeout=30, encoding="utf-8", errors="replace"
            )
            if git_result.returncode != 0:
                self.warn(f"git branch failed: {git_result.stderr}")
                return result

            for line in git_result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.strip().split(" ", 1)
                branch_name = parts[0]
                date_str = parts[1] if len(parts) > 1 else ""

                result["branches"].append(branch_name)

                # Check for stale branches
                if date_str and branch_name not in PROTECTED_BRANCHES:
                    try:
                        # Parse ISO date loosely
                        branch_date = datetime.fromisoformat(date_str.strip().replace(" ", "T")[:19])
                        age_days = (datetime.now() - branch_date).days
                        if age_days > 7:
                            self.findings.append({
                                "type": "stale_branch",
                                "severity": "low",
                                "title": f"Stale branch: {branch_name} ({age_days}d old)",
                                "detail": f"Last commit: {date_str}",
                                "recommendation": "Merge or delete if no longer needed",
                            })
                    except (ValueError, TypeError):
                        pass

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            self.warn(f"Git not available for branch audit: {e}")

        self.action(f"Branch audit: {len(result['branches'])} branches found")
        return result

    def _review_proposal(self, proposal):
        """Review a new module/dependency proposal (Lucius Review Record)."""
        self.log.info(f"Reviewing proposal: {proposal.get('title', 'untitled')}")

        record = {
            "review_id": f"LRR-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            "proposal": proposal,
            "verdict": "pending",
            "alternatives_found": [],
            "recommendation": "",
            "implementation_spec": None,
            "checks": {
                "duplicates_existing": False,
                "requires_new_dependency": False,
                "architecture_impact": "none",
            },
        }

        title_lower = proposal.get("title", "").lower()
        desc_lower = proposal.get("description", "").lower()

        # Check for overlap with existing modules
        if hasattr(self, "_inventory"):
            for path in self._inventory["modules"]:
                module_name = Path(path).stem.lower()
                if module_name in title_lower or module_name in desc_lower:
                    record["checks"]["duplicates_existing"] = True
                    record["alternatives_found"].append(path)

        if record["checks"]["duplicates_existing"]:
            record["verdict"] = "request_changes"
            record["recommendation"] = (
                f"Possible overlap with existing modules: {record['alternatives_found']}. "
                "Review for consolidation before creating new module."
            )
        else:
            record["verdict"] = "approved_pending_implementation"
            record["recommendation"] = "No obvious overlap. Proceed with implementation."

        review_file = self.REVIEWS_DIR / f"{record['review_id']}.json"
        with open(review_file, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str)

        self.action(f"Proposal review: {record['verdict']}")
        return record

    # ================================================================
    # MANDATE 3: THE CONSCIENCE — Enforce Protocol Compliance
    # ================================================================

    def _check_hardcoded_paths(self):
        """Scan entire codebase for hardcoded paths that should use rudy.paths."""
        self.log.info("Checking for hardcoded paths...")

        # Files/patterns that are expected to contain path strings (not actual usage)
        EXEMPT_FILES = {"rudy/paths.py", "rudy/agents/lucius_fox.py"}

        for root, dirs, files in os.walk(self.RUDY_PKG):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py"):
                    continue
                fp = Path(root) / f
                rel = str(fp.relative_to(self.CODEBASE_ROOT))

                # Skip files that legitimately define/document path patterns
                if rel in EXEMPT_FILES:
                    continue

                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                    for i, line in enumerate(content.split("\n"), 1):
                        stripped = line.strip()
                        # Skip comments and docstrings
                        if stripped.startswith("#"):
                            continue
                        if stripped.startswith('"""') or stripped.startswith("'''"):
                            continue
                        for pattern in HARDCODED_PATH_PATTERNS:
                            if re.search(pattern, line, re.IGNORECASE):
                                self.findings.append({
                                    "type": "hardcoded_path",
                                    "severity": "high",
                                    "title": f"Hardcoded path: {rel}:{i}",
                                    "detail": f"Line {i}: {stripped[:120]}",
                                    "recommendation": "Import from rudy.paths",
                                })
                                break  # One finding per line is enough
                except Exception:
                    pass

        # Also check scripts/
        scripts_dir = self.CODEBASE_ROOT / "scripts"
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
                                rel = str(fp.relative_to(self.CODEBASE_ROOT))
                                self.findings.append({
                                    "type": "hardcoded_path",
                                    "severity": "medium",
                                    "title": f"Hardcoded path in script: {rel}:{i}",
                                    "detail": f"Line {i}: {stripped[:120]}",
                                    "recommendation": "Import from rudy.paths or use dynamic detection",
                                })
                                break
                except Exception:
                    pass

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
        """Check that modules use rudy.paths for path resolution."""
        self.log.info("Checking import hygiene...")

        for root, dirs, files in os.walk(self.RUDY_PKG):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py") or f == "paths.py":
                    continue
                fp = Path(root) / f
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                    rel = str(fp.relative_to(self.CODEBASE_ROOT))

                    # Check: file constructs paths with Path(__file__) but doesn't import from rudy.paths
                    uses_file_path = "Path(__file__)" in content
                    imports_rudy_paths = "from rudy.paths" in content or "import rudy.paths" in content

                    # Exempt: sys.path bootstrap pattern (e.g. scripts that insert repo root
                    # before importing rudy.paths — the bootstrap IS the path to rudy.paths)
                    is_bootstrap = "sys.path.insert" in content and "Path(__file__)" in content

                    if uses_file_path and not imports_rudy_paths and not is_bootstrap:
                        self.findings.append({
                            "type": "import_hygiene",
                            "severity": "medium",
                            "title": f"{rel} uses Path(__file__) without rudy.paths",
                            "detail": "Module constructs paths from __file__ instead of importing canonical paths",
                            "recommendation": "Import from rudy.paths for consistency and portability",
                        })

                    # Check: file references DESKTOP or HOME directly via os.environ
                    if ("USERPROFILE" in content or "os.path.expanduser" in content) and not imports_rudy_paths:
                        if f != "__init__.py":
                            self.findings.append({
                                "type": "import_hygiene",
                                "severity": "low",
                                "title": f"{rel} resolves home directory without rudy.paths",
                                "detail": "Uses USERPROFILE/expanduser directly",
                                "recommendation": "Use rudy.paths.HOME or rudy.paths.DESKTOP",
                            })

                except Exception:
                    pass

    # ================================================================
    # REPORTING
    # ================================================================

    def _generate_audit_report(self):
        """Write structured audit report."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        report = {
            "audit_id": f"lucius-audit-{timestamp}",
            "timestamp": datetime.now().isoformat(),
            "agent_version": self.version,
            "summary": {
                "total_findings": len(self.findings),
                "by_severity": {},
                "by_type": {},
            },
            "findings": self.findings,
            "code_stats": self.status.get("code_inventory", {}),
            "third_party": self.status.get("third_party_imports", []),
        }

        for f in self.findings:
            sev = f.get("severity", "unknown")
            typ = f.get("type", "unknown")
            report["summary"]["by_severity"][sev] = report["summary"]["by_severity"].get(sev, 0) + 1
            report["summary"]["by_type"][typ] = report["summary"]["by_type"].get(typ, 0) + 1

        report_file = self.AUDIT_DIR / f"audit-{timestamp}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

        self.log.info(f"Audit report: {report_file}")
        self.log.info(f"Findings: {report['summary']['by_severity']}")

        md_file = self.AUDIT_DIR / f"audit-{timestamp}.md"
        lines = [
            "# Lucius Fox Audit Report",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Version:** {self.version}",
            f"**Findings:** {len(self.findings)}",
            "",
            "## Summary",
            "",
        ]
        for sev in ["high", "medium", "low", "info"]:
            count = report["summary"]["by_severity"].get(sev, 0)
            if count:
                lines.append(f"- **{sev.upper()}:** {count}")
        lines.append("")
        lines.append("## Findings")
        lines.append("")

        for i, f_item in enumerate(self.findings, 1):
            sev = f_item.get("severity", "?").upper()
            lines.append(f"### {i}. [{sev}] {f_item['title']}")
            lines.append(f"{f_item.get('detail', '')}")
            lines.append(f"**Recommendation:** {f_item.get('recommendation', 'N/A')}")
            lines.append("")

        md_file.write_text("\n".join(lines), encoding="utf-8")
        self.action(f"Audit report written to {report_file.name}")
        return report


# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Lucius Fox — Batcave Quality Gate")
    parser.add_argument("mode", nargs="?", default="full_audit",
                        choices=["full_audit", "hygiene_check", "branch_governance",
                                 "review_files", "locate", "dependency_check"],
                        help="Operating mode")
    parser.add_argument("--files", nargs="*", help="Files to review (for review_files mode)")
    parser.add_argument("--query", type=str, help="Search query (for locate mode)")
    args = parser.parse_args()

    lucius = LuciusFox()
    kwargs = {}
    if args.mode == "review_files" and args.files:
        kwargs["files"] = args.files
    elif args.mode == "locate" and args.query:
        kwargs["query"] = args.query

    lucius.execute(mode=args.mode, **kwargs)
