"""
Tests for rudy.agents.lucius_gate — Lucius Fox session governance.

ADR-004 v2.1, Phase 1A: Condition C4 (test harness).

Test categories:
    1. Dataclass construction and defaults
    2. Circuit breaker (run_check) — timeout, import error, clean pass
    3. MCP tier loading — YAML present, YAML missing, bad values
    4. Import isolation — lucius_gate imports with zero optional deps
    5. Gate functions — session_start, pre_commit, post_session
    6. Chaos scenario — broken dependency mid-gate
"""

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rudy.agents.lucius_gate import (
    DEFAULT_MCP_TIERS,
    GateCheck,
    GateCheckState,
    GateMetrics,
    GateResult,
    MCPTier,
    PROTECTED_BRANCHES,
    load_mcp_tiers,
    post_session_gate,
    pre_commit_check,
    run_check,
    session_start_gate,
)


# ═══════════════════════════════════════════════════════════════════
# 1. Dataclass Tests
# ═══════════════════════════════════════════════════════════════════


class TestGateCheckState:
    def test_enum_values(self):
        assert GateCheckState.PASS.value == "PASS"
        assert GateCheckState.FAIL.value == "FAIL"
        assert GateCheckState.DEGRADED.value == "DEGRADED"

    def test_enum_members(self):
        assert len(GateCheckState) == 3


class TestMCPTier:
    def test_enum_values(self):
        assert MCPTier.CRITICAL.value == "CRITICAL"
        assert MCPTier.IMPORTANT.value == "IMPORTANT"
        assert MCPTier.OPTIONAL.value == "OPTIONAL"


class TestGateCheck:
    def test_pass_state(self):
        c = GateCheck(name="test", passed=True, detail="ok")
        assert c.state == GateCheckState.PASS
        assert c.passed is True

    def test_fail_state(self):
        c = GateCheck(name="test", passed=False, detail="not ok")
        assert c.state == GateCheckState.FAIL
        assert c.passed is False

    def test_degraded_explicit(self):
        c = GateCheck(name="test", passed=None, detail="err", state=GateCheckState.DEGRADED)
        assert c.state == GateCheckState.DEGRADED
        assert c.passed is None

    def test_degraded_inferred_from_none(self):
        c = GateCheck(name="test", passed=None, detail="unknown")
        assert c.state == GateCheckState.DEGRADED

    def test_default_elapsed(self):
        c = GateCheck(name="test", passed=True)
        assert c.elapsed_sec == 0.0


class TestGateMetrics:
    def test_defaults(self):
        m = GateMetrics(gate_name="test_gate")
        assert m.gate_name == "test_gate"
        assert m.total_elapsed_sec == 0.0
        assert m.check_timings == {}
        assert m.session_number == 0
        assert m.timestamp  # auto-populated

    def test_custom_values(self):
        m = GateMetrics(
            gate_name="session_start",
            total_elapsed_sec=1.5,
            check_timings={"check_a": 0.5, "check_b": 1.0},
            session_number=19,
        )
        assert m.total_elapsed_sec == 1.5
        assert m.check_timings["check_a"] == 0.5
        assert m.session_number == 19


class TestGateResult:
    def test_pass_result(self):
        checks = [GateCheck(name="a", passed=True)]
        r = GateResult(passed=True, degraded=False, checks=checks)
        assert r.passed is True
        assert r.degraded is False
        assert "PASS" in r.summary()

    def test_blocked_result(self):
        checks = [GateCheck(name="a", passed=False)]
        r = GateResult(passed=False, degraded=False, checks=checks)
        assert r.passed is False
        assert "BLOCKED" in r.summary()

    def test_degraded_result(self):
        checks = [
            GateCheck(name="a", passed=True),
            GateCheck(name="b", passed=None, state=GateCheckState.DEGRADED),
        ]
        r = GateResult(passed=True, degraded=True, checks=checks)
        assert "DEGRADED" in r.summary()

    def test_to_dict_serializable(self):
        checks = [GateCheck(name="a", passed=True, elapsed_sec=0.123)]
        metrics = GateMetrics(gate_name="test", total_elapsed_sec=0.123)
        r = GateResult(passed=True, degraded=False, checks=checks, metrics=metrics)
        d = r.to_dict()
        # Must be JSON-serializable
        serialized = json.dumps(d)
        assert serialized
        assert d["passed"] is True
        assert d["checks"][0]["name"] == "a"

    def test_to_dict_no_metrics(self):
        r = GateResult(passed=True, degraded=False)
        d = r.to_dict()
        assert d["metrics"] is None


