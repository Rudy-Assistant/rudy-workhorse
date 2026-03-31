"""
Lucius Gate â€” Session governance with circuit breakers and degraded-mode fallbacks.

ADR-004 v2.1 Addendum (2026-03-30): Phase 1A deliverable.
Phase 1C (2026-03-30): Real MCP connectivity checks, chaos testing.
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
    recommendations: List[str] = field(default_factory=list)
    compliance_score: Optional[float] = None  # Nuanced 0-100 from scorer (Phase 3)
    score_report: Optional[Dict[str, Any]] = None  # Full score breakdown

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
            "recommendations": self.recommendations,
            "compliance_score": self.compliance_score,
            "score_report": self.score_report,
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
            import yaml  # noqa: F401, E402 â€” delayed import per C3
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


def load_mcp_timeouts(config_path: Optional[str] = None) -> Dict[str, float]:
    """Load per-MCP timeout overrides from YAML config.

    Falls back to DEFAULT_CHECK_TIMEOUT_SEC for any MCP not listed.
    All external imports (yaml) are inside this function body per C3.

    Returns:
        Dict mapping MCP name -> timeout in seconds.
    """
    timeouts: Dict[str, float] = {}

    # Resolve config path
    if config_path is None:
        try:
            config_path = str(
                Path(__file__).resolve().parent / "lucius_mcp_tiers.yml"
            )
        except Exception:
            config_path = None

    if config_path and os.path.isfile(config_path):
        try:
            import yaml  # noqa: C3
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except ImportError:
            log.debug("PyYAML not installed; using default timeouts")
            return timeouts
        except Exception as e:
            log.debug(f"Failed to read timeout config: {e}")
            return timeouts

        if isinstance(raw, dict):
            raw_timeouts = raw.get("timeouts", {})
            if isinstance(raw_timeouts, dict):
                for mcp_name, timeout_val in raw_timeouts.items():
                    try:
                        timeouts[str(mcp_name).lower()] = float(timeout_val)
                    except (ValueError, TypeError):
                        log.debug(f"Invalid timeout for {mcp_name}: {timeout_val}")

    return timeouts



# ---------------------------------------------------------------------------
# Protected Branches (reuse from lucius_fox.py pattern, but self-contained)
# ---------------------------------------------------------------------------

PROTECTED_BRANCHES = frozenset({"main", "master"})


# ---------------------------------------------------------------------------
# Circuit Breaker â€” run_check()
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



# ---------------------------------------------------------------------------
# Phase 1C: Real MCP connectivity checks (replaces Phase 1A stubs)
# All non-stdlib imports inside function bodies per C3 import isolation.
# ---------------------------------------------------------------------------

# Module-level cache for .claude.json data (avoid repeated I/O per gate pass)
_claude_json_cache: Dict[str, Any] = {}


def _read_claude_json_data() -> dict:
    """Read and cache .claude.json from user home directory.

    Returns the parsed JSON dict, or empty dict on failure.
    Result is cached in _claude_json_cache for the gate pass lifetime.
    """
    if "data" in _claude_json_cache:
        return _claude_json_cache["data"]

    try:
        home = Path.home()
        claude_json_path = home / ".claude.json"
        if not claude_json_path.exists():
            _claude_json_cache["data"] = {}
            return {}
        with open(claude_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _claude_json_cache["data"] = data
        return data
    except Exception as e:
        log.debug(f"Could not read .claude.json: {e}")
        _claude_json_cache["data"] = {}
        return {}


def _process_exists(process_name: str, cmdline_contains: str = None) -> bool:
    """Check if a Windows process exists, optionally matching command line.

    Uses Get-CimInstance Win32_Process for command line access.
    Falls back to tasklist.exe for simple name checks.

    Args:
        process_name: Process name (without .exe).
        cmdline_contains: Optional substring to match in CommandLine.

    Returns:
        True if a matching process was found.
    """
    import subprocess  # noqa: C3

    if cmdline_contains:
        # Need full command line -- use CIM
        try:
            ps_cmd = (
                f"Get-CimInstance Win32_Process -Filter "
                f"\"Name LIKE '%{process_name}%'\" "
                f"| Select-Object -ExpandProperty CommandLine"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and cmdline_contains.lower() in result.stdout.lower():
                return True
        except Exception:
            pass
        return False

    # Simple existence check -- tasklist is fast and reliable
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FI", f"IMAGENAME eq {process_name}.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return process_name.lower() in result.stdout.lower()
    except Exception:
        return False


def _check_mcp_desktop_commander() -> GateCheck:
    """desktop-commander: node process with 'desktop-commander' in cmdline."""
    import subprocess  # noqa: C3

    try:
        if _process_exists("node", cmdline_contains="desktopcommander"):
            return GateCheck(
                name="mcp_desktop-commander",
                passed=True,
                detail="desktop-commander node process detected via cmdline",
            )
        # Fallback: any node.exe running is a weak signal
        if _process_exists("node"):
            return GateCheck(
                name="mcp_desktop-commander",
                passed=None,
                detail="node processes found but desktop-commander not confirmed in cmdline",
                state=GateCheckState.DEGRADED,
            )
        return GateCheck(
            name="mcp_desktop-commander",
            passed=False,
            detail="no node process found -- desktop-commander not running",
        )
    except Exception as e:
        return GateCheck(
            name="mcp_desktop-commander",
            passed=None,
            detail=f"process check failed: {type(e).__name__}",
            state=GateCheckState.DEGRADED,
        )


def _check_mcp_windows_mcp() -> GateCheck:
    """windows-mcp: runs as its own named executable."""
    try:
        if _process_exists("windows-mcp"):
            return GateCheck(
                name="mcp_windows-mcp",
                passed=True,
                detail="windows-mcp process detected",
            )
        return GateCheck(
            name="mcp_windows-mcp",
            passed=False,
            detail="windows-mcp process not found",
        )
    except Exception as e:
        return GateCheck(
            name="mcp_windows-mcp",
            passed=None,
            detail=f"process check failed: {type(e).__name__}",
            state=GateCheckState.DEGRADED,
        )


def _check_mcp_github() -> GateCheck:
    """github: check MCP process first, then validate PAT if available.

    Primary: Detect server-github node process running (MCP is alive).
    Secondary: If PAT found (env var or file), validate via GitHub API.
    """
    import urllib.request  # noqa: C3
    import urllib.error  # noqa: C3

    # Primary: check if the GitHub MCP node process is running
    mcp_process_running = _process_exists("node", cmdline_contains="server-github")

    # Secondary: try to find and validate a PAT
    pat = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

    if not pat:
        # Try PAT file at known locations
        pat_candidates = []
        try:
            from rudy.paths import REPO_ROOT  # noqa: C3
            pat_candidates.append(REPO_ROOT / "rudy-logs" / "github-classic-pat.txt")
            pat_candidates.append(REPO_ROOT.parent / "rudy-logs" / "github-classic-pat.txt")
        except ImportError:
            pass
        home = Path.home()
        pat_candidates.extend([
            home / "Downloads" / "github-recovery-codes.txt",
            home / "Desktop" / "rudy-logs" / "github-classic-pat.txt",
            home / "Desktop" / "rudy-workhorse" / "rudy-logs" / "github-classic-pat.txt",
        ])
        for p in pat_candidates:
            try:
                if p.exists():
                    pat = p.read_text(encoding="utf-8").strip()
                    if pat:
                        break
            except Exception:
                continue

    # If MCP process is running, that's a PASS (with optional PAT detail)
    if mcp_process_running:
        if pat:
            # Bonus: validate PAT too
            try:
                req = urllib.request.Request(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"token {pat}",
                        "User-Agent": "rudy-lucius-gate/1.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        return GateCheck(
                            name="mcp_github",
                            passed=True,
                            detail="MCP process running + PAT validated (200)",
                        )
            except Exception:
                pass
            return GateCheck(
                name="mcp_github",
                passed=True,
                detail="MCP process running (PAT found but validation skipped)",
            )
        return GateCheck(
            name="mcp_github",
            passed=True,
            detail="GitHub MCP node process (server-github) detected",
        )

    # MCP not running -- try PAT validation as fallback
    if pat:
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"token {pat}",
                    "User-Agent": "rudy-lucius-gate/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return GateCheck(
                        name="mcp_github",
                        passed=True,
                        detail="GitHub API auth OK (200) but MCP process not detected",
                    )
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return GateCheck(
                    name="mcp_github",
                    passed=False,
                    detail="MCP not running + PAT rejected (401)",
                )
        except Exception:
            pass

    # Neither MCP process nor valid PAT found
    return GateCheck(
        name="mcp_github",
        passed=None,
        detail="GitHub MCP process not detected and no valid PAT found",
        state=GateCheckState.DEGRADED,
    )


def _check_mcp_gmail() -> GateCheck:
    """gmail: TCP socket probe to smtp.zoho.com:587 (Rudy's SMTP backend)."""
    import socket  # noqa: C3

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex(("smtp.zoho.com", 587))
        sock.close()
        if result == 0:
            return GateCheck(
                name="mcp_gmail",
                passed=True,
                detail="SMTP backend reachable (smtp.zoho.com:587)",
            )
        return GateCheck(
            name="mcp_gmail",
            passed=False,
            detail=f"SMTP connect_ex returned {result}",
        )
    except socket.timeout:
        return GateCheck(
            name="mcp_gmail",
            passed=False,
            detail="SMTP connection timed out (5s)",
        )
    except Exception as e:
        return GateCheck(
            name="mcp_gmail",
            passed=None,
            detail=f"SMTP probe error: {type(e).__name__}",
            state=GateCheckState.DEGRADED,
        )


def _check_mcp_cloud_connector(mcp_name: str, display_name: str) -> GateCheck:
    """Check if a Cowork cloud connector appears in .claude.json history.

    PASS if found in claudeAiMcpEverConnected. DEGRADED if not (the
    connector may work but hasn't been registered yet -- not a FAIL).
    """
    data = _read_claude_json_data()
    connectors = data.get("claudeAiMcpEverConnected", [])

    if display_name in connectors:
        return GateCheck(
            name=f"mcp_{mcp_name}",
            passed=True,
            detail=f"\'{display_name}\' found in .claude.json connector history",
        )
    return GateCheck(
        name=f"mcp_{mcp_name}",
        passed=None,
        detail=f"\'{display_name}\' not in connector history (may still work)",
        state=GateCheckState.DEGRADED,
    )


def _check_mcp_chrome() -> GateCheck:
    """chrome: check cachedChromeExtensionInstalled flag in .claude.json."""
    data = _read_claude_json_data()
    if data.get("cachedChromeExtensionInstalled", False):
        return GateCheck(
            name="mcp_chrome",
            passed=True,
            detail="Chrome extension installed (cachedChromeExtensionInstalled=true)",
        )
    return GateCheck(
        name="mcp_chrome",
        passed=None,
        detail="Chrome extension not confirmed in .claude.json",
        state=GateCheckState.DEGRADED,
    )


def _check_mcp_context7() -> GateCheck:
    """context7: local MCP -- node process with 'context7' in cmdline."""
    try:
        if _process_exists("node", cmdline_contains="context7"):
            return GateCheck(
                name="mcp_context7",
                passed=True,
                detail="context7 node process detected via cmdline",
            )
        return GateCheck(
            name="mcp_context7",
            passed=None,
            detail="context7 node process not found in cmdline",
            state=GateCheckState.DEGRADED,
        )
    except Exception as e:
        return GateCheck(
            name="mcp_context7",
            passed=None,
            detail=f"process check failed: {type(e).__name__}",
            state=GateCheckState.DEGRADED,
        )


# Cloud connector display name mapping
_CLOUD_CONNECTOR_MAP: Dict[str, str] = {
    "google-calendar": "claude.ai Google Calendar",
    "notion": "claude.ai Notion",
    "brave-search": "claude.ai Brave Search",
    "huggingface": "claude.ai Hugging Face",
}


def _check_mcp_connection(mcp_name: str) -> GateCheck:
    """Check if an MCP server is reachable.

    Phase 1C: Real connectivity checks replacing Phase 1A stubs.
    Dispatches to type-specific checkers based on MCP name.

    Check strategies:
        - desktop-commander, windows-mcp, context7: process existence
        - github: HTTP auth with stored PAT
        - gmail: TCP socket to SMTP backend
        - chrome: .claude.json extension flag
        - google-calendar, notion, brave-search, huggingface: .claude.json connector history

    All non-stdlib imports inside function bodies per C3.
    Every check has a 5s internal timeout. Exceptions become DEGRADED.
    """
    try:
        if mcp_name == "desktop-commander":
            return _check_mcp_desktop_commander()
        elif mcp_name == "windows-mcp":
            return _check_mcp_windows_mcp()
        elif mcp_name == "github":
            return _check_mcp_github()
        elif mcp_name == "gmail":
            return _check_mcp_gmail()
        elif mcp_name == "chrome":
            return _check_mcp_chrome()
        elif mcp_name == "context7":
            return _check_mcp_context7()
        elif mcp_name in _CLOUD_CONNECTOR_MAP:
            return _check_mcp_cloud_connector(mcp_name, _CLOUD_CONNECTOR_MAP[mcp_name])
        else:
            return GateCheck(
                name=f"mcp_{mcp_name}",
                passed=None,
                detail=f"no check implemented for \'{mcp_name}\'",
                state=GateCheckState.DEGRADED,
            )
    except Exception as e:
        return GateCheck(
            name=f"mcp_{mcp_name}",
            passed=None,
            detail=f"check dispatch error: {type(e).__name__}: {e}",
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



def _check_branch_verification(expected_branch: Optional[str] = None) -> GateCheck:
    """Verify working copy is on the expected git branch.

    ADR-004 v2.1 — Session 35 patch (LG-S34-005).
    Branch confusion caused hours of dead autonomy in Session 34.

    If expected_branch is None, reads from:
        1. rudy-data/coordination/session-branch.json ({"branch": "..."})
        2. Falls back to PASS with a warning (no expectation set)

    Returns FAIL if on the wrong branch (blocks the session).
    """
    import subprocess  # noqa: C3

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        if result.returncode != 0:
            return GateCheck(
                name="branch_verification",
                passed=None,
                detail=f"git rev-parse failed: {result.stderr.strip()}",
                state=GateCheckState.DEGRADED,
            )
        actual_branch = result.stdout.strip()
    except FileNotFoundError:
        return GateCheck(
            name="branch_verification",
            passed=None,
            detail="git not found in PATH",
            state=GateCheckState.DEGRADED,
        )
    except Exception as e:
        return GateCheck(
            name="branch_verification",
            passed=None,
            detail=f"branch check error: {type(e).__name__}: {e}",
            state=GateCheckState.DEGRADED,
        )

    # Resolve expected branch
    if expected_branch is None:
        try:
            from rudy.paths import RUDY_DATA  # noqa: C3
            session_branch_file = RUDY_DATA / "coordination" / "session-branch.json"
            if session_branch_file.is_file():
                import json as _json
                data = _json.loads(session_branch_file.read_text(encoding="utf-8"))
                expected_branch = data.get("branch")
        except Exception:
            pass

    if expected_branch is None:
        return GateCheck(
            name="branch_verification",
            passed=True,
            detail=f"On branch '{actual_branch}' (no expectation set — WARN)",
        )

    if actual_branch != expected_branch:
        log.error(
            "BRANCH MISMATCH: expected '%s', got '%s' — SESSION BLOCKED",
            expected_branch, actual_branch,
        )
        return GateCheck(
            name="branch_verification",
            passed=False,
            detail=(
                f"BRANCH MISMATCH: expected '{expected_branch}', "
                f"actual '{actual_branch}'. "
                f"Run: git checkout {expected_branch}"
            ),
        )

    return GateCheck(
        name="branch_verification",
        passed=True,
        detail=f"On expected branch '{actual_branch}'",
    )


def session_start_gate(
    session_number: int = 0,
    mcp_tiers_path: Optional[str] = None,
    check_timeout_sec: float = DEFAULT_CHECK_TIMEOUT_SEC,
    task_description: str = "",
    expected_branch: Optional[str] = None,
) -> GateResult:
    """Run all pre-session checks. Called when a new session begins.

    Checks:
        1. Repo root is detectable
        2. Branch verification (LG-S34-005 — blocks on mismatch)
        3. Vault is accessible
        4. MCP connections (per tier)

    If task_description is provided, also runs skills_check() and
    includes recommendations in the GateResult.

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
    # Branch verification (LG-S34-005: Session 35 patch)
    checks.append(run_check(
        fn=lambda: _check_branch_verification(expected_branch),
        name="branch_verification",
        timeout_sec=check_timeout_sec,
        criticality=MCPTier.CRITICAL,
    ))
    checks.append(run_check(
        fn=_check_vault_accessible,
        name="vault_accessible",
        timeout_sec=check_timeout_sec,
        criticality=MCPTier.IMPORTANT,
    ))

    # MCP connectivity checks (per-MCP timeouts from YAML config)
    mcp_timeouts = load_mcp_timeouts(mcp_tiers_path)
    for mcp_name, tier in mcp_tiers.items():
        per_mcp_timeout = mcp_timeouts.get(mcp_name, check_timeout_sec)
        check = run_check(
            fn=lambda _name=mcp_name: _check_mcp_connection(_name),
            name=f"mcp_{mcp_name}",
            timeout_sec=per_mcp_timeout,
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

    # Recommend skills if task context provided (Phase 2, Session 24)
    if task_description:
        try:
            from rudy.agents.lucius_fox import LuciusFox
            lucius = LuciusFox()
            skill_result = lucius._skills_check(task_description)
            if isinstance(skill_result, dict):
                for rec in skill_result.get("recommendations", []):
                    result.recommended_skills.append(rec.get("name", str(rec)))
                if result.recommended_skills:
                    result.recommendations.append(
                        f"Recommended skills for this task: "
                        f"{', '.join(result.recommended_skills)}"
                    )
        except ImportError:
            pass
        except Exception as e:
            log.warning(f"Skills recommendation failed: {e}")

    # Load open findings for session awareness (Phase 2, Session 24)
    try:
        from rudy.agents.lucius_findings import get_open_findings, escalate_stale_findings
        # Escalate stale findings
        escalate_stale_findings(session_number)
        # Load open findings into gate result
        open_f = get_open_findings()
        result.open_findings = open_f
        if open_f:
            critical = sum(1 for f in open_f if f.get("severity") == "CRITICAL")
            high = sum(1 for f in open_f if f.get("severity") == "HIGH")
            if critical:
                result.recommendations.append(
                    f"⚠️ {critical} CRITICAL findings require immediate attention"
                )
            if high:
                result.recommendations.append(
                    f"{high} HIGH findings pending resolution"
                )
    except ImportError:
        pass
    except Exception as e:
        log.warning(f"Findings load failed: {e}")

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
        the push â€” bricking Robin is worse than a branch violation.
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
    evidence: Optional[dict] = None,
) -> GateResult:
    """Run post-session checks before handoff. Called by HandoffWriter.

    Checks:
        1. context_window_pct was provided
        2. Vault is accessible (for writing handoff artifacts)

    If evidence is provided, runs the Lucius Scorer for a nuanced
    compliance score (0-100). Otherwise falls back to binary 100/0.

    Returns:
        GateResult. If the gate itself fails (DEGRADED), the caller
        should log and allow the handoff with compliance_score=0.
        The result's recommendations list may contain the score report.
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

    result = _build_gate_result(
        gate_name="post_session",
        checks=checks,
        mcp_tiers={},
        start_time=gate_start,
        session_number=session_number,
    )

    # Nuanced scoring via Lucius Scorer (Phase 3, Session 24)
    if evidence is not None:
        try:
            from rudy.agents.lucius_scorer import score_session, format_score_report
            score_result = score_session(evidence)
            result.compliance_score = score_result.get("total_score", 0)
            result.score_report = score_result
            result.recommendations.append(
                f"Session score: {score_result['total_score']}/100 "
                f"({score_result['grade']})"
            )
            log.info(f"Session scored: {score_result['summary']}")
        except ImportError:
            log.warning("lucius_scorer not available, using binary scoring")
        except Exception as e:
            log.warning(f"Scorer failed: {e}")

    return result
