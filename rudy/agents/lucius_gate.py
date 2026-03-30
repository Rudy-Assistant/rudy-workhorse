"""
Lucius Gate — Session governance with circuit breakers and degraded-mode fallbacks.

ADR-004 v2.1 Addendum (2026-03-30): Phase 1A deliverable.
Conditions addressed: C1 (circuit breaker), C2 (MCP tiered criticality),
C3 (import isolation), C5 (latency baselines via GateMetrics).

IMPORT ISOLATION (Condition C3):
    This module has ZERO non-stdlib hard dependencies at module level.
    Only these are permitted at the top: os, sys, json, time, logging,
    dataclasses, typing, pathlib, enum.
    All other imports (lucius_registry, lucius_scorer, func_timeout, yaml,
    rudy.paths, etc.) MUST be inside function bodies wrapped in try/except.

If this module fails to import, the entire governance layer is bricked.
This must be the most robust code in the system.
"""

import enum
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Module-level logger (stdlib only)
# ---------------------------------------------------------------------------
log = logging.getLogger("lucius_gate")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GateCheckState(enum.Enum):
    """Outcome of a single gate check."""
    PASS = "PASS"
    FAIL = "FAIL"
    DEGRADED = "DEGRADED"


class MCPTier(enum.Enum):
    """MCP criticality tiers per ADR-004 v2.1 Section 2.3."""
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    OPTIONAL = "OPTIONAL"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GateCheck:
    """Result of a single gate check."""
    name: str
    passed: Optional[bool]  # None = could not determine (DEGRADED)
    detail: str = ""
    state: GateCheckState = GateCheckState.PASS
    elapsed_sec: float = 0.0

    def __post_init__(self):
        # Infer state from passed if not explicitly set to DEGRADED
        if self.state != GateCheckState.DEGRADED:
            if self.passed is True:
                self.state = GateCheckState.PASS
            elif self.passed is False:
                self.state = GateCheckState.FAIL
            else:
                self.state = GateCheckState.DEGRADED


@dataclass
class GateMetrics:
    """Timing data for a complete gate pass. ADR-004 v2.1 Section 2.5."""
    gate_name: str
    total_elapsed_sec: float = 0.0
    check_timings: Dict[str, float] = field(default_factory=dict)
    timestamp: str = ""
    session_number: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class GateResult:
    """Aggregate result of a full gate pass."""
    passed: bool  # True only if all CRITICAL checks PASS
    degraded: bool  # True if any check returned DEGRADED
    checks: List[GateCheck] = field(default_factory=list)
    metrics: Optional[GateMetrics] = None
    recommended_skills: List[str] = field(default_factory=list)
    open_findings: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.state == GateCheckState.PASS)
        failed = sum(1 for c in self.checks if c.state == GateCheckState.FAIL)
        degraded = sum(1 for c in self.checks if c.state == GateCheckState.DEGRADED)
        status = "PASS" if self.passed else "BLOCKED"
        if self.degraded:
            status += " (DEGRADED)"
        return f"Gate {status}: {passed}/{total} passed, {failed} failed, {degraded} degraded"

    def to_dict(self) -> dict:
        """Serializable dictionary for logging/vault storage."""
        return {
            "passed": self.passed,
            "degraded": self.degraded,
            "summary": self.summary(),
            "checks": [
                {
                    "name": c.name,
                    "state": c.state.value,
                    "passed": c.passed,
                    "detail": c.detail,
                    "elapsed_sec": round(c.elapsed_sec, 4),
                }
                for c in self.checks
            ],
            "metrics": {
                "gate_name": self.metrics.gate_name,
                "total_elapsed_sec": round(self.metrics.total_elapsed_sec, 4),
                "check_timings": {
                    k: round(v, 4)
                    for k, v in self.metrics.check_timings.items()
                },
                "timestamp": self.metrics.timestamp,
                "session_number": self.metrics.session_number,
            } if self.metrics else None,
            "recommended_skills": self.recommended_skills,
            "open_findings_count": len(self.open_findings),
        }


# ---------------------------------------------------------------------------
# MCP Tier Configuration Loading
# ---------------------------------------------------------------------------

# Default tiers used when YAML file is missing or unreadable.
# These match ADR-004 v2.1 Section 2.3.
DEFAULT_MCP_TIERS: Dict[str, str] = {
    "github": "CRITICAL",
    "desktop-commander": "CRITICAL",
    "gmail": "IMPORTANT",
    "google-calendar": "IMPORTANT",
    "notion": "IMPORTANT",
    "windows-mcp": "IMPORTANT",
    "brave-search": "OPTIONAL",
    "huggingface": "OPTIONAL",
    "context7": "OPTIONAL",
    "chrome": "OPTIONAL",
}

