"""
Phase 1C Chaos Tests for Lucius Gate.

ADR-004 v2.1 Phase 1C: Verify gate resilience under adverse conditions.

Test categories:
    1. YAML corruption — malformed, missing keys, invalid tiers
    2. Timeout simulation — slow checks that exceed deadlines
    3. Import failures — lucius_gate broken or missing
    4. Circuit breaker stress — rapid repeated failures, recovery
    5. Concurrent gate invocations — race conditions
    6. .claude.json corruption — invalid JSON, missing keys
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rudy.agents.lucius_gate import (
    GateCheck,
    GateCheckState,
    GateMetrics,
    GateResult,
    MCPTier,
    DEFAULT_MCP_TIERS,
    DEFAULT_CHECK_TIMEOUT_SEC,
    load_mcp_tiers,
    load_mcp_timeouts,
    run_check,
    session_start_gate,
    pre_commit_check,
    post_session_gate,
    _check_mcp_connection,
    _read_claude_json_data,
    _claude_json_cache,
)


# =====================================================================
# Helpers
# =====================================================================

def _clear_claude_json_cache():
    """Clear the module-level .claude.json cache between tests."""
    _claude_json_cache.clear()


# =====================================================================
# 1. YAML Corruption Tests
# =====================================================================

class TestYAMLCorruption:
    """Verify gate handles corrupt/missing/malformed YAML gracefully."""

    def test_missing_yaml_uses_defaults(self, tmp_path):
        """Missing YAML file should fall back to DEFAULT_MCP_TIERS."""
        fake_path = str(tmp_path / "nonexistent.yml")
        tiers = load_mcp_tiers(config_path=fake_path)
        # Should get defaults
        assert "github" in tiers
        assert tiers["github"] == MCPTier.CRITICAL

    def test_empty_yaml_uses_defaults(self, tmp_path):
        """Empty YAML file should fall back to defaults."""
        empty_yaml = tmp_path / "empty.yml"
        empty_yaml.write_text("")
        tiers = load_mcp_tiers(config_path=str(empty_yaml))
        assert "github" in tiers

    def test_malformed_yaml_uses_defaults(self, tmp_path):
        """Invalid YAML syntax should fall back to defaults."""
        bad_yaml = tmp_path / "bad.yml"
        bad_yaml.write_text("{{{{not: valid: yaml: [[[")
        tiers = load_mcp_tiers(config_path=str(bad_yaml))
        assert "github" in tiers

    def test_yaml_missing_mcps_key(self, tmp_path):
        """YAML with no 'mcps' key should use defaults."""
        yaml_file = tmp_path / "no_mcps.yml"
        yaml_file.write_text("timeouts:\n  github: 10\n")
        tiers = load_mcp_tiers(config_path=str(yaml_file))
        assert "github" in tiers

    def test_yaml_invalid_tier_value(self, tmp_path):
        """Unknown tier value should default to OPTIONAL."""
        yaml_file = tmp_path / "bad_tier.yml"
        yaml_file.write_text("mcps:\n  github: SUPERDUPER\n")
        tiers = load_mcp_tiers(config_path=str(yaml_file))
        assert tiers["github"] == MCPTier.OPTIONAL

    def test_yaml_none_tier_value(self, tmp_path):
        """None tier value should default to OPTIONAL."""
        yaml_file = tmp_path / "none_tier.yml"
        yaml_file.write_text("mcps:\n  github: null\n")
        tiers = load_mcp_tiers(config_path=str(yaml_file))
        assert tiers["github"] == MCPTier.OPTIONAL

    def test_yaml_numeric_mcp_name(self, tmp_path):
        """Numeric MCP name should be converted to string."""
        yaml_file = tmp_path / "numeric.yml"
        yaml_file.write_text("mcps:\n  12345: CRITICAL\n")
        tiers = load_mcp_tiers(config_path=str(yaml_file))
        assert "12345" in tiers

    def test_timeout_yaml_corrupt(self, tmp_path):
        """Corrupt timeout values should be silently ignored."""
        yaml_file = tmp_path / "bad_timeout.yml"
        yaml_file.write_text("mcps:\n  github: CRITICAL\ntimeouts:\n  github: not_a_number\n  gmail: 5\n")
        timeouts = load_mcp_timeouts(config_path=str(yaml_file))
        assert "github" not in timeouts  # invalid value skipped
        assert timeouts.get("gmail") == 5.0

    def test_timeout_yaml_missing(self, tmp_path):
        """Missing timeout YAML returns empty dict."""
        fake_path = str(tmp_path / "nonexistent.yml")
        timeouts = load_mcp_timeouts(config_path=fake_path)
        assert timeouts == {}

    def test_timeout_yaml_empty_section(self, tmp_path):
        """Empty timeouts section returns empty dict."""
        yaml_file = tmp_path / "empty_timeouts.yml"
        yaml_file.write_text("mcps:\n  github: CRITICAL\ntimeouts: {}\n")
        timeouts = load_mcp_timeouts(config_path=str(yaml_file))
        assert timeouts == {}


# =====================================================================
# 2. Timeout Simulation
# =====================================================================

class TestTimeoutBehavior:
    """Verify that slow/hanging checks are properly timed out."""

    def test_slow_check_returns_degraded(self):
        """A check that exceeds its timeout should return DEGRADED.

        If func_timeout is not installed, the check runs unprotected and
        completes normally (PASS). Both outcomes are acceptable -- the
        circuit breaker logs a warning about missing timeout protection.
        """
        # Check if func_timeout is available
        try:
            import func_timeout  # noqa: F401
            has_func_timeout = True
        except ImportError:
            has_func_timeout = False

        def slow_check():
            time.sleep(2)  # Shorter sleep for faster tests
            return GateCheck(name="slow", passed=True, detail="completed")

        result = run_check(
            fn=slow_check,
            name="slow_test",
            timeout_sec=0.5,  # 500ms timeout
            criticality=MCPTier.OPTIONAL,
        )

        if has_func_timeout:
            # With timeout enforcement: check should be killed
            assert result.state == GateCheckState.DEGRADED
            assert result.elapsed_sec < 2.0
        else:
            # Without timeout enforcement: check runs to completion
            # This is the documented degraded-mode behavior
            assert result.state == GateCheckState.PASS
            assert result.elapsed_sec >= 1.5

    def test_fast_check_passes(self):
        """A check that completes quickly should PASS."""
        def fast_check():
            return GateCheck(name="fast", passed=True, detail="quick")

        result = run_check(
            fn=fast_check,
            name="fast_test",
            timeout_sec=5.0,
            criticality=MCPTier.OPTIONAL,
        )
        assert result.state == GateCheckState.PASS
        assert result.elapsed_sec < 1.0

    def test_exception_in_check_returns_degraded(self):
        """A check that raises should return DEGRADED, not crash."""
        def boom():
            raise RuntimeError("kaboom")

        result = run_check(
            fn=boom,
            name="boom_test",
            timeout_sec=5.0,
            criticality=MCPTier.CRITICAL,
        )
        assert result.state == GateCheckState.DEGRADED
        assert "kaboom" in result.detail

    def test_check_returning_non_gatecheck(self):
        """A check that returns a non-GateCheck value should be wrapped."""
        def weird_check():
            return True

        result = run_check(
            fn=weird_check,
            name="weird_test",
            timeout_sec=5.0,
            criticality=MCPTier.OPTIONAL,
        )
        assert result.passed is True


# =====================================================================
# 3. Import Failure Tests
# =====================================================================

class TestImportFailures:
    """Verify gate consumers degrade when lucius_gate can't be imported."""

    def test_session_gate_import_failure(self):
        """session_gate.py should return None if lucius_gate is broken."""
        with patch.dict("sys.modules", {"rudy.agents.lucius_gate": None}):
            from rudy.workflows.session_gate import run_session_start_gate
            result = run_session_start_gate(session_number=99)
            assert result is None

    def test_session_gate_crash_returns_none(self):
        """session_gate.py should return None if gate crashes."""
        with patch("rudy.agents.lucius_gate.session_start_gate",
                    side_effect=RuntimeError("total failure")):
            from rudy.workflows.session_gate import run_session_start_gate
            result = run_session_start_gate(session_number=99)
            assert result is None


