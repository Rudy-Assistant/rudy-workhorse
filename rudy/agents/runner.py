#!/usr/bin/env python3
"""
Unified Agent Runner — bridges scheduled tasks, command runner, and Cowork to the sub-agent system.

Usage:
    python -m rudy.agents.runner system_master [--mode full]
    python -m rudy.agents.runner security_agent
    python -m rudy.agents.runner sentinel
    python -m rudy.agents.runner task_master --mode briefing
    python -m rudy.agents.runner research_intel --mode digest
    python -m rudy.agents.runner operations_monitor
    python -m rudy.agents.runner ALL              # Run all agents sequentially
    python -m rudy.agents.runner health            # Quick health summary of all agents

Called by:
    - Cowork scheduled tasks (via rudy-commands/ scripts)
    - Command runner directly
    - CLI: python -m rudy.cli agent run <name>
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS_DIR = DESKTOP / "rudy-logs"
sys.path.insert(0, str(DESKTOP))

# Agent registry — maps names to (module, class, default_mode)
AGENT_REGISTRY = {
    "system_master": ("rudy.agents.system_master", "SystemMaster", "full"),
    "security_agent": ("rudy.agents.security_agent", "SecurityAgent", "full"),
    "sentinel": ("rudy.agents.sentinel", "Sentinel", "full"),
    "task_master": ("rudy.agents.task_master", "TaskMaster", "briefing"),
    "research_intel": ("rudy.agents.research_intel", "ResearchIntel", "digest"),
    "operations_monitor": ("rudy.agents.operations_monitor", "OperationsMonitor", "full"),
}

# Aliases
AGENT_ALIASES = {
    "system": "system_master",
    "security": "security_agent",
    "ops": "operations_monitor",
    "research": "research_intel",
    "task": "task_master",
    "intel": "research_intel",
}


def load_agent(agent_name: str):
    """Dynamically import and instantiate an agent."""
    import importlib
    if agent_name not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {agent_name}. Available: {', '.join(AGENT_REGISTRY.keys())}")

    module_path, class_name, _ = AGENT_REGISTRY[agent_name]
    module = importlib.import_module(module_path)
    agent_class = getattr(module, class_name)
    return agent_class()


def run_agent(agent_name: str, mode: str = None) -> dict:
    """Run a single agent and return its status dict."""
    if agent_name in AGENT_ALIASES:
        agent_name = AGENT_ALIASES[agent_name]

    _, _, default_mode = AGENT_REGISTRY[agent_name]
    mode = mode or default_mode

    print(f"\n{'='*60}")
    print(f"  Running {agent_name} (mode={mode})")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    agent = load_agent(agent_name)
    agent.execute(mode=mode)
    return agent.status


def run_all(mode: str = "full") -> dict:
    """Run all agents sequentially, return summary."""
    results = {}
    for name in AGENT_REGISTRY:
        try:
            status = run_agent(name, mode)
            results[name] = {
                "status": status.get("status", "unknown"),
                "alerts": len(status.get("critical_alerts", [])),
                "warnings": len(status.get("warnings", [])),
                "actions": len(status.get("actions_taken", [])),
                "duration": status.get("duration_seconds", 0),
                "summary": status.get("summary", ""),
            }
        except Exception as e:
            results[name] = {"status": "error", "error": str(e)}

    # Write aggregate status
    summary_file = LOGS_DIR / "agent-aggregate-status.json"
    aggregate = {
        "timestamp": datetime.now().isoformat(),
        "agents": results,
        "total_alerts": sum(r.get("alerts", 0) for r in results.values()),
        "total_warnings": sum(r.get("warnings", 0) for r in results.values()),
        "total_actions": sum(r.get("actions", 0) for r in results.values()),
        "all_healthy": all(r.get("status") == "healthy" for r in results.values()),
    }
    with open(summary_file, "w") as f:
        json.dump(aggregate, f, indent=2)

    return aggregate


def health_summary() -> dict:
    """Read all agent status files and produce a health summary without running anything."""
    results = {}
    for name in AGENT_REGISTRY:
        status_file = LOGS_DIR / f"{name}-status.json"
        if status_file.exists():
            try:
                with open(status_file) as f:
                    data = json.load(f)
                results[name] = {
                    "status": data.get("status", "unknown"),
                    "last_run": data.get("last_run", "never"),
                    "alerts": len(data.get("critical_alerts", [])),
                    "summary": data.get("summary", ""),
                    "duration": data.get("duration_seconds", 0),
                }
            except Exception:
                results[name] = {"status": "error_reading", "last_run": "unknown"}
        else:
            results[name] = {"status": "never_run", "last_run": "never"}

    return {
        "timestamp": datetime.now().isoformat(),
        "agents": results,
        "all_healthy": all(r.get("status") == "healthy" for r in results.values()),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Rudy Agent Runner")
    parser.add_argument("agent", help="Agent name or 'ALL' or 'health'")
    parser.add_argument("--mode", "-m", default=None, help="Execution mode")
    args = parser.parse_args()

    agent_name = args.agent.lower()

    if agent_name == "all":
        result = run_all(args.mode or "full")
        print(f"\n{'='*60}")
        print(f"  AGGREGATE RESULTS")
        print(f"{'='*60}")
        for name, data in result["agents"].items():
            status_icon = "✓" if data.get("status") == "healthy" else "✗"
            print(f"  {status_icon} {name}: {data.get('status', 'unknown')} — {data.get('summary', '')}")
        print(f"\n  Total: {result['total_alerts']} alerts, {result['total_warnings']} warnings, {result['total_actions']} actions")
        print(f"  All healthy: {result['all_healthy']}")

    elif agent_name == "health":
        result = health_summary()
        print(f"\n{'='*60}")
        print(f"  AGENT HEALTH SUMMARY")
        print(f"{'='*60}")
        for name, data in result["agents"].items():
            status_icon = "✓" if data.get("status") == "healthy" else "?" if data.get("status") == "never_run" else "✗"
            print(f"  {status_icon} {name}: {data.get('status')} (last: {data.get('last_run', 'never')})")
        print(f"\n  All healthy: {result['all_healthy']}")

    else:
        if agent_name in AGENT_ALIASES:
            agent_name = AGENT_ALIASES[agent_name]

        if agent_name not in AGENT_REGISTRY:
            print(f"Unknown agent: {agent_name}")
            print(f"Available: {', '.join(list(AGENT_REGISTRY.keys()) + list(AGENT_ALIASES.keys()) + ['ALL', 'health'])}")
            sys.exit(1)

        status = run_agent(agent_name, args.mode)
        print(f"\nResult: {status.get('status', 'unknown')}")
        print(f"Summary: {status.get('summary', 'N/A')}")
        if status.get("critical_alerts"):
            print(f"ALERTS: {status['critical_alerts']}")


if __name__ == "__main__":
    main()