# ═══════════════════════════════════════════════════════════════════
# 2. Circuit Breaker Tests (run_check)
# ═══════════════════════════════════════════════════════════════════


class TestRunCheck:
    def test_clean_pass(self):
        """Check that returns GateCheck(passed=True) works cleanly."""
        def good_check():
            return GateCheck(name="good", passed=True, detail="all good")

        result = run_check(good_check, name="good", timeout_sec=5)
        assert result.state == GateCheckState.PASS
        assert result.passed is True
        assert result.elapsed_sec > 0

    def test_clean_fail(self):
        """Check that returns GateCheck(passed=False) is a FAIL, not DEGRADED."""
        def bad_check():
            return GateCheck(name="bad", passed=False, detail="condition not met")

        result = run_check(bad_check, name="bad", timeout_sec=5)
        assert result.state == GateCheckState.FAIL
        assert result.passed is False

    def test_exception_becomes_degraded(self):
        """Unhandled exception in check → DEGRADED, never crash."""
        def exploding_check():
            raise RuntimeError("kaboom")

        result = run_check(exploding_check, name="exploding", timeout_sec=5)
        assert result.state == GateCheckState.DEGRADED
        assert result.passed is None
        assert "RuntimeError" in result.detail

    def test_import_error_becomes_degraded(self):
        """ImportError inside check → DEGRADED."""
        def import_check():
            import nonexistent_module_xyz  # noqa
            return GateCheck(name="import", passed=True)

        result = run_check(import_check, name="import", timeout_sec=5)
        assert result.state == GateCheckState.DEGRADED
        assert result.passed is None

    def test_non_gatecheck_return_wrapped(self):
        """If check returns a bool instead of GateCheck, it gets wrapped."""
        def bool_check():
            return True

        result = run_check(bool_check, name="bool", timeout_sec=5)
        assert result.passed is True
        assert result.name == "bool"

    def test_timing_recorded(self):
        """Check that elapsed_sec is populated."""
        def slow_check():
            time.sleep(0.05)
            return GateCheck(name="slow", passed=True)

        result = run_check(slow_check, name="slow", timeout_sec=5)
        assert result.elapsed_sec >= 0.04  # allow small timing variance


# ═══════════════════════════════════════════════════════════════════
# 3. MCP Tier Loading Tests
# ═══════════════════════════════════════════════════════════════════


