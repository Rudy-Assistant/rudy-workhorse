"""
Lucius Plan Impact — Blast radius analysis for planned changes.

Extracted from lucius_fox.py (ADR-005 Phase 2b, Session 71).
"""

import logging
import os
from pathlib import Path

from rudy.paths import REPO_ROOT

log = logging.getLogger("lucius_fox")


def plan_impact(
    files: list,
    description: str = "",
    codebase_root: Path = None,
    known_agents: list = None,
) -> dict:
    """Impact analysis before multi-file changes.

    ADR-004 Compliance: Analyzes the blast radius of planned changes.
    Run BEFORE making multi-file modifications.

    Args:
        files: List of file paths (relative to repo root) to be changed.
        description: Natural language description of the planned change.
        codebase_root: Path to the rudy package root (default: REPO_ROOT / "rudy").
        known_agents: List of agent names to check for impact.

    Returns:
        dict with impact analysis: affected modules, dependents,
        agents, tests, CI checks, risk assessment, and recommendations.
    """
    if codebase_root is None:
        codebase_root = REPO_ROOT / "rudy"
    if known_agents is None:
        known_agents = []

    if not files:
        return {
            "error": "No files provided. Pass files=['path/to/file.py', ...] to analyze impact.",
            "risk": "UNKNOWN",
        }

    analysis = {
        "description": description,
        "planned_files": files,
        "impact": [],
        "affected_agents": [],
        "affected_tests": [],
        "ci_checks": [],
        "import_dependents": {},
        "risk": "LOW",
        "recommendations": [],
    }

    # Resolve paths and categorize
    agent_modules = set()
    core_modules = set()
    workflow_modules = set()
    config_files = set()
    ci_files = set()

    for f in files:
        fp = Path(f)
        name = fp.name

        if "agents/" in f or "agents\\\\" in f:
            agent_modules.add(name)
        if f.startswith("rudy/") and "agents/" not in f and "workflows/" not in f:
            core_modules.add(name)
        if "workflows/" in f:
            workflow_modules.add(name)
        if f.endswith((".yml", ".yaml", ".json", ".toml")):
            config_files.add(name)
        if ".github/" in f:
            ci_files.add(name)

    # Scan for import dependents across codebase
    import_targets = set()
    for f in files:
        fp = Path(f)
        if fp.suffix == ".py":
            stem = fp.stem
            dotpath = str(fp).replace("/", ".").replace("\\", ".").rstrip(".py")
            if dotpath.endswith(".py"):
                dotpath = dotpath[:-3]
            import_targets.add(stem)
            import_targets.add(dotpath)

    if import_targets:
        for root, dirs, filenames in os.walk(codebase_root):
            dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                scan_path = Path(root) / fname
                rel = str(scan_path.relative_to(REPO_ROOT)).replace("\\", "/")
                if rel in files:
                    continue
                try:
                    file_content = scan_path.read_text(encoding="utf-8", errors="replace")
                    for target in import_targets:
                        if target in file_content:
                            if target not in analysis["import_dependents"]:
                                analysis["import_dependents"][target] = []
                            analysis["import_dependents"][target].append(rel)
                except Exception:
                    continue

    # Identify affected agents
    rudy_pkg = codebase_root
    for agent_name in known_agents:
        agent_file = f"rudy/agents/{agent_name}.py"
        if agent_file in files:
            analysis["affected_agents"].append(agent_name)
        agent_path = rudy_pkg / "agents" / f"{agent_name}.py"
        if agent_path.exists():
            try:
                agent_content = agent_path.read_text(encoding="utf-8", errors="replace")
                for target in import_targets:
                    if target in agent_content and agent_name not in analysis["affected_agents"]:
                        analysis["affected_agents"].append(
                            f"{agent_name} (imports changed module)"
                        )
            except Exception:
                pass

    # Identify affected tests
    test_dirs = [REPO_ROOT / "tests"]
    for test_dir in test_dirs:
        if not test_dir.exists():
            continue
        for test_file in test_dir.rglob("*.py"):
            try:
                file_content = test_file.read_text(encoding="utf-8", errors="replace")
                for target in import_targets:
                    if target in file_content:
                        rel = str(test_file.relative_to(REPO_ROOT)).replace("\\", "/")
                        if rel not in analysis["affected_tests"]:
                            analysis["affected_tests"].append(rel)
            except Exception:
                continue

    # Determine which CI checks will run
    analysis["ci_checks"] = ["lint.yml (ruff + py_compile)"]
    if ci_files:
        analysis["ci_checks"].append("CI workflow files modified -- verify syntax")
    if any(f.startswith("rudy/") for f in files):
        analysis["ci_checks"].append("test.yml (smoke tests -- module imports)")
        analysis["ci_checks"].append(
            "lucius-review.yml (bandit + pip-audit + batcave-paths)"
        )

    # Risk assessment
    risk_factors = []
    total_dependents = sum(len(v) for v in analysis["import_dependents"].values())

    if any("__init__" in f for f in files):
        risk_factors.append(
            "Package __init__.py modified -- may break all imports in package"
        )
    if any("paths.py" in f for f in files):
        risk_factors.append(
            "paths.py modified -- central path registry, affects entire codebase"
        )
    if agent_modules:
        risk_factors.append(f"Agent module(s) modified: {', '.join(agent_modules)}")
    if workflow_modules:
        risk_factors.append(
            f"Workflow module(s) modified: {', '.join(workflow_modules)}"
        )
    if total_dependents > 10:
        risk_factors.append(
            f"High dependency count: {total_dependents} files import changed modules"
        )
    if config_files:
        risk_factors.append(f"Config file(s) modified: {', '.join(config_files)}")
    if any("lucius" in f.lower() for f in files):
        risk_factors.append("Lucius module modified -- governance layer change")

    if len(risk_factors) >= 3 or total_dependents > 10:
        analysis["risk"] = "HIGH"
    elif len(risk_factors) >= 1 or total_dependents > 3:
        analysis["risk"] = "MEDIUM"

    analysis["risk_factors"] = risk_factors

    # Recommendations
    if analysis["risk"] == "HIGH":
        analysis["recommendations"].append(
            "Create a dedicated feature branch for this change"
        )
        analysis["recommendations"].append(
            "Run full Lucius hygiene_check after changes"
        )
        analysis["recommendations"].append(
            "Test all affected agents via `python -m rudy.agents.runner health`"
        )
    if total_dependents > 0:
        analysis["recommendations"].append(
            f"Verify {total_dependents} dependent file(s) still work after changes"
        )
    if analysis["affected_tests"]:
        analysis["recommendations"].append(
            f"Run affected tests: {', '.join(analysis['affected_tests'][:5])}"
        )
    if not analysis["affected_tests"] and any(f.startswith("rudy/") for f in files):
        analysis["recommendations"].append(
            "No tests found for changed modules -- consider adding test coverage"
        )

    # Build summary
    summary_lines = [
        f"Impact Analysis: {description or 'multi-file change'}",
        f"Risk: {analysis['risk']}",
        f"Files to change: {len(files)}",
        f"Import dependents: {total_dependents}",
        f"Affected agents: {len(analysis['affected_agents'])}",
        f"Affected tests: {len(analysis['affected_tests'])}",
        f"CI checks: {len(analysis['ci_checks'])}",
    ]
    if risk_factors:
        summary_lines.append("")
        summary_lines.append("Risk factors:")
        for rf in risk_factors:
            summary_lines.append(f"  - {rf}")
    if analysis["recommendations"]:
        summary_lines.append("")
        summary_lines.append("Recommendations:")
        for rec in analysis["recommendations"]:
            summary_lines.append(f"  - {rec}")

    analysis["summary"] = "\n".join(summary_lines)

    log.info(
        "plan: %s risk, %d dependents, %d agents affected",
        analysis["risk"],
        total_dependents,
        len(analysis["affected_agents"]),
    )

    return analysis