# =====================================================================
# 4. Circuit Breaker Stress Tests
# =====================================================================

class TestCircuitBreakerStress:
    """Rapid repeated failures should not crash or accumulate state."""

    def test_rapid_failures_stay_degraded(self):
        """100 rapid failures should all return DEGRADED cleanly."""
        call_count = 0

        def failing_check():
            nonlocal call_count
            call_count += 1
            raise ConnectionError(f"fail #{call_count}")

        results = []
        for i in range(100):
            r = run_check(
                fn=failing_check,
                name=f"stress_{i}",
                timeout_sec=1.0,
                criticality=MCPTier.OPTIONAL,
            )
            results.append(r)

        assert all(r.state == GateCheckState.DEGRADED for r in results)
        assert call_count == 100
        # Total time should be minimal (no sleeping or backoff)
        total_time = sum(r.elapsed_sec for r in results)
        assert total_time < 5.0  # 100 instant failures << 5s

    def test_alternating_pass_fail(self):
        """Alternating pass/fail should not corrupt state."""
        counter = 0

        def toggle_check():
            nonlocal counter
            counter += 1
            if counter % 2 == 0:
                raise RuntimeError("even = fail")
            return GateCheck(name="toggle", passed=True, detail="odd = pass")

        results = []
        for i in range(50):
            r = run_check(
                fn=toggle_check,
                name=f"toggle_{i}",
                timeout_sec=1.0,
                criticality=MCPTier.OPTIONAL,
            )
            results.append(r)

        passes = sum(1 for r in results if r.state == GateCheckState.PASS)
        degraded = sum(1 for r in results if r.state == GateCheckState.DEGRADED)
        assert passes == 25
        assert degraded == 25

    def test_multiple_full_gate_passes(self):
        """Running the full gate 5 times rapidly should not leak state."""
        with patch("rudy.agents.lucius_gate._check_mcp_connection") as mock_mcp, \
             patch("rudy.agents.lucius_gate._check_repo_root") as mock_repo, \
             patch("rudy.agents.lucius_gate._check_vault_accessible") as mock_vault:

            mock_repo.return_value = GateCheck(name="repo_root", passed=True, detail="ok")
            mock_vault.return_value = GateCheck(name="vault_accessible", passed=True, detail="ok")
            mock_mcp.return_value = GateCheck(name="mcp_test", passed=True, detail="ok")

            results = []
            for i in range(5):
                r = session_start_gate(session_number=i)
                results.append(r)

            assert all(r.passed for r in results)
            assert len(results) == 5


