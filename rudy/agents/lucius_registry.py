"""
Lucius Registry — Phase 2: Living Registry (ADR-004 v2.0)

The single source of truth for every artifact in the Batcave ecosystem.
Scans Python modules, agents, Cowork skills, MCP connections, and scheduled
tasks to produce a machine-readable registry.json plus a human-readable
registry-summary.md.

Design constraints:
    - Import isolation (C3): All non-stdlib imports inside function bodies
      with try/except. If this module is broken, lucius_gate still works.
    - Stateless scanning: Each scan regenerates from source. No stale cache.
    - Fast: Target <2s for full registry build on the Batcave codebase.

Output files:
    - {RUDY_DATA}/registry.json       — machine-readable full inventory
    - {RUDY_DATA}/registry-summary.md  — auto-generated human overview

CLI:
    python -m rudy.agents.lucius_registry [build|query|summary]
    python -m rudy.agents.lucius_registry query --search "sentinel"
"""

import ast
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("lucius.registry")

# ---------------------------------------------------------------------------
# Registry schema version — bump when format changes
# ---------------------------------------------------------------------------
REGISTRY_VERSION = "2.0.0"


# ---------------------------------------------------------------------------
# Utility: safe import of rudy.paths
# ---------------------------------------------------------------------------
def _get_paths():
    """Import rudy.paths safely (C3 isolation)."""
    try:
        from rudy.paths import REPO_ROOT, RUDY_DATA, RUDY_LOGS
        return REPO_ROOT, RUDY_DATA, RUDY_LOGS
    except ImportError:
        # Fallback: resolve from this file's location
        repo = Path(__file__).resolve().parent.parent.parent
        return repo, repo.parent / "rudy-data", repo.parent / "rudy-logs"


# ---------------------------------------------------------------------------
# Module scanner
# ---------------------------------------------------------------------------
def scan_python_modules(repo_root: Path) -> list[dict]:
    """Scan all Python modules under rudy/ and scripts/.

    For each .py file, extracts:
        - path (relative to repo root)
        - lines (line count)
        - imports (top-level import names)
        - docstring (first line of module docstring)
        - last_modified (ISO timestamp)
        - size_bytes
    """
    modules = []
    scan_dirs = [repo_root / "rudy", repo_root / "scripts"]

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for py_file in sorted(scan_dir.rglob("*.py")):
            if "__pycache__" in str(py_file):
                continue

            rel_path = str(py_file.relative_to(repo_root)).replace("\\", "/")
            stat = py_file.stat()

            entry = {
                "path": rel_path,
                "lines": 0,
                "imports": [],
                "docstring": "",
                "last_modified": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "size_bytes": stat.st_size,
            }

            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                entry["lines"] = source.count("\n") + 1

                # Parse AST for imports and docstring
                try:
                    tree = ast.parse(source, filename=str(py_file))
                    # Module docstring
                    if (
                        tree.body
                        and isinstance(tree.body[0], ast.Expr)
                        and isinstance(tree.body[0].value, ast.Constant)
                        and isinstance(tree.body[0].value.value, str)
                    ):
                        doc = tree.body[0].value.value.strip()
                        # First meaningful line
                        for line in doc.split("\n"):
                            line = line.strip()
                            if line:
                                entry["docstring"] = line[:200]
                                break

                    # Top-level imports
                    imports = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.add(alias.name.split(".")[0])
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imports.add(node.module.split(".")[0])
                    entry["imports"] = sorted(imports)
                except SyntaxError:
                    entry["docstring"] = "[SYNTAX ERROR]"
            except (OSError, UnicodeDecodeError):
                pass

            modules.append(entry)

    return modules