# Default timeout per check (seconds). Conservative until Phase 1B measurement.
DEFAULT_CHECK_TIMEOUT_SEC: float = 30.0

# Maximum total gate time (seconds).
MAX_GATE_TIMEOUT_SEC: float = 300.0


def load_mcp_tiers(config_path: Optional[str] = None) -> Dict[str, MCPTier]:
    """Load MCP tier assignments from YAML config.

    Falls back to DEFAULT_MCP_TIERS if YAML is unavailable.
    All external imports (yaml, rudy.paths) are inside this function body.

    Returns:
        Dict mapping MCP name -> MCPTier enum.
    """
    tiers: Dict[str, MCPTier] = {}
    raw: Optional[dict] = None

    # Resolve config path
    if config_path is None:
        try:
            from pathlib import Path as _P
            config_path = str(
                _P(__file__).resolve().parent / "lucius_mcp_tiers.yml"
            )
        except Exception:
            config_path = None

    # Attempt to load YAML
    if config_path and os.path.isfile(config_path):
        try:
            import yaml  # noqa: delayed import per C3
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except ImportError:
            log.warning("PyYAML not installed; falling back to default MCP tiers")
            raw = None
        except Exception as e:
            log.warning(f"Failed to read MCP tier config: {e}; using defaults")
            raw = None
    else:
        log.info("MCP tier config not found; using built-in defaults")

    # Parse raw config or use defaults
    source = raw.get("mcps", {}) if isinstance(raw, dict) else {}
    if not source:
        source = DEFAULT_MCP_TIERS

    for mcp_name, tier_str in source.items():
        tier_str_upper = str(tier_str).upper()
        try:
            tiers[str(mcp_name).lower()] = MCPTier(tier_str_upper)
        except ValueError:
            log.warning(f"Unknown tier '{tier_str}' for MCP '{mcp_name}'; defaulting to OPTIONAL")
            tiers[str(mcp_name).lower()] = MCPTier.OPTIONAL

    return tiers


# ---------------------------------------------------------------------------
# Protected Branches (reuse from lucius_fox.py pattern, but self-contained)
# ---------------------------------------------------------------------------

PROTECTED_BRANCHES = frozenset({"main", "master"})


# ---------------------------------------------------------------------------
# Circuit Breaker — run_check()
# ---------------------------------------------------------------------------


def run_check(
    fn: Callable[[], "GateCheck"],
    name: str,
    timeout_sec: float = DEFAULT_CHECK_TIMEOUT_SEC,
    criticality: MCPTier = MCPTier.OPTIONAL,
) -> GateCheck:
    """Execute a single gate check with circuit breaker protection.

    ADR-004 v2.1 Section 2.2: Every check returns PASS/FAIL/DEGRADED.
    Timeout + fallback per check. Configurable criticality.

    The func_timeout dependency is optional. If unavailable, the check
    runs without timeout protection and a DEGRADED warning is logged
    for the timeout mechanism itself.

    Args:
        fn: Callable that returns a GateCheck (or raises).
        name: Human-readable check name.
        timeout_sec: Maximum seconds before timeout.
        criticality: MCPTier controlling block/warn/log behavior.

    Returns:
        GateCheck with appropriate state.
    """
    start = time.perf_counter()

    # Try to get func_timeout for deadline enforcement
    _func_timeout = None
    _FunctionTimedOut = None
    try:
        from func_timeout import func_timeout as _ft, FunctionTimedOut as _fto  # noqa: C3
        _func_timeout = _ft
        _FunctionTimedOut = _fto
    except ImportError:
        log.debug("func_timeout not available; running check without timeout protection")

    try:
        if _func_timeout is not None and _FunctionTimedOut is not None:
            result = _func_timeout(timeout_sec, fn)
        else:
            result = fn()

        elapsed = time.perf_counter() - start

        # fn should return a GateCheck, but be defensive
        if isinstance(result, GateCheck):
            result.elapsed_sec = elapsed
            return result

        # If fn returned a bool or something unexpected, wrap it
        return GateCheck(
            name=name,
            passed=bool(result),
            detail="check returned non-GateCheck value",
            elapsed_sec=elapsed,
        )

    except Exception as e:
        elapsed = time.perf_counter() - start
        # Determine if this was a timeout
        is_timeout = _FunctionTimedOut is not None and isinstance(e, _FunctionTimedOut)
        detail = f"Timeout after {timeout_sec}s" if is_timeout else f"{type(e).__name__}: {e}"

        log.warning(f"Check '{name}' degraded ({criticality.value}): {detail}")

        return GateCheck(
            name=name,
            passed=None,
            detail=detail,
            state=GateCheckState.DEGRADED,
            elapsed_sec=elapsed,
        )


