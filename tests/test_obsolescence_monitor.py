"""
Comprehensive tests for rudy.obsolescence_monitor module.

Tests cover:
- Package auditing (check_outdated, check_specific, get_installed_version)
- Module health checking (import verification)
- Landscape scanning (tool discovery and comparison)
- Recommendation generation
- Usage tracking and reporting
- Edge cases (no outdated packages, import failures, empty results)
"""

import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import json
from datetime import datetime, timedelta
import sys

import rudy.obsolescence_monitor as mod


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Monkeypatch DATA_DIR to temporary directory."""
    temp_dir = tmp_path / "obsolescence"
    temp_dir.mkdir(exist_ok=True)
    with patch.object(mod, "DATA_DIR", temp_dir):
        yield temp_dir


@pytest.fixture
def mock_subprocess_outdated():
    """Mock successful pip list --outdated response."""
    outdated_json = [
        {
            "name": "django",
            "version": "3.2.0",
            "latest_version": "4.0.0",
            "latest_filetype": "wheel",
        },
        {
            "name": "pytest",
            "version": "6.2.4",
            "latest_version": "7.0.0",
            "latest_filetype": "wheel",
        },
        {
            "name": "chromadb",
            "version": "0.3.21",
            "latest_version": "0.4.0",
            "latest_filetype": "wheel",
        },
    ]
    with patch("rudy.obsolescence_monitor._run") as mock_run:
        mock_run.return_value = (json.dumps(outdated_json), "", 0)
        yield mock_run


@pytest.fixture
def mock_subprocess_no_outdated():
    """Mock pip list --outdated with no outdated packages."""
    with patch("rudy.obsolescence_monitor._run") as mock_run:
        mock_run.return_value = ("[]", "", 0)
        yield mock_run


@pytest.fixture
def mock_subprocess_pip_show():
    """Mock successful pip show response."""
    pip_show_output = """Name: pytest