# ---------------------------------------------------------------------------
# Agent scanner
# ---------------------------------------------------------------------------
def scan_agents(repo_root: Path, logs_dir: Path) -> list[dict]:
    """Scan agent definitions and their runtime status.

    Returns agent name, module path, schedule info, and last-run status.
    """
    agents_dir = repo_root / "rudy" / "agents"
    if not agents_dir.exists():
        return []

    # Known agent mapping (name → module file)
    KNOWN_AGENTS = {
        "system_master": "system_master.py",
        "security_agent": "security_agent.py",
        "sentinel": "sentinel.py",
        "task_master": "task_master.py",
        "research_intel": "research_intel.py",
        "operations_monitor": "operations_monitor.py",
        "lucius_fox": "lucius_fox.py",
    }

    agents = []
    for name, filename in KNOWN_AGENTS.items():
        agent_file = agents_dir / filename
        entry = {
            "name": name,
            "module": f"rudy/agents/{filename}",
            "exists": agent_file.exists(),
            "status": "unknown",
            "last_run": None,
            "last_duration_sec": None,
        }

        # Read status file if present
        status_file = logs_dir / f"{name}-status.json"
        if status_file.exists():
            try:
                status_data = json.loads(
                    status_file.read_text(encoding="utf-8", errors="replace")
                )
                entry["status"] = status_data.get("status", "unknown")
                entry["last_run"] = status_data.get("timestamp")
                entry["last_duration_sec"] = status_data.get("duration_seconds")
            except (json.JSONDecodeError, OSError):
                entry["status"] = "status_file_corrupt"

        if agent_file.exists():
            entry["lines"] = agent_file.read_text(
                encoding="utf-8", errors="replace"
            ).count("\n") + 1

        agents.append(entry)

    return agents