class TestLoadMCPTiers:
    def test_loads_from_yaml(self, tmp_path):
        """Load tiers from a valid YAML file."""
        yaml_content = """
mcps:
  github: CRITICAL
  brave-search: OPTIONAL
  notion: IMPORTANT
"""
        yaml_file = tmp_path / "tiers.yml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        tiers = load_mcp_tiers(str(yaml_file))
        assert tiers["github"] == MCPTier.CRITICAL
        assert tiers["brave-search"] == MCPTier.OPTIONAL
        assert tiers["notion"] == MCPTier.IMPORTANT

    def test_fallback_when_yaml_missing(self):
        """When YAML file doesn't exist, use defaults."""
        tiers = load_mcp_tiers("/nonexistent/path/tiers.yml")
        assert "github" in tiers
        assert tiers["github"] == MCPTier.CRITICAL
        assert tiers["desktop-commander"] == MCPTier.CRITICAL
        assert tiers["brave-search"] == MCPTier.OPTIONAL

    def test_fallback_when_yaml_import_fails(self, tmp_path):
        """When PyYAML is not installed, fall back to defaults."""
        yaml_file = tmp_path / "tiers.yml"
        yaml_file.write_text("mcps:\n  github: CRITICAL\n", encoding="utf-8")

        with patch.dict("sys.modules", {"yaml": None}):
            # Force reimport to trigger ImportError
            import importlib
            # The function catches ImportError internally
            tiers = load_mcp_tiers(str(yaml_file))
            assert "github" in tiers  # defaults loaded

    def test_bad_tier_value_defaults_to_optional(self, tmp_path):
        """Unknown tier string defaults to OPTIONAL."""
        yaml_content = """
mcps:
  github: SUPER_CRITICAL
"""
        yaml_file = tmp_path / "tiers.yml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        tiers = load_mcp_tiers(str(yaml_file))
        assert tiers["github"] == MCPTier.OPTIONAL

    def test_default_tiers_match_adr(self):
        """Verify built-in defaults match ADR-004 v2.1 Section 2.3."""
        assert DEFAULT_MCP_TIERS["github"] == "CRITICAL"
        assert DEFAULT_MCP_TIERS["desktop-commander"] == "CRITICAL"
        assert DEFAULT_MCP_TIERS["gmail"] == "IMPORTANT"
        assert DEFAULT_MCP_TIERS["google-calendar"] == "IMPORTANT"
        assert DEFAULT_MCP_TIERS["notion"] == "IMPORTANT"
        assert DEFAULT_MCP_TIERS["windows-mcp"] == "IMPORTANT"
        assert DEFAULT_MCP_TIERS["brave-search"] == "OPTIONAL"
        assert DEFAULT_MCP_TIERS["huggingface"] == "OPTIONAL"
        assert DEFAULT_MCP_TIERS["context7"] == "OPTIONAL"
        assert DEFAULT_MCP_TIERS["chrome"] == "OPTIONAL"


# ═══════════════════════════════════════════════════════════════════
# 4. Import Isolation Tests (Condition C3)
# ═══════════════════════════════════════════════════════════════════