# =====================================================================
# 5. .claude.json Corruption
# =====================================================================

class TestClaudeJsonCorruption:
    """Verify MCP checks handle corrupt .claude.json gracefully."""

    def setup_method(self):
        _clear_claude_json_cache()

    def test_missing_claude_json(self, tmp_path):
        """Missing .claude.json should return empty data."""
        with patch("pathlib.Path.home", return_value=tmp_path):
            _clear_claude_json_cache()
            data = _read_claude_json_data()
            assert data == {}

    def test_corrupt_claude_json(self, tmp_path):
        """Invalid JSON in .claude.json should return empty data."""
        (tmp_path / ".claude.json").write_text("{{{invalid json")
        with patch("pathlib.Path.home", return_value=tmp_path):
            _clear_claude_json_cache()
            data = _read_claude_json_data()
            assert data == {}

    def test_claude_json_missing_connectors(self, tmp_path):
        """Missing claudeAiMcpEverConnected key should yield empty list."""
        (tmp_path / ".claude.json").write_text('{"numStartups": 1}')
        with patch("pathlib.Path.home", return_value=tmp_path):
            _clear_claude_json_cache()
            data = _read_claude_json_data()
            assert data.get("claudeAiMcpEverConnected", []) == []

    def test_claude_json_cache_persists(self, tmp_path):
        """Second call should use cached data, not re-read file."""
        (tmp_path / ".claude.json").write_text('{"claudeAiMcpEverConnected": ["test"]}')
        with patch("pathlib.Path.home", return_value=tmp_path):
            _clear_claude_json_cache()
            data1 = _read_claude_json_data()
            # Delete the file
            (tmp_path / ".claude.json").unlink()
            # Should still return cached data
            data2 = _read_claude_json_data()
            assert data1 == data2
            assert data2.get("claudeAiMcpEverConnected") == ["test"]

    def test_unknown_mcp_returns_degraded(self):
        """Unknown MCP name should return DEGRADED, not crash."""
        result = _check_mcp_connection("nonexistent-mcp-xyz")
        assert result.state == GateCheckState.DEGRADED
        assert "no check implemented" in result.detail


