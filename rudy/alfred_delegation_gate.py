#!/usr/bin/env python3
"""
Alfred Delegation Gate -- Phase 3 Step 8 (ADR-020 Amendment).

Structural gate that classifies intended operations and routes
local-capable tasks to Robin automatically. Alfred reserves
processing for intelligence-class work that ONLY Alfred can
perform (complex reasoning, cloud API orchestration, strategic
planning, code architecture).

Robin handles: file ops, git operations, system diagnostics,
compilation, linting, process management, local AI inference,
MCP tool execution, Windows automation, routine workflows.

Integration:
    Called by Alfred before executing any local operation.
    Uses robin_alfred_protocol.py for IPC when delegating.

Metrics:
    Tracks delegated vs. retained operations per session.
    Target: >60% delegation rate for local tasks.

Session 139: Phase 3 Step 8 of Andrew-Readiness (ADR-020).
"""

import json
import logging
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    from rudy.paths import RUDY_DATA
except ImportError:
    RUDY_DATA = Path(__file__).resolve().parent.parent / "rudy-data"

try:
    from rudy.robin_alfred_protocol import AlfredMailbox
    _HAS_PROTOCOL = True
except ImportError:
    _HAS_PROTOCOL = False

log = logging.getLogger("delegation_gate")

# Metrics file for session tracking
METRICS_PATH = RUDY_DATA / "coordination" / "delegation-metrics.json"


# -------------------------------------------------------------------
# Operation Classification
# -------------------------------------------------------------------

class OpCategory(Enum):
    """Categories of operations Alfred might perform."""
    FILE_IO = "file_io"           # Read/write/edit files
    GIT = "git"                   # Git operations
    SHELL = "shell"               # Shell commands
    DIAGNOSTICS = "diagnostics"   # System health checks
    LINT_COMPILE = "lint_compile"  # Linting, compilation, CI
    PROCESS_MGMT = "process"      # Process start/stop/check
    LOCAL_AI = "local_ai"           # Ollama inference
    WINDOWS_AUTO = "windows_auto"   # Windows automation
    ROUTINE = "routine"             # Repetitive workflows
    INTELLIGENCE = "intelligence"   # Complex reasoning (Alfred-only)
    CLOUD_API = "cloud_api"         # Cloud API orchestration (Alfred-only)
    STRATEGIC = "strategic"         # Architecture/planning (Alfred-only)
    UNKNOWN = "unknown"


class Disposition(Enum):
    """Routing decision for an operation."""
    DELEGATE = "delegate"   # Send to Robin
    RETAIN = "retain"       # Alfred handles it
    HYBRID = "hybrid"       # Alfred plans, Robin executes


# Categories Robin can handle locally
ROBIN_CAPABLE = {
    OpCategory.FILE_IO,
    OpCategory.GIT,
    OpCategory.SHELL,
    OpCategory.DIAGNOSTICS,
    OpCategory.LINT_COMPILE,
    OpCategory.PROCESS_MGMT,
    OpCategory.LOCAL_AI,
    OpCategory.WINDOWS_AUTO,
    OpCategory.ROUTINE,
}

# Categories only Alfred can handle
ALFRED_ONLY = {
    OpCategory.INTELLIGENCE,
    OpCategory.CLOUD_API,
    OpCategory.STRATEGIC,
}