# ---------------------------------------------------------------------------
# Individual Check Functions
# ---------------------------------------------------------------------------


def _check_mcp_connection(mcp_name: str) -> GateCheck:
    """Check if an MCP server is reachable.

    Phase 1A: stub that checks for known environment indicators.
    Phase 1B will wire this to actual MCP connection tests.
    """
    # In Phase 1A we cannot actually probe MCP connections from a pure-Python
    # context. Return DEGRADED to indicate the check couldn't run, which is
    # honest and lets the gate proceed according to tier rules.
    return GateCheck(
        name=f"mcp_{mcp_name}",
        passed=None,
        detail=f"MCP connection check not wired (Phase 1A stub)",
        state=GateCheckState.DEGRADED,
    )


def _check_protected_branch(branch: str) -> GateCheck:
    """Verify a branch is not in the protected set."""
    if branch in PROTECTED_BRANCHES:
        return GateCheck(
            name="protected_branch",
            passed=False,
            detail=f"Branch '{branch}' is protected; push blocked",
        )
    return GateCheck(
        name="protected_branch",
        passed=True,
        detail=f"Branch '{branch}' is not protected",
    )


def _check_context_window(context_window_pct: Optional[float] = None) -> GateCheck:
    """Check that context window usage percentage was provided."""
    if context_window_pct is None:
        return GateCheck(
            name="context_window_pct",
            passed=False,
            detail="context_window_pct not provided",
        )
    return GateCheck(
        name="context_window_pct",
        passed=True,
        detail=f"context_window_pct={context_window_pct:.1f}%",
    )


def _check_vault_accessible() -> GateCheck:
    """Check that at least one vault destination is writable.

    Imports rudy.paths inside function body per C3 import isolation.
    """
    try:
        # Delayed import per C3
        from rudy.paths import REPO_ROOT  # noqa
        vault_path = REPO_ROOT / "vault"
        if vault_path.is_dir():
            return GateCheck(
                name="vault_accessible",
                passed=True,
                detail=f"vault found at {vault_path}",
            )
        return GateCheck(
            name="vault_accessible",
            passed=False,
            detail=f"vault directory not found at {vault_path}",
        )
    except Exception as e:
        return GateCheck(
            name="vault_accessible",
            passed=None,
            detail=f"Could not check vault: {e}",
            state=GateCheckState.DEGRADED,
        )


def _check_repo_root() -> GateCheck:
    """Verify the repo root is detectable and contains expected markers."""
    try:
        from rudy.paths import REPO_ROOT  # noqa
        claude_md = REPO_ROOT / "CLAUDE.md"
        if claude_md.is_file():
            return GateCheck(
                name="repo_root",
                passed=True,
                detail=f"CLAUDE.md found at {REPO_ROOT}",
            )
        return GateCheck(
            name="repo_root",
            passed=False,
            detail=f"CLAUDE.md not found at {REPO_ROOT}",
        )
    except Exception as e:
        return GateCheck(
            name="repo_root",
            passed=None,
            detail=f"Could not resolve repo root: {e}",
            state=GateCheckState.DEGRADED,
        )


# ---------------------------------------------------------------------------
# Gate Functions
# ---------------------------------------------------------------------------