# ---------------------------------------------------------------------------
# Cowork skills scanner
# ---------------------------------------------------------------------------
def scan_cowork_skills() -> list[dict]:
    """Return the known Cowork skills from the capability index.

    In a live Cowork session, these are injected via system prompts.
    We maintain a static list here that matches CLAUDE.md's Capability Index,
    which should be refreshed when new skills are added.
    """
    # Core skills (always available in Cowork)
    SKILLS = [
        {"name": "docx", "type": "core", "triggers": ["word", "docx", "report", "memo"]},
        {"name": "pptx", "type": "core", "triggers": ["powerpoint", "pptx", "slides", "deck"]},
        {"name": "xlsx", "type": "core", "triggers": ["excel", "xlsx", "spreadsheet", "budget"]},
        {"name": "pdf", "type": "core", "triggers": ["pdf", "form", "extract", "merge"]},
        {"name": "schedule", "type": "core", "triggers": ["schedule", "recurring", "cron"]},
        {"name": "skill-creator", "type": "core", "triggers": ["create skill", "optimize skill"]},
        {"name": "research-brief", "type": "core", "triggers": ["research", "investigate", "brief"]},
        {"name": "code-runner", "type": "core", "triggers": ["code", "script", "execute"]},
        # Engineering plugin
        {"name": "engineering:standup", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:code-review", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:architecture", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:incident-response", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:debug", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:deploy-checklist", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:testing-strategy", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:tech-debt", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:system-design", "type": "plugin", "plugin": "Engineering"},
        {"name": "engineering:documentation", "type": "plugin", "plugin": "Engineering"},
        # Productivity plugin
        {"name": "productivity:memory-management", "type": "plugin", "plugin": "Productivity"},
        {"name": "productivity:start", "type": "plugin", "plugin": "Productivity"},
        {"name": "productivity:task-management", "type": "plugin", "plugin": "Productivity"},
        {"name": "productivity:update", "type": "plugin", "plugin": "Productivity"},
        # Operations plugin
        {"name": "operations:capacity-plan", "type": "plugin", "plugin": "Operations"},
        {"name": "operations:change-request", "type": "plugin", "plugin": "Operations"},
        {"name": "operations:compliance-tracking", "type": "plugin", "plugin": "Operations"},
        {"name": "operations:process-doc", "type": "plugin", "plugin": "Operations"},
        {"name": "operations:process-optimization", "type": "plugin", "plugin": "Operations"},
        {"name": "operations:risk-assessment", "type": "plugin", "plugin": "Operations"},
        {"name": "operations:runbook", "type": "plugin", "plugin": "Operations"},
        {"name": "operations:status-report", "type": "plugin", "plugin": "Operations"},
        {"name": "operations:vendor-review", "type": "plugin", "plugin": "Operations"},
        # Legal plugin
        {"name": "legal:brief", "type": "plugin", "plugin": "Legal"},
        {"name": "legal:compliance-check", "type": "plugin", "plugin": "Legal"},
        {"name": "legal:legal-response", "type": "plugin", "plugin": "Legal"},
        {"name": "legal:legal-risk-assessment", "type": "plugin", "plugin": "Legal"},
        {"name": "legal:meeting-briefing", "type": "plugin", "plugin": "Legal"},
        {"name": "legal:review-contract", "type": "plugin", "plugin": "Legal"},
        {"name": "legal:signature-request", "type": "plugin", "plugin": "Legal"},
        {"name": "legal:triage-nda", "type": "plugin", "plugin": "Legal"},
        {"name": "legal:vendor-check", "type": "plugin", "plugin": "Legal"},
        # Data plugin
        {"name": "data:analyze", "type": "plugin", "plugin": "Data"},
        {"name": "data:build-dashboard", "type": "plugin", "plugin": "Data"},
        {"name": "data:create-viz", "type": "plugin", "plugin": "Data"},
        {"name": "data:explore-data", "type": "plugin", "plugin": "Data"},
        {"name": "data:sql-queries", "type": "plugin", "plugin": "Data"},
        {"name": "data:statistical-analysis", "type": "plugin", "plugin": "Data"},
        {"name": "data:validate-data", "type": "plugin", "plugin": "Data"},
        {"name": "data:write-query", "type": "plugin", "plugin": "Data"},
        # Finance plugin
        {"name": "finance:audit-support", "type": "plugin", "plugin": "Finance"},
        {"name": "finance:close-management", "type": "plugin", "plugin": "Finance"},
        {"name": "finance:financial-statements", "type": "plugin", "plugin": "Finance"},
        {"name": "finance:journal-entry", "type": "plugin", "plugin": "Finance"},
        {"name": "finance:reconciliation", "type": "plugin", "plugin": "Finance"},
        {"name": "finance:sox-testing", "type": "plugin", "plugin": "Finance"},
        {"name": "finance:variance-analysis", "type": "plugin", "plugin": "Finance"},
    ]
    return SKILLS


# ---------------------------------------------------------------------------
# MCP scanner
# ---------------------------------------------------------------------------
def scan_mcp_connections(repo_root: Path) -> list[dict]:
    """Scan MCP tier configuration and return connection inventory."""
    tiers_file = repo_root / "rudy" / "agents" / "lucius_mcp_tiers.yml"
    mcps = []

    # Default tier mapping (fallback if YAML missing)
    DEFAULT_TIERS = {
        "desktop-commander": "CRITICAL",
        "github": "IMPORTANT",
        "gmail": "IMPORTANT",
        "google-calendar": "IMPORTANT",
        "notion": "OPTIONAL",
        "chrome": "OPTIONAL",
        "brave-search": "OPTIONAL",
        "huggingface": "OPTIONAL",
        "context7": "OPTIONAL",
        "windows-mcp": "OPTIONAL",
    }

    tiers = dict(DEFAULT_TIERS)

    if tiers_file.exists():
        try:
            import yaml
            data = yaml.safe_load(
                tiers_file.read_text(encoding="utf-8", errors="replace")
            )
            if isinstance(data, dict) and "mcps" in data:
                tiers.update(data["mcps"])
        except Exception:
            pass  # Fall through to defaults

    for name, tier in sorted(tiers.items()):
        mcps.append({
            "name": name,
            "tier": str(tier),
            "source": "lucius_mcp_tiers.yml" if tiers_file.exists() else "defaults",
        })

    return mcps