class TestImportIsolation:
    def test_module_imports_without_optional_deps(self):
        """lucius_gate.py must import successfully even if optional deps
        (yaml, func_timeout, lucius_registry, lucius_scorer) are unavailable.

        We test this by running a subprocess that blocks those modules
        and attempts to import lucius_gate.

        Note: rudy.paths is NOT blocked because it is required by the
        rudy.agents __init__.py package infrastructure, not by lucius_gate.py
        itself. The AST test (test_no_non_stdlib_top_level_imports) verifies
        that lucius_gate.py has no direct non-stdlib imports.
        """
        test_script = """
import sys
import os

# Add repo root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Block optional deps that lucius_gate.py might try to import.
# rudy.paths is NOT blocked — it is needed by rudy/agents/__init__.py,
# which is package infrastructure outside lucius_gate.py's control.
class BlockingFinder:
    BLOCKED = {'yaml', 'func_timeout', 'lucius_registry', 'lucius_scorer'}
    def find_module(self, name, path=None):
        if name in self.BLOCKED or any(name.startswith(b + '.') for b in self.BLOCKED):
            return self
    def load_module(self, name):
        raise ImportError(f"Blocked for testing: {name}")

sys.meta_path.insert(0, BlockingFinder())

# Now try to import — this must succeed
try:
    from rudy.agents.lucius_gate import (
        GateCheck, GateCheckState, GateMetrics, GateResult,
        MCPTier, run_check, session_start_gate, pre_commit_check, post_session_gate,
    )
    print("IMPORT_OK")
except Exception as e:
    print(f"IMPORT_FAILED: {e}")
    sys.exit(1)
"""
        script_path = Path(__file__).parent / "_test_import_isolation.py"
        try:
            script_path.write_text(test_script, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert "IMPORT_OK" in result.stdout, (
                f"Import failed with optional deps blocked.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        finally:
            if script_path.exists():
                script_path.unlink()

    def test_no_non_stdlib_top_level_imports(self):
        """Verify the source code of lucius_gate.py only imports stdlib at top level."""
        import ast

        gate_path = Path(__file__).parent.parent / "rudy" / "agents" / "lucius_gate.py"
        source = gate_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        ALLOWED_STDLIB = {
            "os", "sys", "json", "time", "logging", "dataclasses", "typing",
            "pathlib", "enum",
        }

        top_level_imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level_imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_level_imports.append(node.module.split(".")[0])

        for mod in top_level_imports:
            assert mod in ALLOWED_STDLIB, (
                f"Non-stdlib top-level import found: '{mod}'. "
                f"Only {ALLOWED_STDLIB} are permitted at module level (Condition C3)."
            )


# ═══════════════════════════════════════════════════════════════════
# 5. Gate Function Tests
# ═══════════════════════════════════════════════════════════════════


class TestSessionStartGate:
    def test_returns_gate_result(self):
        result = session_start_gate(session_number=19)
        assert isinstance(result, GateResult)
        assert isinstance(result.metrics, GateMetrics)
        assert result.metrics.gate_name == "session_start"
        assert result.metrics.session_number == 19

    def test_has_mcp_checks(self):
        result = session_start_gate(session_number=19)
        mcp_checks = [c for c in result.checks if c.name.startswith("mcp_")]
        assert len(mcp_checks) > 0, "session_start_gate should include MCP checks"

    def test_has_structural_checks(self):
        result = session_start_gate(session_number=19)
        names = [c.name for c in result.checks]
        assert "repo_root" in names
        assert "vault_accessible" in names


class TestPreCommitCheck:
    def test_safe_branch_passes(self):
        result = pre_commit_check(branch="alfred/lucius-gate-core")
        assert result.passed is True
        branch_check = next(c for c in result.checks if c.name == "protected_branch")
        assert branch_check.state == GateCheckState.PASS

    def test_protected_branch_blocked(self):
        result = pre_commit_check(branch="main")
        assert result.passed is False
        branch_check = next(c for c in result.checks if c.name == "protected_branch")
        assert branch_check.state == GateCheckState.FAIL

    def test_master_also_blocked(self):
        result = pre_commit_check(branch="master")
        assert result.passed is False


class TestPostSessionGate:
    def test_with_context_window(self):
        result = post_session_gate(session_number=19, context_window_pct=45.0)
        cw_check = next(c for c in result.checks if c.name == "context_window_pct")
        assert cw_check.state == GateCheckState.PASS

    def test_missing_context_window_fails(self):
        result = post_session_gate(session_number=19, context_window_pct=None)
        cw_check = next(c for c in result.checks if c.name == "context_window_pct")
        assert cw_check.state == GateCheckState.FAIL

    def test_returns_metrics(self):
        result = post_session_gate(session_number=19, context_window_pct=50.0)
        assert result.metrics.gate_name == "post_session"
        assert result.metrics.session_number == 19
        assert result.metrics.total_elapsed_sec >= 0


# ═══════════════════════════════════════════════════════════════════
# 6. Chaos Scenario — broken dependency mid-gate (Condition C1 + C3)
# ═══════════════════════════════════════════════════════════════════


class TestChaos:
    def test_gate_survives_broken_dependency(self):
        """If a check raises an unexpected exception, the gate returns
        DEGRADED for that check — never crashes."""
        def broken_check():
            raise OSError("disk on fire")

        result = run_check(broken_check, name="broken", timeout_sec=5)
        assert result.state == GateCheckState.DEGRADED
        assert "disk on fire" in result.detail

    def test_gate_result_with_mixed_states(self):
        """Gate with PASS + DEGRADED + FAIL checks computes correctly."""
        checks = [
            GateCheck(name="a", passed=True),
            GateCheck(name="b", passed=None, state=GateCheckState.DEGRADED),
            GateCheck(name="c", passed=False),
        ]
        # Since "c" is a non-MCP FAIL, it blocks
        r = GateResult(passed=False, degraded=True, checks=checks)
        assert r.passed is False
        assert r.degraded is True
        summary = r.summary()
        assert "1" in summary  # 1 passed
        assert "BLOCKED" in summary