def _build_gate_result(
    gate_name: str,
    checks: List[GateCheck],
    mcp_tiers: Dict[str, MCPTier],
    start_time: float,
    session_number: int = 0,
) -> GateResult:
    """Assemble a GateResult from a list of completed checks.

    Logic:
        - passed = True only if NO check with CRITICAL tier returned FAIL or DEGRADED
        - degraded = True if any check returned DEGRADED
    """
    elapsed = time.perf_counter() - start_time
    metrics = GateMetrics(
        gate_name=gate_name,
        total_elapsed_sec=elapsed,
        check_timings={c.name: c.elapsed_sec for c in checks},
        session_number=session_number,
    )

    any_degraded = any(c.state == GateCheckState.DEGRADED for c in checks)

    # Determine if any CRITICAL check failed or degraded
    all_critical_ok = True
    for c in checks:
        # Check if this is an MCP check and get its tier
        tier = MCPTier.OPTIONAL  # default
        if c.name.startswith("mcp_"):
            mcp_name = c.name[4:]  # strip "mcp_" prefix
            tier = mcp_tiers.get(mcp_name, MCPTier.OPTIONAL)

        # Non-MCP checks that fail are treated as CRITICAL blockers
        if not c.name.startswith("mcp_") and c.state == GateCheckState.FAIL:
            all_critical_ok = False
            break

        # CRITICAL MCP checks that fail or degrade block the session
        if tier == MCPTier.CRITICAL and c.state in (
            GateCheckState.FAIL,
            GateCheckState.DEGRADED,
        ):
            all_critical_ok = False
            break

    return GateResult(
        passed=all_critical_ok,
        degraded=any_degraded,
        checks=checks,
        metrics=metrics,
    )


def session_start_gate(
    session_number: int = 0,
    mcp_tiers_path: Optional[str] = None,
    check_timeout_sec: float = DEFAULT_CHECK_TIMEOUT_SEC,
) -> GateResult:
    """Run all pre-session checks. Called when a new session begins.

    Checks:
        1. Repo root is detectable
        2. Vault is accessible
        3. MCP connections (per tier)

    Returns:
        GateResult with passed=True only if all CRITICAL checks pass.
    """
    gate_start = time.perf_counter()
    mcp_tiers = load_mcp_tiers(mcp_tiers_path)
    checks: List[GateCheck] = []

    # Structural checks
    checks.append(run_check(
        fn=_check_repo_root,
        name="repo_root",
        timeout_sec=check_timeout_sec,
        criticality=MCPTier.CRITICAL,
    ))
    checks.append(run_check(
        fn=_check_vault_accessible,
        name="vault_accessible",
        timeout_sec=check_timeout_sec,
        criticality=MCPTier.IMPORTANT,
    ))

    # MCP connectivity checks
    for mcp_name, tier in mcp_tiers.items():
        check = run_check(
            fn=lambda _name=mcp_name: _check_mcp_connection(_name),
            name=f"mcp_{mcp_name}",
            timeout_sec=check_timeout_sec,
            criticality=tier,
        )
        checks.append(check)

    result = _build_gate_result(
        gate_name="session_start",
        checks=checks,
        mcp_tiers=mcp_tiers,
        start_time=gate_start,
        session_number=session_number,
    )

    log.info(result.summary())
    return result


def pre_commit_check(
    branch: str,
    check_timeout_sec: float = DEFAULT_CHECK_TIMEOUT_SEC,
) -> GateResult:
    """Run pre-commit/pre-push checks. Called before git operations.

    Checks:
        1. Branch is not protected

    Returns:
        GateResult. If DEGRADED, the caller (Robin) should log and allow
        the push — bricking Robin is worse than a branch violation.
    """
    gate_start = time.perf_counter()
    checks: List[GateCheck] = []

    checks.append(run_check(
        fn=lambda: _check_protected_branch(branch),
        name="protected_branch",
        timeout_sec=check_timeout_sec,
        criticality=MCPTier.CRITICAL,
    ))

    return _build_gate_result(
        gate_name="pre_commit",
        checks=checks,
        mcp_tiers={},
        start_time=gate_start,
    )


def post_session_gate(
    session_number: int = 0,
    context_window_pct: Optional[float] = None,
    check_timeout_sec: float = DEFAULT_CHECK_TIMEOUT_SEC,
) -> GateResult:
    """Run post-session checks before handoff. Called by HandoffWriter.

    Checks:
        1. context_window_pct was provided
        2. Vault is accessible (for writing handoff artifacts)

    Returns:
        GateResult. If the gate itself fails (DEGRADED), the caller
        should log and allow the handoff with compliance_score=0.
    """
    gate_start = time.perf_counter()
    checks: List[GateCheck] = []

    checks.append(run_check(
        fn=lambda: _check_context_window(context_window_pct),
        name="context_window_pct",
        timeout_sec=check_timeout_sec,
        criticality=MCPTier.CRITICAL,
    ))
    checks.append(run_check(
        fn=_check_vault_accessible,
        name="vault_accessible",
        timeout_sec=check_timeout_sec,
        criticality=MCPTier.IMPORTANT,
    ))

    return _build_gate_result(
        gate_name="post_session",
        checks=checks,
        mcp_tiers={},
        start_time=gate_start,
        session_number=session_number,
    )