# ---------------------------------------------------------------------------
# Scheduled tasks scanner (reads from CLAUDE.md known tasks)
# ---------------------------------------------------------------------------
def scan_scheduled_tasks() -> list[dict]:
    """Return known scheduled tasks from the Batcave.

    In a live Oracle environment, these are Windows Task Scheduler entries.
    We maintain a static inventory here that matches CLAUDE.md.
    """
    TASKS = [
        {"name": "RudySystemMaster", "schedule": "Every 5 min", "agent": "system_master"},
        {"name": "RudySecurityAgent", "schedule": "Every 30 min", "agent": "security_agent"},
        {"name": "RudySentinel", "schedule": "Every 15 min", "agent": "sentinel"},
        {"name": "RudyMorningBriefing", "schedule": "Daily 7:30 AM", "agent": "task_master"},
        {"name": "RudyResearchDigest", "schedule": "Daily 6 AM", "agent": "research_intel"},
        {"name": "RudySelfImprove-Mon/Wed/Fri", "schedule": "M/W/F 10 AM", "agent": "research_intel"},
        {"name": "RudyWeeklyMaintenance", "schedule": "Sunday 4 AM", "agent": "operations_monitor"},
        {"name": "RustDeskWatchdog", "schedule": "Every 2 min", "agent": "system"},
        {"name": "TailscaleKeepalive", "schedule": "Every 5 min", "agent": "system"},
        {"name": "ConnectionMonitor", "schedule": "Every 5 min", "agent": "system"},
        {"name": "AutoGitPush", "schedule": "Daily 11:59 PM", "agent": "system"},
    ]
    return TASKS


# ---------------------------------------------------------------------------
# Full registry builder
# ---------------------------------------------------------------------------
def build_registry(
    repo_root: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> dict:
    """Build the complete registry from live scanning.

    Returns the full registry dict and writes it to registry.json.
    """
    _repo, _data, _logs = _get_paths()
    repo_root = repo_root or _repo
    logs_dir = logs_dir or _logs
    data_dir = data_dir or _data

    start = time.perf_counter()

    registry = {
        "version": REGISTRY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "modules": scan_python_modules(repo_root),
        "agents": scan_agents(repo_root, logs_dir),
        "skills": scan_cowork_skills(),
        "mcps": scan_mcp_connections(repo_root),
        "scheduled_tasks": scan_scheduled_tasks(),
        "stats": {},
    }

    elapsed = time.perf_counter() - start

    # Compute stats
    total_lines = sum(m.get("lines", 0) for m in registry["modules"])
    total_files = len(registry["modules"])
    registry["stats"] = {
        "total_files": total_files,
        "total_lines": total_lines,
        "total_agents": len(registry["agents"]),
        "total_skills": len(registry["skills"]),
        "total_mcps": len(registry["mcps"]),
        "total_scheduled_tasks": len(registry["scheduled_tasks"]),
        "scan_duration_sec": round(elapsed, 3),
    }

    # Write registry.json
    registry_path = data_dir / "registry.json"
    data_dir.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(registry, indent=2, default=str),
        encoding="utf-8",
    )

    # Write registry-summary.md
    summary_path = data_dir / "registry-summary.md"
    summary_path.write_text(
        _generate_summary_md(registry),
        encoding="utf-8",
    )

    log.info(
        f"Registry built: {total_files} files, {total_lines} lines, "
        f"{len(registry['agents'])} agents in {elapsed:.2f}s → {registry_path}"
    )

    return registry