# =====================================================================
# 6. Gate Result Assembly Edge Cases
# =====================================================================

class TestGateResultEdgeCases:
    """Edge cases in _build_gate_result logic."""

    def test_empty_checks_passes(self):
        """Gate with no checks should pass (vacuous truth)."""
        with patch("rudy.agents.lucius_gate._check_repo_root") as mock_repo, \
             patch("rudy.agents.lucius_gate._check_vault_accessible") as mock_vault, \
             patch("rudy.agents.lucius_gate.load_mcp_tiers", return_value={}), \
             patch("rudy.agents.lucius_gate.load_mcp_timeouts", return_value={}):

            mock_repo.return_value = GateCheck(name="repo_root", passed=True, detail="ok")
            mock_vault.return_value = GateCheck(name="vault_accessible", passed=True, detail="ok")
            result = session_start_gate(session_number=0)
            assert result.passed is True

    def test_all_optional_degraded_still_passes(self):
        """All OPTIONAL MCPs degraded should not block the gate."""
        with patch("rudy.agents.lucius_gate._check_repo_root") as mock_repo, \
             patch("rudy.agents.lucius_gate._check_vault_accessible") as mock_vault, \
             patch("rudy.agents.lucius_gate._check_mcp_connection") as mock_mcp, \
             patch("rudy.agents.lucius_gate.load_mcp_tiers",
                   return_value={"test-mcp": MCPTier.OPTIONAL}), \
             patch("rudy.agents.lucius_gate.load_mcp_timeouts", return_value={}):

            mock_repo.return_value = GateCheck(name="repo_root", passed=True, detail="ok")
            mock_vault.return_value = GateCheck(name="vault_accessible", passed=True, detail="ok")
            mock_mcp.return_value = GateCheck(
                name="mcp_test-mcp", passed=None, detail="degraded",
                state=GateCheckState.DEGRADED
            )

            result = session_start_gate(session_number=0)
            assert result.passed is True
            assert result.degraded is True

    def test_critical_degraded_blocks(self):
        """A CRITICAL MCP degraded should block the gate."""
        with patch("rudy.agents.lucius_gate._check_repo_root") as mock_repo, \
             patch("rudy.agents.lucius_gate._check_vault_accessible") as mock_vault, \
             patch("rudy.agents.lucius_gate._check_mcp_connection") as mock_mcp, \
             patch("rudy.agents.lucius_gate.load_mcp_tiers",
                   return_value={"critical-mcp": MCPTier.CRITICAL}), \
             patch("rudy.agents.lucius_gate.load_mcp_timeouts", return_value={}):

            mock_repo.return_value = GateCheck(name="repo_root", passed=True, detail="ok")
            mock_vault.return_value = GateCheck(name="vault_accessible", passed=True, detail="ok")
            mock_mcp.return_value = GateCheck(
                name="mcp_critical-mcp", passed=None, detail="degraded",
                state=GateCheckState.DEGRADED
            )

            result = session_start_gate(session_number=0)
            assert result.passed is False

    def test_pre_commit_protected_branch_blocked(self):
        """Protected branches must be blocked."""
        for branch in ["main", "master"]:
            result = pre_commit_check(branch)
            assert result.passed is False

    def test_pre_commit_feature_branch_allowed(self):
        """Feature branches must be allowed."""
        result = pre_commit_check("alfred/lucius-gate-chaos")
        assert result.passed is True

    def test_post_session_gate_no_context_fails(self):
        """Missing context_window_pct should cause check to fail."""
        result = post_session_gate(session_number=1, context_window_pct=None)
        assert result.passed is False

    def test_post_session_gate_with_context_passes(self):
        """Providing context_window_pct should pass (vault check may vary)."""
        with patch("rudy.agents.lucius_gate._check_vault_accessible") as mock_vault:
            mock_vault.return_value = GateCheck(
                name="vault_accessible", passed=True, detail="ok"
            )
            result = post_session_gate(session_number=1, context_window_pct=50.0)
            assert result.passed is True
