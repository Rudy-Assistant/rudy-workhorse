"""
Lucius Fox - The Specialist Engineer.
Owns the health, efficiency, and currency of the entire Bat Family toolchain.

Unlike the Four Horsemen (SystemMaster, OperationsMonitor, ResearchIntel, TaskMaster)
and the Sentinel who observes moment-to-moment, Lucius operates at the architectural
level. He ensures:
  1. No custom code exists where a proven library would serve
  2. No duplication across agents or modules
  3. Dependencies are current, secure, and actively maintained
  4. Skills, connectors, and MCP servers are well-leveraged (not gathering dust)
  5. Every new module passes a build-vs-buy review before deployment
  6. README/documentation stays authoritative and current

Lucius runs on two triggers:
  - Scheduled audit cadence (weekly, or after N sessions)
  - Proposal gate (when any agent proposes a new module/dependency)

Design principles:
  - Scrutinize before building: does something already exist?
  - Enforce discipline: controlled process for custom code
  - Own the documentation: CLAUDE.md, README.md, BATCAVE.md
  - Audit retroactively: are our methods still the best available?
  - Never block emergencies: lightweight mode for time-pressured work

ADR-002: Lucius Fox Agent (2026-03-29)
  Decision: Build as AgentBase subclass in rudy/agents/ framework.
  Alternatives considered: LangGraph agent, standalone script, Cowork plugin.
  Rationale: Uses existing infrastructure (scheduling, logging, crash dumps,
  cross-agent status reads). LangGraph migration may be recommended BY Lucius
  as a future audit finding, but Lucius himself uses what exists today.
"""
import json
import os

from datetime import datetime
from pathlib import Path
from rudy.paths import REPO_ROOT, RUDY_DATA, RUDY_LOGS, DESKTOP
from . import AgentBase, LOGS_DIR

class LuciusFox(AgentBase):
    name = "lucius-fox"
    version = "1.0"

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

    def run(self, mode="full_audit", **kwargs):
        """Run Lucius in specified mode."""
        if mode == "full_audit":
            self._audit_code_inventory()
            self._audit_duplication()
            self._audit_dependencies()
            self._audit_agent_health()
            self._audit_documentation()
            self._generate_audit_report()
        elif mode == "proposal_review":
            proposal = kwargs.get("proposal", {})
            self._review_proposal(proposal)
        elif mode == "dependency_check":
            self._audit_dependencies()
            self._generate_audit_report()
        self.summarize(f"Lucius audit complete: {len(self.findings)} findings")

    # ================================================================
    # AUDIT FUNCTIONS
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
                    # Extract docstring (first triple-quoted block)
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

    def _audit_duplication(self):
        """Find files with overlapping purpose or duplicated code."""
        self.log.info("Auditing for duplication...")
        if not hasattr(self, "_inventory"):
            return

        # Check for similar filenames suggesting duplication
        name_groups = {}
        for path in self._inventory["modules"]:
            base = Path(path).stem.lower()
            # Normalize: robin_sentinel and sentinel might overlap
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

        # Check for files importing from each other (circular or shadow deps)
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

        # Check requirements.txt or setup.py
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

        # Check for imports of non-standard libraries
        if hasattr(self, "_inventory"):
            all_imports = set()
            for info in self._inventory["modules"].values():
                for imp in info["imports"]:
                    # Extract top-level package
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
                # Check staleness
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

        docs_to_check = [
            (self.CODEBASE_ROOT / "CLAUDE.md", "Institutional memory"),
            (self.CODEBASE_ROOT / "README.md", "Project README"),
            (self.CODEBASE_ROOT / "SOLE-SURVIVOR-PROTOCOL.md", "Recovery protocol"),
            (DESKTOP / "rudy-data" / "batcave-memory" / "BATCAVE.md", "Batcave shared memory"),
        ]

        for path, desc in docs_to_check:
            if path.exists():
                age_hours = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
                lines = path.read_text(errors="replace").count("\n")
                if age_hours > 168:  # 1 week
                    self.findings.append({
                        "type": "doc_stale",
                        "severity": "medium",
                        "title": f"{desc} is stale ({age_hours/24:.0f} days old)",
                        "detail": f"{path.name}: {lines} lines, last modified {age_hours/24:.0f}d ago",
                        "recommendation": "Review and update documentation",
                    })
            else:
                self.findings.append({
                    "type": "doc_missing",
                    "severity": "high" if "README" in str(path) else "medium",
                    "title": f"Missing documentation: {desc}",
                    "detail": f"Expected at {path}",
                    "recommendation": "Create this documentation",
                })

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

        # Tally by severity and type
        for f in self.findings:
            sev = f.get("severity", "unknown")
            typ = f.get("type", "unknown")
            report["summary"]["by_severity"][sev] = report["summary"]["by_severity"].get(sev, 0) + 1
            report["summary"]["by_type"][typ] = report["summary"]["by_type"].get(typ, 0) + 1

        # Write report
        report_file = self.AUDIT_DIR / f"audit-{timestamp}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

        self.log.info(f"Audit report: {report_file}")
        self.log.info(f"Findings: {report['summary']['by_severity']}")

        # Also write human-readable summary
        md_file = self.AUDIT_DIR / f"audit-{timestamp}.md"
        lines = [
            "# Lucius Fox Audit Report",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
        }

        # This is a placeholder for the full review logic.
        # In production, Lucius would:
        # 1. Search PyPI, npm, GitHub for alternatives
        # 2. Check if existing agents/modules overlap
        # 3. Evaluate build-vs-buy tradeoff
        # 4. If custom approved, write implementation spec

        review_file = self.REVIEWS_DIR / f"{record['review_id']}.json"
        with open(review_file, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str)

        self.action(f"Review record: {review_file.name}")
        return record