# Keyword patterns for classification
CLASSIFICATION_PATTERNS = {
    OpCategory.FILE_IO: [
        "read_file", "write_file", "get-content", "set-content",
        "copy-item", "move-item", "remove-item", "new-item",
        "cat ", "head ", "tail ", "mkdir", "rmdir", "dir ",
        "ls ", "file_read", "file_write", "file_edit",
    ],
    OpCategory.GIT: [
        "git ", "git_status", "git_push", "git_pull",
        "git_commit", "git_checkout", "git_branch",
        "git_merge", "git_rebase", "git_diff", "git_log",
        "git_add", "git_stash", "git_full_push",
    ],
    OpCategory.SHELL: [
        "start_process", "shell", "cmd ", "powershell",
        "python ", "node ", "npm ", "pip ", "cargo ",
    ],
    OpCategory.DIAGNOSTICS: [
        "health_check", "check_process", "get-process",
        "system_health", "disk_usage", "cpu_percent",
        "memory_usage", "service_status", "ping ",
        "test-connection", "check_robin", "nervous_system",
    ],
    OpCategory.LINT_COMPILE: [
        "ruff ", "ruff_check", "py_compile", "bandit ",
        "flake8", "mypy ", "pylint", "pytest ",
        "run_ci_local", "ci_check", "lint", "compile",
    ],
    OpCategory.PROCESS_MGMT: [
        "kill_process", "stop-process", "start-service",
        "stop-service", "restart-service", "get-service",
        "cleanup_session", "process_hygiene",
    ],
    OpCategory.LOCAL_AI: [
        "ollama", "gemma", "qwen", "deepseek",
        "nomic-embed", "local_inference", "embedding",
    ],
    OpCategory.WINDOWS_AUTO: [
        "registry", "scheduled_task", "windows-mcp",
        "autohotkey", "winrm", "rustdesk", "tailscale",
    ],
    OpCategory.ROUTINE: [
        "morning_routine", "night_shift", "session_prep",
        "pr_workflow", "health_workflow", "backup",
    ],
}


# -------------------------------------------------------------------
# Delegation Metrics
# -------------------------------------------------------------------

class DelegationMetrics:
    """Track delegation vs. retention per session."""

    def __init__(self, session_number: int = 0):
        self.session_number = session_number
        self._records: list[dict] = []
        self._start_time = datetime.now()

    def record(self, operation: str, category: OpCategory,
               disposition: Disposition, reason: str = ""):
        """Record a delegation decision."""
        self._records.append({
            "timestamp": datetime.now().isoformat(),
            "operation": operation[:200],
            "category": category.value,
            "disposition": disposition.value,
            "reason": reason,
        })

    @property
    def total(self) -> int:
        return len(self._records)

    @property
    def delegated(self) -> int:
        return sum(
            1 for r in self._records
            if r["disposition"] == Disposition.DELEGATE.value
        )

    @property
    def retained(self) -> int:
        return sum(
            1 for r in self._records
            if r["disposition"] == Disposition.RETAIN.value
        )

    @property
    def delegation_rate(self) -> float:
        """Percentage of operations delegated to Robin."""
        if not self._records:
            return 0.0
        return (self.delegated / self.total) * 100

    def summary(self) -> dict:
        """Session delegation summary."""
        by_category: dict[str, dict[str, int]] = {}
        for r in self._records:
            cat = r["category"]
            disp = r["disposition"]
            if cat not in by_category:
                by_category[cat] = {"delegate": 0, "retain": 0, "hybrid": 0}
            by_category[cat][disp] = by_category[cat].get(disp, 0) + 1
        return {
            "session": self.session_number,
            "total_operations": self.total,
            "delegated": self.delegated,
            "retained": self.retained,
            "delegation_rate_pct": round(self.delegation_rate, 1),
            "target_rate_pct": 60.0,
            "meets_target": self.delegation_rate >= 60.0,
            "by_category": by_category,
            "duration_minutes": round(
                (datetime.now() - self._start_time).total_seconds() / 60, 1
            ),
        }

    def save(self) -> None:
        """Persist metrics to coordination file."""
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(METRICS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, indent=2)
        log.info(
            "Delegation metrics saved: %d/%d delegated (%.1f%%)",
            self.delegated, self.total, self.delegation_rate,
        )


# -------------------------------------------------------------------
# The Gate: Classifier + Router
# -------------------------------------------------------------------