# ---------------------------------------------------------------------------
# Query engine
# ---------------------------------------------------------------------------
def query_registry(
    search: str,
    registry: Optional[dict] = None,
    registry_path: Optional[Path] = None,
) -> list[dict]:
    """Search the registry for artifacts matching a query.

    Searches across module paths, docstrings, agent names, skill names,
    and MCP names. Returns matching entries ranked by relevance.

    Args:
        search: Search term (case-insensitive substring match).
        registry: Pre-loaded registry dict, or None to load from disk.
        registry_path: Path to registry.json, or None for default.

    Returns:
        List of {type, name, path, match_context, score} dicts.
    """
    if registry is None:
        _, data_dir, _ = _get_paths()
        rp = registry_path or (data_dir / "registry.json")
        if not rp.exists():
            return [{"error": "Registry not found. Run 'build' first."}]
        registry = json.loads(rp.read_text(encoding="utf-8"))

    search_lower = search.lower()
    results = []

    # Search modules
    for mod in registry.get("modules", []):
        score = 0
        match_ctx = []
        path_lower = mod["path"].lower()
        doc_lower = mod.get("docstring", "").lower()

        if search_lower in path_lower:
            score += 10
            match_ctx.append(f"path: {mod['path']}")
        if search_lower in doc_lower:
            score += 5
            match_ctx.append(f"docstring: {mod['docstring'][:100]}")
        # Check imports
        for imp in mod.get("imports", []):
            if search_lower in imp.lower():
                score += 3
                match_ctx.append(f"imports: {imp}")
                break

        if score > 0:
            results.append({
                "type": "module",
                "name": Path(mod["path"]).stem,
                "path": mod["path"],
                "lines": mod.get("lines", 0),
                "match_context": "; ".join(match_ctx),
                "score": score,
            })

    # Search agents
    for agent in registry.get("agents", []):
        if search_lower in agent["name"].lower() or search_lower in agent["module"].lower():
            results.append({
                "type": "agent",
                "name": agent["name"],
                "path": agent["module"],
                "status": agent.get("status", "unknown"),
                "match_context": f"agent: {agent['name']} ({agent.get('status', 'unknown')})",
                "score": 15,
            })

    # Search skills
    for skill in registry.get("skills", []):
        if search_lower in skill["name"].lower():
            results.append({
                "type": "skill",
                "name": skill["name"],
                "path": "",
                "match_context": f"skill: {skill['name']} ({skill['type']})",
                "score": 8,
            })
        # Check triggers
        for trigger in skill.get("triggers", []):
            if search_lower in trigger.lower():
                results.append({
                    "type": "skill",
                    "name": skill["name"],
                    "path": "",
                    "match_context": f"trigger: {trigger}",
                    "score": 6,
                })
                break

    # Search MCPs
    for mcp in registry.get("mcps", []):
        if search_lower in mcp["name"].lower():
            results.append({
                "type": "mcp",
                "name": mcp["name"],
                "path": "",
                "match_context": f"mcp: {mcp['name']} (tier: {mcp['tier']})",
                "score": 12,
            })

    # Search scheduled tasks
    for task in registry.get("scheduled_tasks", []):
        if search_lower in task["name"].lower() or search_lower in task.get("agent", "").lower():
            results.append({
                "type": "scheduled_task",
                "name": task["name"],
                "path": "",
                "match_context": f"task: {task['name']} ({task['schedule']})",
                "score": 7,
            })

    # Deduplicate: keep highest-scoring entry per (type, name, path)
    seen = {}
    for r in results:
        key = (r["type"], r["name"], r.get("path", ""))
        if key not in seen or r["score"] > seen[key]["score"]:
            seen[key] = r
    results = list(seen.values())

    # Sort by score descending
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Summary generator
# ---------------------------------------------------------------------------
def _generate_summary_md(registry: dict) -> str:
    """Generate a human-readable markdown summary from the registry."""
    stats = registry.get("stats", {})
    lines = [
        "# Batcave Registry Summary",
        "",
        f"**Generated:** {registry.get('generated_at', 'unknown')}",
        f"**Version:** {registry.get('version', 'unknown')}",
        f"**Scan time:** {stats.get('scan_duration_sec', '?')}s",
        "",
        "## Stats",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Python files | {stats.get('total_files', 0)} |",
        f"| Total lines | {stats.get('total_lines', 0):,} |",
        f"| Agents | {stats.get('total_agents', 0)} |",
        f"| Cowork skills | {stats.get('total_skills', 0)} |",
        f"| MCP connections | {stats.get('total_mcps', 0)} |",
        f"| Scheduled tasks | {stats.get('total_scheduled_tasks', 0)} |",
        "",
        "## Agents",
        "",
        "| Agent | Status | Lines | Last Run |",
        "|-------|--------|-------|----------|",
    ]

    for agent in registry.get("agents", []):
        status_icon = {"healthy": "✅", "error": "❌", "unknown": "❓"}.get(
            agent.get("status", "unknown"), "❓"
        )
        lines.append(
            f"| {agent['name']} | {status_icon} {agent.get('status', 'unknown')} "
            f"| {agent.get('lines', '?')} | {agent.get('last_run', 'never')} |"
        )

    lines.extend([
        "",
        "## Largest Modules (top 15)",
        "",
        "| Module | Lines | Docstring |",
        "|--------|-------|-----------|",
    ])

    sorted_mods = sorted(
        registry.get("modules", []),
        key=lambda m: m.get("lines", 0),
        reverse=True,
    )[:15]
    for mod in sorted_mods:
        doc = mod.get("docstring", "")[:60]
        lines.append(f"| {mod['path']} | {mod.get('lines', 0):,} | {doc} |")

    lines.extend([
        "",
        "## MCP Connections",
        "",
        "| Name | Tier |",
        "|------|------|",
    ])
    for mcp in registry.get("mcps", []):
        tier_icon = {"CRITICAL": "🔴", "IMPORTANT": "🟡", "OPTIONAL": "🟢"}.get(
            mcp.get("tier", ""), ""
        )
        lines.append(f"| {mcp['name']} | {tier_icon} {mcp['tier']} |")

    lines.extend([
        "",
        "## Scheduled Tasks",
        "",
        "| Task | Schedule | Agent |",
        "|------|----------|-------|",
    ])
    for task in registry.get("scheduled_tasks", []):
        lines.append(f"| {task['name']} | {task['schedule']} | {task.get('agent', '')} |")

    lines.extend(["", "---", f"*Auto-generated by Lucius Registry v{REGISTRY_VERSION}*", ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main():
    """CLI dispatcher for lucius_registry."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Lucius Registry — Batcave artifact inventory"
    )
    parser.add_argument(
        "command",
        choices=["build", "query", "summary"],
        help="build: scan and write registry | query: search | summary: print stats",
    )
    parser.add_argument("--search", "-s", help="Search term (for query command)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.command == "build":
        registry = build_registry()
        stats = registry["stats"]
        if args.json:
            print(json.dumps(registry, indent=2, default=str))
        else:
            print(
                f"Registry built: {stats['total_files']} files, "
                f"{stats['total_lines']:,} lines, "
                f"{stats['total_agents']} agents, "
                f"{stats['total_skills']} skills, "
                f"{stats['total_mcps']} MCPs, "
                f"{stats['total_scheduled_tasks']} scheduled tasks "
                f"in {stats['scan_duration_sec']}s"
            )

    elif args.command == "query":
        if not args.search:
            parser.error("--search required for query command")
        results = query_registry(args.search)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            if not results:
                print(f"No results for '{args.search}'")
            else:
                for r in results:
                    print(
                        f"  [{r['type']:15s}] {r['name']:30s} "
                        f"score={r['score']}  {r.get('match_context', '')}"
                    )

    elif args.command == "summary":
        _, data_dir, _ = _get_paths()
        rp = data_dir / "registry.json"
        if not rp.exists():
            print("Registry not found. Run 'build' first.")
            return
        registry = json.loads(rp.read_text(encoding="utf-8"))
        print(_generate_summary_md(registry))


if __name__ == "__main__":
    main()