Version: 7.1.2
Summary: pytest: simple powerful testing with Python
"""
    with patch("rudy.obsolescence_monitor._run") as mock_run:
        mock_run.return_value = (pip_show_output, "", 0)
        yield mock_run


@pytest.fixture
def mock_subprocess_pip_show_not_found():
    """Mock pip show when package not found."""
    with patch("rudy.obsolescence_monitor._run") as mock_run:
        mock_run.return_value = ("", "WARNING: Package not found", 1)
        yield mock_run


# ── PackageAuditor Tests ────────────────────────────────────────────


class TestPackageAuditor:
    """Tests for PackageAuditor class."""

    def test_check_outdated_success(self, mock_subprocess_outdated):
        """Test successful check for outdated packages."""
        auditor = mod.PackageAuditor()
        result = auditor.check_outdated()

        assert len(result) == 3
        assert result[0]["name"] == "django"
        assert result[0]["version"] == "3.2.0"
        assert result[0]["latest_version"] == "4.0.0"

    def test_check_outdated_empty(self, mock_subprocess_no_outdated):
        """Test check_outdated when no outdated packages exist."""
        auditor = mod.PackageAuditor()
        result = auditor.check_outdated()
        assert result == []

    def test_check_outdated_subprocess_error(self):
        """Test check_outdated when subprocess fails."""
        with patch("rudy.obsolescence_monitor._run") as mock_run:
            mock_run.return_value = ("", "Command failed", 1)
            auditor = mod.PackageAuditor()
            result = auditor.check_outdated()
            assert result == []

    def test_check_outdated_json_decode_error(self):
        """Test check_outdated with invalid JSON output."""
        with patch("rudy.obsolescence_monitor._run") as mock_run:
            mock_run.return_value = ("invalid json", "", 0)
            auditor = mod.PackageAuditor()
            result = auditor.check_outdated()
            assert result == []

    def test_check_specific_found(self, mock_subprocess_outdated):
        """Test check_specific finds specified packages."""
        auditor = mod.PackageAuditor()
        result = auditor.check_specific(["django", "pytest"])

        assert len(result) == 2
        names = {p["name"] for p in result}
        assert names == {"django", "pytest"}

    def test_check_specific_case_insensitive(self, mock_subprocess_outdated):
        """Test check_specific is case-insensitive."""
        auditor = mod.PackageAuditor()
        result = auditor.check_specific(["DJANGO", "PyTest"])

        assert len(result) == 2
        names = {p["name"] for p in result}
        assert names == {"django", "pytest"}

    def test_check_specific_not_found(self, mock_subprocess_outdated):
        """Test check_specific when packages not in outdated list."""
        auditor = mod.PackageAuditor()
        result = auditor.check_specific(["nonexistent"])
        assert result == []

    def test_check_specific_empty_list(self, mock_subprocess_outdated):
        """Test check_specific with empty package list."""
        auditor = mod.PackageAuditor()
        result = auditor.check_specific([])
        assert result == []

    def test_get_installed_version_success(self, mock_subprocess_pip_show):
        """Test successful version retrieval."""
        auditor = mod.PackageAuditor()
        version = auditor.get_installed_version("pytest")
        assert version == "7.1.2"

    def test_get_installed_version_not_found(self, mock_subprocess_pip_show_not_found):
        """Test get_installed_version when package not found."""
        auditor = mod.PackageAuditor()
        version = auditor.get_installed_version("nonexistent")
        assert version is None

    def test_get_installed_version_no_version_line(self):
        """Test get_installed_version when Version line missing."""
        with patch("rudy.obsolescence_monitor._run") as mock_run:
            mock_run.return_value = ("Name: pytest\nSummary: test", "", 0)
            auditor = mod.PackageAuditor()
            version = auditor.get_installed_version("pytest")
            assert version is None


# ── ModuleHealthChecker Tests ───────────────────────────────────────


class TestModuleHealthChecker:
    """Tests for ModuleHealthChecker class."""

    def test_check_all_success(self):
        """Test successful module health check."""
        checker = mod.ModuleHealthChecker()

        with patch("importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_module.__file__ = "/path/to/module.py"
            mock_import.return_value = mock_module

            result = checker.check_all()

            assert "timestamp" in result
            assert "modules" in result
            assert "summary" in result
            assert result["summary"]["total"] == len(mod.RUDY_MODULES)
            assert result["summary"]["ok"] == len(mod.RUDY_MODULES)
            assert result["summary"]["health_pct"] == 100.0

    def test_check_all_import_error(self):
        """Test module health check with ImportError."""
        checker = mod.ModuleHealthChecker()

        with patch("importlib.import_module") as mock_import:
            mock_import.side_effect = ImportError("Module not found")

            result = checker.check_all()

            assert result["summary"]["ok"] == 0
            assert result["summary"]["health_pct"] == 0.0
            # Check first module has import_error status
            first_mod = list(result["modules"].values())[0]
            assert first_mod["status"] == "import_error"
            assert "Module not found" in first_mod["error"]

    def test_check_all_generic_error(self):
        """Test module health check with generic Exception."""
        checker = mod.ModuleHealthChecker()

        with patch("importlib.import_module") as mock_import:
            mock_import.side_effect = RuntimeError("Initialization failed")

            result = checker.check_all()

            assert result["summary"]["ok"] == 0
            first_mod = list(result["modules"].values())[0]
            assert first_mod["status"] == "error"

    def test_check_all_mixed_success_failure(self):
        """Test module health check with mixed results."""
        checker = mod.ModuleHealthChecker()

        def import_side_effect(mod_name):
            if "presence" in mod_name:
                raise ImportError("Missing dependency")
            mock = MagicMock()
            mock.__file__ = f"/path/{mod_name}.py"
            return mock

        with patch("importlib.import_module", side_effect=import_side_effect):
            result = checker.check_all()

            ok_count = result["summary"]["ok"]
            total = result["summary"]["total"]
            assert 0 < ok_count < total
            assert result["summary"]["health_pct"] > 0
            assert result["summary"]["health_pct"] < 100.0

    def test_check_all_desktop_path_added(self):
        """Test that Desktop path is added to sys.path if needed."""
        original_path = sys.path.copy()
        try:
            # Remove Desktop from path if present
            sys.path = [p for p in sys.path if "Desktop" not in p]

            checker = mod.ModuleHealthChecker()
            with patch("importlib.import_module"):
                checker.check_all()

            # Desktop should be added
            assert any("Desktop" in p for p in sys.path)
        finally:
            sys.path = original_path

    def test_check_all_error_truncation(self):
        """Test that error messages are truncated to 200 chars."""
        checker = mod.ModuleHealthChecker()

        long_error = "x" * 300

        with patch("importlib.import_module") as mock_import:
            mock_import.side_effect = RuntimeError(long_error)

            result = checker.check_all()
            first_mod = list(result["modules"].values())[0]
            assert len(first_mod["error"]) <= 200


# ── LandscapeScanner Tests ──────────────────────────────────────────


class TestLandscapeScanner:
    """Tests for LandscapeScanner class."""

    def test_scan_basic(self):
        """Test basic landscape scan."""
        scanner = mod.LandscapeScanner()

        def pip_show_side_effect(cmd):
            if "pocket-tts" in cmd:
                return "Version: 0.3.0\n", "", 0
            elif "sadtalker" in cmd:
                return "Version: 1.0.0\n", "", 0
            else:
                return "", "not found", 1

        with patch("rudy.obsolescence_monitor._run", side_effect=pip_show_side_effect):
            result = scanner.scan()

            assert "timestamp" in result
            assert "domains" in result
            assert len(result["domains"]) > 0

            # Check structure
            voice_cloning = result["domains"].get("voice_cloning", {})
            assert "installed" in voice_cloning
            assert "missing" in voice_cloning
            assert "current_tools" in voice_cloning
            assert "best_of_breed" in voice_cloning

    def test_scan_all_installed(self):
        """Test scan when all tools are installed."""
        scanner = mod.LandscapeScanner()

        def pip_show_all_found(cmd):
            return "Version: 1.0.0\n", "", 0

        with patch("rudy.obsolescence_monitor._run", side_effect=pip_show_all_found):
            result = scanner.scan()

            for domain_info in result["domains"].values():
                assert len(domain_info["installed"]) > 0
                assert domain_info["missing"] == []

    def test_scan_none_installed(self):
        """Test scan when no tools are installed."""
        scanner = mod.LandscapeScanner()

        with patch("rudy.obsolescence_monitor._run") as mock_run:
            mock_run.return_value = ("", "not found", 1)

            result = scanner.scan()

            for domain_info in result["domains"].values():
                assert domain_info["installed"] == []
                assert len(domain_info["missing"]) > 0

    def test_generate_recommendations_no_tools(self):
        """Test recommendations when domain has no installed tools."""
        scanner = mod.LandscapeScanner()

        scan_result = {
            "domains": {
                "voice_cloning": {
                    "installed": [],
                    "missing": ["pocket-tts", "bark"],
                    "current_tools": ["pocket-tts", "bark"],
                    "watch_list": ["fish-speech"],
                }
            }
        }

        recs = scanner.generate_recommendations(scan_result)

        high_priority = [r for r in recs if r["priority"] == "high"]
        assert len(high_priority) > 0
        assert any("voice_cloning" in r["domain"] for r in high_priority)

    def test_generate_recommendations_watch_list(self):
        """Test recommendations include watch list items."""
        scanner = mod.LandscapeScanner()

        scan_result = {
            "domains": {
                "ocr": {
                    "installed": [{"package": "easyocr", "version": "1.6.0"}],
                    "missing": [],
                    "current_tools": ["easyocr"],
                    "watch_list": ["surya-ocr", "doctr"],
                }
            }
        }

        recs = scanner.generate_recommendations(scan_result)

        evaluate_recs = [r for r in recs if r["action"] == "evaluate"]
        assert len(evaluate_recs) >= 2
        assert any("surya-ocr" in r["detail"] for r in evaluate_recs)

    def test_generate_recommendations_empty_domains(self):
        """Test recommendations with empty domains."""
        scanner = mod.LandscapeScanner()

        scan_result = {"domains": {}}

        recs = scanner.generate_recommendations(scan_result)
        assert recs == []

    def test_generate_recommendations_no_current_tools(self):
        """Test recommendations when domain has no current tools."""
        scanner = mod.LandscapeScanner()

        scan_result = {
            "domains": {
                "image_generation": {
                    "installed": [],
                    "missing": [],
                    "current_tools": [],  # No current tools
                    "watch_list": ["flux"],
                }
            }
        }

        recs = scanner.generate_recommendations(scan_result)

        # Should only have watch list recommendations
        high_priority = [r for r in recs if r["priority"] == "high"]
        assert len(high_priority) == 0


# ── UsageTracker Tests ──────────────────────────────────────────────


class TestUsageTracker:
    """Tests for UsageTracker class."""

    def test_record_use_new_module(self, tmp_data_dir):
        """Test recording usage for a new module."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()
            tracker.record_use("rudy.presence")

            assert "rudy.presence" in tracker.stats["modules"]
            assert tracker.stats["modules"]["rudy.presence"]["count"] == 1
            assert tracker.stats["modules"]["rudy.presence"]["last_used"] is not None

    def test_record_use_increment_count(self, tmp_data_dir):
        """Test that use count increments."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()
            tracker.record_use("rudy.presence")
            tracker.record_use("rudy.presence")

            assert tracker.stats["modules"]["rudy.presence"]["count"] == 2

    def test_record_use_with_function(self, tmp_data_dir):
        """Test recording function-level usage."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()
            tracker.record_use("rudy.presence", "check_location")

            funcs = tracker.stats["modules"]["rudy.presence"]["functions"]
            assert "check_location" in funcs
            assert funcs["check_location"] == 1

    def test_record_use_function_increment(self, tmp_data_dir):
        """Test that function counts increment."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()
            tracker.record_use("rudy.presence", "check_location")
            tracker.record_use("rudy.presence", "check_location")

            funcs = tracker.stats["modules"]["rudy.presence"]["functions"]
            assert funcs["check_location"] == 2

    def test_record_use_multiple_functions(self, tmp_data_dir):
        """Test tracking multiple functions in same module."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()
            tracker.record_use("rudy.presence", "check_location")
            tracker.record_use("rudy.presence", "update_status")

            funcs = tracker.stats["modules"]["rudy.presence"]["functions"]
            assert len(funcs) == 2

    def test_get_unused_recent_use(self, tmp_data_dir):
        """Test get_unused excludes recently used modules."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()
            tracker.record_use("rudy.presence")

            # Recently used, should not be in unused
            unused = tracker.get_unused(days_threshold=30)
            assert "rudy.presence" not in unused

    def test_get_unused_old_use(self, tmp_data_dir):
        """Test get_unused includes modules not used recently."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()

            # Manually set last_used to old date
            old_date = (datetime.now() - timedelta(days=40)).isoformat()
            tracker.stats["modules"]["rudy.presence"] = {
                "count": 1,
                "functions": {},
                "last_used": old_date,
            }

            unused = tracker.get_unused(days_threshold=30)
            assert "rudy.presence" in unused

    def test_get_unused_never_used(self, tmp_data_dir):
        """Test get_unused includes never-used modules."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()
            # Don't record use for any module

            unused = tracker.get_unused(days_threshold=30)
            # All modules should be unused
            assert len(unused) == len(mod.RUDY_MODULES)

    def test_get_report(self, tmp_data_dir):
        """Test usage report generation."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker = mod.UsageTracker()
            tracker.record_use("rudy.presence")
            tracker.record_use("rudy.voice")

            report = tracker.get_report()

            assert report["total_modules"] == len(mod.RUDY_MODULES)
            assert report["tracked_modules"] == 2
            assert "stats" in report

    def test_usage_file_persistence(self, tmp_data_dir):
        """Test that usage stats are persisted to file."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            tracker1 = mod.UsageTracker()
            tracker1.record_use("rudy.presence")

            # Create new tracker instance
            tracker2 = mod.UsageTracker()

            # Should load previous data
            assert "rudy.presence" in tracker2.stats["modules"]


# ── ObsolescenceMonitor Tests ───────────────────────────────────────


class TestObsolescenceMonitor:
    """Tests for main ObsolescenceMonitor class."""

    def test_init(self, tmp_data_dir):
        """Test initialization creates required components."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            assert isinstance(monitor.packages, mod.PackageAuditor)
            assert isinstance(monitor.health, mod.ModuleHealthChecker)
            assert isinstance(monitor.landscape, mod.LandscapeScanner)
            assert isinstance(monitor.usage, mod.UsageTracker)
            assert tmp_data_dir.exists()

    def test_quick_check(self, tmp_data_dir):
        """Test quick check execution."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            with patch.object(monitor.health, "check_all") as mock_health:
                mock_health.return_value = {
                    "summary": {"ok": 10, "total": 10, "health_pct": 100.0}
                }

                result = monitor.quick_check()

                assert "timestamp" in result
                assert "module_health" in result
                assert "python_version" in result
                assert result["module_health"]["health_pct"] == 100.0

    def test_check_packages(self, tmp_data_dir, mock_subprocess_outdated):
        """Test check_packages returns outdated list."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()
            result = monitor.check_packages()

            assert len(result) == 3
            assert result[0]["name"] == "django"

    def test_full_audit_structure(self, tmp_data_dir):
        """Test full audit returns proper structure."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            with patch.object(monitor.health, "check_all") as mock_health, \
                 patch.object(monitor.packages, "check_outdated") as mock_outdated, \
                 patch.object(monitor.landscape, "scan") as mock_scan, \
                 patch("builtins.print"):

                mock_health.return_value = {
                    "summary": {"ok": 10, "total": 10, "health_pct": 100.0},
                    "modules": {}
                }
                mock_outdated.return_value = [
                    {"name": "chromadb", "version": "0.3", "latest_version": "0.4"}
                ]
                mock_scan.return_value = {"domains": {}}

                result = monitor.full_audit()

                assert "timestamp" in result
                assert "type" in result
                assert result["type"] == "full_audit"
                assert "module_health" in result
                assert "outdated_packages" in result
                assert "landscape" in result
                assert "usage" in result
                assert "recommendations" in result
                assert "report_file" in result

    def test_full_audit_report_saved(self, tmp_data_dir):
        """Test that full audit saves report to file."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            with patch.object(monitor.health, "check_all") as mock_health, \
                 patch.object(monitor.packages, "check_outdated") as mock_outdated, \
                 patch.object(monitor.landscape, "scan") as mock_scan, \
                 patch("builtins.print"):

                mock_health.return_value = {
                    "summary": {"ok": 10, "total": 10, "health_pct": 100.0},
                    "modules": {}
                }
                mock_outdated.return_value = []
                mock_scan.return_value = {"domains": {}}

                result = monitor.full_audit()
                report_file = Path(result["report_file"])

                assert report_file.exists()
                assert report_file.suffix == ".json"

    def test_full_audit_identifies_critical_packages(self, tmp_data_dir):
        """Test full audit identifies critical outdated packages."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            with patch.object(monitor.health, "check_all") as mock_health, \
                 patch.object(monitor.packages, "check_outdated") as mock_outdated, \
                 patch.object(monitor.landscape, "scan") as mock_scan, \
                 patch("builtins.print"):

                mock_health.return_value = {
                    "summary": {"ok": 10, "total": 10, "health_pct": 100.0},
                    "modules": {}
                }
                mock_outdated.return_value = [
                    {"name": "chromadb", "version": "0.3", "latest_version": "0.4"},
                    {"name": "playwright", "version": "1.0", "latest_version": "1.5"},
                    {"name": "requests", "version": "2.25", "latest_version": "2.28"},
                ]
                mock_scan.return_value = {"domains": {}}

                result = monitor.full_audit()

                critical = result["outdated_packages"]["critical"]
                assert len(critical) == 2  # chromadb and playwright
                names = {p["name"] for p in critical}
                assert "chromadb" in names
                assert "playwright" in names

    def test_generate_summary(self, tmp_data_dir):
        """Test summary generation."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            report = {
                "module_health": {
                    "summary": {"ok": 15, "total": 20, "health_pct": 75.0}
                },
                "outdated_packages": {
                    "count": 5,
                    "critical": [{"name": "chromadb"}],
                },
                "recommendations": [
                    {
                        "priority": "high",
                        "action": "upgrade",
                        "detail": "Update chromadb",
                    }
                ],
                "unused_modules": ["rudy.offline_ops"],
                "report_file": "/path/to/audit.json",
            }

            summary = monitor.generate_summary(report)

            assert "CAPABILITY AUDIT REPORT" in summary
            assert "Module Health: 15/20" in summary
            assert "Outdated Packages: 5" in summary
            assert "HIGH PRIORITY" in summary
            assert "Dormant Modules" in summary

    def test_file_github_issues_no_github_ops(self, tmp_data_dir):
        """Test file_github_issues when github_ops unavailable."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            with patch("rudy.obsolescence_monitor.importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError("No module named github_ops")

                report = {
                    "recommendations": [
                        {"priority": "high", "action": "upgrade", "detail": "Test"}
                    ]
                }

                result = monitor.file_github_issues(report)
                assert result == []

    def test_file_github_issues_gh_unavailable(self, tmp_data_dir):
        """Test file_github_issues when GitHub CLI unavailable."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            mock_github_ops = MagicMock()
            mock_gh = MagicMock()
            mock_gh.gh_available = False
            mock_github_ops.get_github.return_value = mock_gh

            with patch.dict("sys.modules", {"rudy.integrations.github_ops": mock_github_ops}):
                report = {
                    "recommendations": [
                        {"priority": "high", "action": "upgrade", "detail": "Test"}
                    ]
                }

                result = monitor.file_github_issues(report)
                assert result == []

    def test_execute_quick_mode(self, tmp_data_dir):
        """Test execute with quick mode."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            with patch.object(monitor, "quick_check") as mock_quick:
                mock_quick.return_value = {"timestamp": "2024-01-01"}

                result = monitor.execute(mode="quick")

                assert result == {"timestamp": "2024-01-01"}
                mock_quick.assert_called_once()

    def test_execute_packages_mode(self, tmp_data_dir, mock_subprocess_outdated):
        """Test execute with packages mode."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()
            result = monitor.execute(mode="packages")

            assert "outdated" in result
            assert len(result["outdated"]) == 3

    def test_execute_full_mode_with_issue_filing(self, tmp_data_dir):
        """Test execute full mode with GitHub issue filing."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            mock_report = {
                "timestamp": "2024-01-01",
                "module_health": {"summary": {}},
                "outdated_packages": {"count": 0, "critical": []},
                "landscape": {"domains": {}},
                "usage": {},
                "unused_modules": [],
                "recommendations": [],
                "report_file": str(tmp_data_dir / "audit.json"),
            }

            with patch.object(monitor, "full_audit") as mock_audit, \
                 patch.object(monitor, "generate_summary") as mock_summary, \
                 patch.object(monitor, "file_github_issues") as mock_file_issues, \
                 patch("builtins.print"):

                mock_audit.return_value = mock_report
                mock_summary.return_value = "Summary"
                mock_file_issues.return_value = ["url1", "url2"]

                result = monitor.execute(mode="full", file_issues=True)

                assert "github_issues" in result
                assert len(result["github_issues"]) == 2


# ── Helper Function Tests ───────────────────────────────────────────


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_save_json(self, tmp_path):
        """Test JSON saving."""
        test_file = tmp_path / "test.json"
        test_data = {"key": "value", "timestamp": datetime.now()}

        mod._save_json(test_file, test_data)

        assert test_file.exists()
        with open(test_file) as f:
            loaded = json.load(f)
        assert loaded["key"] == "value"

    def test_save_json_creates_parent_dirs(self, tmp_path):
        """Test that _save_json creates parent directories."""
        test_file = tmp_path / "nested" / "deep" / "test.json"

        mod._save_json(test_file, {"key": "value"})

        assert test_file.exists()

    def test_load_json_existing(self, tmp_path):
        """Test loading existing JSON file."""
        test_file = tmp_path / "test.json"
        test_data = {"key": "value"}

        with open(test_file, "w") as f:
            json.dump(test_data, f)

        loaded = mod._load_json(test_file)
        assert loaded == test_data

    def test_load_json_missing(self, tmp_path):
        """Test loading missing JSON file returns default."""
        test_file = tmp_path / "missing.json"

        result = mod._load_json(test_file, {"default": True})
        assert result == {"default": True}

    def test_load_json_missing_no_default(self, tmp_path):
        """Test loading missing JSON file with no default."""
        test_file = tmp_path / "missing.json"

        result = mod._load_json(test_file)
        assert result == {}

    def test_load_json_corrupt(self, tmp_path):
        """Test loading corrupt JSON file."""
        test_file = tmp_path / "corrupt.json"

        with open(test_file, "w") as f:
            f.write("{invalid json")

        result = mod._load_json(test_file, {"default": True})
        assert result == {"default": True}

    def test_run_success(self):
        """Test _run with successful command."""
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = "output"
            mock_result.stderr = ""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            stdout, stderr, rc = mod._run("echo test")

            assert stdout == "output"
            assert stderr == ""
            assert rc == 0

    def test_run_failure(self):
        """Test _run with failed command."""
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = "error"
            mock_result.returncode = 1
            mock_run.return_value = mock_result

            stdout, stderr, rc = mod._run("bad command")

            assert stdout == ""
            assert stderr == "error"
            assert rc == 1

    def test_run_timeout(self):
        """Test _run with timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = TimeoutError("Command timed out")

            stdout, stderr, rc = mod._run("slow command", timeout=1)

            assert stdout == ""
            assert "timed out" in stderr.lower()
            assert rc == -1

    def test_run_exception(self):
        """Test _run with general exception."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Generic error")

            stdout, stderr, rc = mod._run("bad command")

            assert stdout == ""
            assert "Generic error" in stderr
            assert rc == -1


# ── Integration Tests ──────────────────────────────────────────────


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_full_workflow(self, tmp_data_dir):
        """Test complete workflow from audit to report."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            monitor = mod.ObsolescenceMonitor()

            # Mock all external calls
            with patch("rudy.obsolescence_monitor._run") as mock_run:
                # Setup _run to return various responses
                def run_side_effect(cmd, timeout=60):
                    if "pip list --outdated" in cmd:
                        return json.dumps([{"name": "pytest"}]), "", 0
                    return "", "", 1

                mock_run.side_effect = run_side_effect

                with patch.object(monitor.health, "check_all") as mock_health, \
                     patch("builtins.print"):

                    mock_health.return_value = {
                        "summary": {"ok": 10, "total": 10, "health_pct": 100.0},
                        "modules": {}
                    }

                    # Execute
                    report = monitor.full_audit()

                    # Validate
                    assert "report_file" in report
                    assert Path(report["report_file"]).exists()

    def test_edge_case_empty_landscape(self, tmp_data_dir):
        """Test edge case with empty landscape scan."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            scanner = mod.LandscapeScanner()

            with patch("rudy.obsolescence_monitor._run") as mock_run:
                mock_run.return_value = ("", "not found", 1)

                result = scanner.scan()

                # Should still have domains, just empty installed
                assert "domains" in result
                for domain in result["domains"].values():
                    assert domain["installed"] == []

    def test_edge_case_no_current_tools_recommendation(self, tmp_data_dir):
        """Test recommendation generation with no current tools."""
        with patch.object(mod, "DATA_DIR", tmp_data_dir):
            scanner = mod.LandscapeScanner()

            scan_result = {
                "domains": {
                    "image_generation": {
                        "installed": [],
                        "missing": [],
                        "current_tools": [],
                        "watch_list": ["flux", "sdxl-turbo"],
                    }
                }
            }

            recs = scanner.generate_recommendations(scan_result)

            # Should have watch list recommendations but no high priority
            evaluate_recs = [r for r in recs if r["action"] == "evaluate"]
            assert len(evaluate_recs) >= 2