class DelegationGate:
    """Structural gate that routes operations to Robin or Alfred.

    Usage:
        gate = DelegationGate(session_number=139)

        # Before any local operation:
        decision = gate.evaluate("git push origin s139/feature")
        if decision.disposition == Disposition.DELEGATE:
            # Send to Robin via protocol
            gate.delegate_to_robin(decision)
        else:
            # Alfred handles it
            pass

        # At session end:
        gate.finalize()
    """

    def __init__(self, session_number: int = 0,
                 robin_online: bool = True):
        self.session_number = session_number
        self.robin_online = robin_online
        self.metrics = DelegationMetrics(session_number)
        self._mailbox: Optional[object] = None
        if _HAS_PROTOCOL and robin_online:
            try:
                self._mailbox = AlfredMailbox(
                    session_number=session_number,
                )
            except Exception as exc:
                log.warning("AlfredMailbox init failed: %s", exc)

    def classify(self, operation: str) -> OpCategory:
        """Classify an operation into a category.

        Args:
            operation: Description of the intended operation
                       (tool name, command, or natural language).

        Returns:
            The OpCategory that best matches the operation.
        """
        op_lower = operation.lower().strip()

        # Check each category's patterns
        best_cat = OpCategory.UNKNOWN
        best_score = 0
        for cat, patterns in CLASSIFICATION_PATTERNS.items():
            score = sum(1 for p in patterns if p in op_lower)
            if score > best_score:
                best_score = score
                best_cat = cat

        # Heuristic fallbacks for unmatched operations
        if best_cat == OpCategory.UNKNOWN:
            if any(w in op_lower for w in ["file", "path", "read", "write"]):
                best_cat = OpCategory.FILE_IO
            elif any(w in op_lower for w in ["reason", "plan", "design", "architect"]):
                best_cat = OpCategory.STRATEGIC
            elif any(w in op_lower for w in ["api", "cloud", "webhook", "fetch"]):
                best_cat = OpCategory.CLOUD_API
            elif any(w in op_lower for w in ["analyze", "review", "evaluate"]):
                best_cat = OpCategory.INTELLIGENCE

        return best_cat

    def evaluate(self, operation: str) -> "GateDecision":
        """Evaluate an operation and return a routing decision.

        Args:
            operation: Description of the intended operation.

        Returns:
            GateDecision with category, disposition, and reason.
        """
        category = self.classify(operation)

        # Robin offline -> retain everything
        if not self.robin_online:
            disposition = Disposition.RETAIN
            reason = "Robin offline -- Alfred handles all operations"
        elif category in ALFRED_ONLY:
            disposition = Disposition.RETAIN
            reason = f"Intelligence-class operation ({category.value})"
        elif category in ROBIN_CAPABLE:
            disposition = Disposition.DELEGATE
            reason = f"Local operation ({category.value}) -- Robin capable"
        elif category == OpCategory.UNKNOWN:
            # Unknown -> retain conservatively
            disposition = Disposition.RETAIN
            reason = "Unclassified operation -- Alfred retains"
        else:
            disposition = Disposition.RETAIN
            reason = "Default retention"

        decision = GateDecision(
            operation=operation,
            category=category,
            disposition=disposition,
            reason=reason,
        )

        # Record metrics
        self.metrics.record(
            operation, category, disposition, reason,
        )

        log.debug(
            "Gate: %s -> %s (%s): %s",
            operation[:60], disposition.value,
            category.value, reason,
        )
        return decision

    def delegate_to_robin(self, decision: "GateDecision") -> str:
        """Delegate an operation to Robin via the mailbox protocol.

        Args:
            decision: The GateDecision to delegate.

        Returns:
            Message ID from the protocol, or empty string on failure.
        """
        if not self._mailbox:
            log.warning("Cannot delegate: no mailbox connection")
            return ""

        try:
            msg_id = self._mailbox.respond_to_robin("task", {
                "task": decision.operation,
                "category": decision.category.value,
                "reason": decision.reason,
                "delegated_at": datetime.now().isoformat(),
                "session": self.session_number,
            })
            log.info(
                "Delegated to Robin [%s]: %s",
                decision.category.value, decision.operation[:80],
            )
            return msg_id
        except Exception as exc:
            log.error("Delegation failed: %s", exc)
            return ""

    def finalize(self) -> dict:
        """Finalize session metrics and save."""
        summary = self.metrics.summary()
        self.metrics.save()
        rate = summary["delegation_rate_pct"]
        target = summary["target_rate_pct"]
        if rate < target:
            log.warning(
                "Delegation rate %.1f%% below target %.1f%%",
                rate, target,
            )
        else:
            log.info(
                "Delegation rate %.1f%% meets target %.1f%%",
                rate, target,
            )
        return summary


# -------------------------------------------------------------------
# Gate Decision Data Class
# -------------------------------------------------------------------

class GateDecision:
    """Result of the delegation gate evaluation."""

    def __init__(self, operation: str, category: OpCategory,
                 disposition: Disposition, reason: str = ""):
        self.operation = operation
        self.category = category
        self.disposition = disposition
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"GateDecision({self.disposition.value}: "
            f"{self.category.value} -> {self.operation[:50]})"
        )

    @property
    def should_delegate(self) -> bool:
        return self.disposition == Disposition.DELEGATE

    @property
    def should_retain(self) -> bool:
        return self.disposition == Disposition.RETAIN


# -------------------------------------------------------------------
# Convenience Functions
# -------------------------------------------------------------------

_gate_instance: Optional[DelegationGate] = None


def get_gate(session_number: int = 0,
             robin_online: bool = True) -> DelegationGate:
    """Get or create the singleton gate instance."""
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = DelegationGate(
            session_number=session_number,
            robin_online=robin_online,
        )
    return _gate_instance


def should_delegate(operation: str,
                    session_number: int = 0) -> bool:
    """Quick check: should this operation be delegated to Robin?

    Args:
        operation: Description of the operation.
        session_number: Current session number.

    Returns:
        True if Robin should handle this operation.
    """
    gate = get_gate(session_number=session_number)
    decision = gate.evaluate(operation)
    return decision.should_delegate


def reset_gate() -> None:
    """Reset the singleton gate (for testing)."""
    global _gate_instance
    _gate_instance = None


# -------------------------------------------------------------------
# CLI Entry Point
# -------------------------------------------------------------------

def main():
    """CLI for testing the delegation gate."""
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )

    p = argparse.ArgumentParser(
        description="Alfred Delegation Gate -- Phase 3 Step 8"
    )
    p.add_argument(
        "operation", nargs="?", default="",
        help="Operation to classify",
    )
    p.add_argument(
        "--session", type=int, default=0,
        help="Session number",
    )
    p.add_argument(
        "--test", action="store_true",
        help="Run classification tests",
    )
    args = p.parse_args()

    if args.test:
        gate = DelegationGate(session_number=args.session)
        test_ops = [
            "git push origin s139/feature",
            "Get-Content 'C:\\file.txt' -Raw",
            "ruff check --select E,F,W rudy/",
            "Design the new caching architecture",
            "Fetch weather API data from openweathermap",
            "Get-Process | Where-Object python",
            "ollama run gemma4:26b",
            "Create scheduled task for backup",
            "Analyze the PR diff for security issues",
        ]
        for op in test_ops:
            d = gate.evaluate(op)
            print(f"  {d.disposition.value:8s} | {d.category.value:12s} | {op}")
        summary = gate.finalize()
        print(f"\nDelegation rate: {summary['delegation_rate_pct']}%")
        print(f"Target: {summary['target_rate_pct']}%")
        print(f"Meets target: {summary['meets_target']}")
    elif args.operation:
        gate = DelegationGate(session_number=args.session)
        d = gate.evaluate(args.operation)
        print(json.dumps({
            "operation": d.operation,
            "category": d.category.value,
            "disposition": d.disposition.value,
            "reason": d.reason,
        }, indent=2))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
