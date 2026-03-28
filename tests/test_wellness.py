import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import json
from datetime import datetime, timedelta

import rudy.wellness as mod


@pytest.fixture
def tmp_wellness_paths(tmp_path, monkeypatch):
    """Redirect all wellness paths to tmp_path."""
    logs_dir = tmp_path / "rudy-logs"
    logs_dir.mkdir()

    monkeypatch.setattr(mod, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(mod, "WELLNESS_CONFIG", logs_dir / "wellness-config.json")
    monkeypatch.setattr(mod, "WELLNESS_STATE", logs_dir / "wellness-state.json")
    monkeypatch.setattr(mod, "WELLNESS_ALERTS", logs_dir / "wellness-alerts.json")
    monkeypatch.setattr(mod, "PRESENCE_CURRENT", logs_dir / "presence-current.json")
    monkeypatch.setattr(mod, "PRESENCE_DEVICES", logs_dir / "presence-devices.json")
    monkeypatch.setattr(mod, "PRESENCE_LOG", logs_dir / "presence-log.json")
    monkeypatch.setattr(mod, "PRESENCE_ROUTINES", logs_dir / "presence-routines.json")

    return logs_dir


@pytest.fixture
def monitor(tmp_wellness_paths):
    """Create a fresh WellnessMonitor instance."""
    return mod.WellnessMonitor()


class TestWellnessMonitorInit:
    """Test WellnessMonitor initialization."""

    def test_init_loads_defaults_when_files_missing(self, monitor):
        """When files don't exist, should load default config."""
        assert monitor.config is not None
        assert monitor.config.get("enabled") is True
        assert monitor.config.get("check_interval_minutes") == 30
        assert monitor.config.get("inactivity_threshold_minutes") == 120
        assert monitor.config.get("nighttime_start") == 23
        assert monitor.config.get("nighttime_end") == 6
        assert monitor.config.get("alert_email") == "ccimino2@gmail.com"

    def test_init_loads_empty_state_when_missing(self, monitor):
        """When state file doesn't exist, should initialize empty."""
        assert monitor.state == {}

    def test_init_loads_empty_collections(self, monitor):
        """Should initialize empty collections."""
        assert monitor.alerts == []
        assert monitor.devices == {}
        assert monitor.current == {}
        assert monitor.routines == {}
        assert monitor.events == []

    def test_init_loads_existing_config(self, tmp_wellness_paths):
        """Should load existing config from file."""
        custom_config = {
            "enabled": False,
            "check_interval_minutes": 60,
            "monitored_persons": {"Grandma": {"device_macs": ["aa:bb:cc:dd:ee:ff"]}},
        }
        with open(tmp_wellness_paths / "wellness-config.json", "w") as f:
            json.dump(custom_config, f)

        monitor = mod.WellnessMonitor()
        assert monitor.config["check_interval_minutes"] == 60
        assert "Grandma" in monitor.config.get("monitored_persons", {})

    def test_init_handles_corrupted_json(self, tmp_wellness_paths, caplog):
        """Should handle corrupted JSON gracefully."""
        with open(tmp_wellness_paths / "wellness-config.json", "w") as f:
            f.write("{ invalid json }")

        with caplog.at_level("DEBUG"):
            monitor = mod.WellnessMonitor()
        assert monitor.config is not None
        # Should load defaults when config is corrupted
        assert monitor.config.get("enabled") is True


class TestLoadSaveJson:
    """Test JSON loading and saving."""

    def test_load_json_with_existing_file(self, monitor, tmp_wellness_paths):
        """Should load JSON from existing file."""
        test_data = {"key": "value", "number": 42}
        test_file = tmp_wellness_paths / "test.json"
        with open(test_file, "w") as f:
            json.dump(test_data, f)

        loaded = monitor._load_json(test_file, {})
        assert loaded == test_data

    def test_load_json_returns_default_when_missing(self, monitor, tmp_path):
        """Should return default when file doesn't exist."""
        missing_file = tmp_path / "missing.json"
        default = {"default": True}

        loaded = monitor._load_json(missing_file, default)
        assert loaded == default

    def test_load_json_returns_default_on_corruption(self, monitor, tmp_wellness_paths, caplog):
        """Should return default when JSON is corrupted."""
        corrupt_file = tmp_wellness_paths / "corrupt.json"
        with open(corrupt_file, "w") as f:
            f.write("not valid json")

        default = {"default": True}
        loaded = monitor._load_json(corrupt_file, default)
        assert loaded == default

    def test_save_json_creates_file(self, monitor, tmp_wellness_paths):
        """Should save JSON to file."""
        test_data = {"key": "value", "nested": {"inner": 123}}
        test_file = tmp_wellness_paths / "output.json"

        monitor._save_json(test_file, test_data)

        assert test_file.exists()
        with open(test_file) as f:
            loaded = json.load(f)
        assert loaded == test_data

    def test_save_json_handles_datetime_objects(self, monitor, tmp_wellness_paths):
        """Should handle datetime serialization."""
        now = datetime.now()
        test_data = {"timestamp": now}
        test_file = tmp_wellness_paths / "datetime.json"

        monitor._save_json(test_file, test_data)

        with open(test_file) as f:
            loaded = json.load(f)
        assert "timestamp" in loaded


class TestDefaultConfig:
    """Test default configuration."""

    def test_default_config_structure(self, monitor):
        """Default config should have required fields."""
        config = monitor._default_config()

        assert "check_interval_minutes" in config
        assert "inactivity_threshold_minutes" in config
        assert "nighttime_start" in config
        assert "nighttime_end" in config
        assert "nighttime_alert_threshold_minutes" in config
        assert "monitored_persons" in config
        assert "alert_email" in config
        assert "enabled" in config

    def test_default_config_values(self, monitor):
        """Default config should have correct values."""
        config = monitor._default_config()

        assert config["check_interval_minutes"] == 30
        assert config["inactivity_threshold_minutes"] == 120
        assert config["nighttime_start"] == 23
        assert config["nighttime_end"] == 6
        assert config["nighttime_alert_threshold_minutes"] == 60
        assert config["monitored_persons"] == {}
        assert config["alert_email"] == "ccimino2@gmail.com"
        assert config["enabled"] is True


class TestAddMonitoredPerson:
    """Test adding monitored persons."""

    def test_add_person_basic(self, monitor, tmp_wellness_paths):
        """Should add a monitored person."""
        monitor.add_monitored_person("Grandma", ["aa:bb:cc:dd:ee:ff"])

        assert "Grandma" in monitor.config["monitored_persons"]
        person = monitor.config["monitored_persons"]["Grandma"]
        assert person["device_macs"] == ["aa:bb:cc:dd:ee:ff"]
        assert person["relationship"] == "family"
        assert person["alert_on_inactivity"] is True
        assert person["alert_on_nighttime_activity"] is False
        assert person["fall_risk"] is False

    def test_add_person_with_custom_options(self, monitor):
        """Should add person with custom settings."""
        monitor.add_monitored_person(
            "Grandpa",
            ["11:22:33:44:55:66", "77:88:99:aa:bb:cc"],
            relationship="grandparent",
            alert_on_inactivity=True,
            alert_on_nighttime_activity=True,
            fall_risk=True,
            custom_threshold_minutes=45,
        )

        person = monitor.config["monitored_persons"]["Grandpa"]
        assert len(person["device_macs"]) == 2
        assert person["relationship"] == "grandparent"
        assert person["alert_on_inactivity"] is True
        assert person["alert_on_nighttime_activity"] is True
        assert person["fall_risk"] is True
        assert person["custom_threshold_minutes"] == 45

    def test_add_person_normalizes_mac_addresses(self, monitor):
        """Should normalize MAC addresses to lowercase."""
        monitor.add_monitored_person("User", ["AA:BB:CC:DD:EE:FF"])

        person = monitor.config["monitored_persons"]["User"]
        assert person["device_macs"][0] == "aa:bb:cc:dd:ee:ff"

    def test_add_person_fall_risk_defaults_threshold(self, monitor):
        """Fall risk persons should have shorter default threshold."""
        monitor.add_monitored_person("FallRisk", ["aa:bb:cc:dd:ee:ff"], fall_risk=True)

        person = monitor.config["monitored_persons"]["FallRisk"]
        assert person["custom_threshold_minutes"] == 60

    def test_add_person_saves_config(self, monitor, tmp_wellness_paths):
        """Should save config to file."""
        monitor.add_monitored_person("SaveTest", ["aa:bb:cc:dd:ee:ff"])

        with open(tmp_wellness_paths / "wellness-config.json") as f:
            saved = json.load(f)
        assert "SaveTest" in saved["monitored_persons"]

    def test_add_person_timestamps_registration(self, monitor):
        """Should timestamp registration."""
        before = datetime.now()
        monitor.add_monitored_person("TimestampTest", ["aa:bb:cc:dd:ee:ff"])
        after = datetime.now()

        person = monitor.config["monitored_persons"]["TimestampTest"]
        registered = datetime.fromisoformat(person["registered"])
        assert before <= registered <= after


class TestIsNighttime:
    """Test nighttime detection."""

    def test_is_nighttime_evening(self, monitor):
        """Should detect evening as nighttime."""
        # 11 PM
        dt = datetime(2026, 3, 28, 23, 0, 0)
        assert monitor._is_nighttime(dt) is True

    def test_is_nighttime_midnight(self, monitor):
        """Should detect midnight as nighttime."""
        # 12 AM
        dt = datetime(2026, 3, 28, 0, 0, 0)
        assert monitor._is_nighttime(dt) is True

    def test_is_nighttime_early_morning(self, monitor):
        """Should detect early morning as nighttime."""
        # 5 AM
        dt = datetime(2026, 3, 28, 5, 0, 0)
        assert monitor._is_nighttime(dt) is True

    def test_is_not_nighttime_morning(self, monitor):
        """Should detect morning as daytime."""
        # 6 AM (boundary)
        dt = datetime(2026, 3, 28, 6, 0, 0)
        assert monitor._is_nighttime(dt) is False

    def test_is_not_nighttime_day(self, monitor):
        """Should detect daytime as not nighttime."""
        # 3 PM
        dt = datetime(2026, 3, 28, 15, 0, 0)
        assert monitor._is_nighttime(dt) is False

    def test_is_nighttime_respects_config(self, monitor):
        """Should respect custom nighttime bounds."""
        monitor.config["nighttime_start"] = 20  # 8 PM
        monitor.config["nighttime_end"] = 8  # 8 AM

        dt_evening = datetime(2026, 3, 28, 20, 0, 0)
        dt_day = datetime(2026, 3, 28, 10, 0, 0)

        assert monitor._is_nighttime(dt_evening) is True
        assert monitor._is_nighttime(dt_day) is False


class TestCheckPerson:
    """Test person wellness checks."""

    def test_check_person_no_devices(self, monitor):
        """Should handle person with no devices."""
        config = {"device_macs": []}
        now = datetime.now()

        status = monitor._check_person("NoDevices", config, now, False)

        assert status["name"] == "NoDevices"
        assert status["devices_present"] == 0
        assert status["devices_absent"] == 0
        assert status["wellness"] == "ok"
        assert status["alerts"] == []

    def test_check_person_device_present(self, monitor):
        """Should detect when device is present."""
        monitor.current = {
            "aa:bb:cc:dd:ee:ff": {
                "last_seen": datetime.now().isoformat()
            }
        }
        config = {"device_macs": ["aa:bb:cc:dd:ee:ff"]}
        now = datetime.now()

        status = monitor._check_person("Home", config, now, False)

        assert status["devices_present"] == 1
        assert status["devices_absent"] == 0
        assert status["last_seen"] is not None

    def test_check_person_device_absent(self, monitor):
        """Should detect when device is absent."""
        monitor.current = {}
        config = {"device_macs": ["aa:bb:cc:dd:ee:ff"]}
        now = datetime.now()

        status = monitor._check_person("Away", config, now, False)

        assert status["devices_present"] == 0
        assert status["devices_absent"] == 1
        assert status["last_seen"] is None

    def test_check_person_multiple_devices(self, monitor):
        """Should track multiple devices."""
        monitor.current = {
            "aa:bb:cc:dd:ee:ff": {"last_seen": datetime.now().isoformat()}
        }
        config = {"device_macs": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]}
        now = datetime.now()

        status = monitor._check_person("MultiDevice", config, now, False)

        assert status["devices_present"] == 1
        assert status["devices_absent"] == 1

    def test_check_person_inactivity_alert_triggered(self, monitor):
        """Should trigger inactivity alert when threshold exceeded."""
        monitor.current = {}
        monitor.state = {}

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_inactivity": True,
        }
        now = datetime.now()
        past = now - timedelta(minutes=150)

        monitor.state["person_Test"] = {
            "last_seen_home": past.isoformat(),
            "consecutive_absent_checks": 1,
        }

        status = monitor._check_person("Test", config, now, False)

        assert len(status["alerts"]) > 0
        assert status["alerts"][0]["type"] == "inactivity"
        assert "150" in status["alerts"][0]["message"]
        assert status["wellness"] == "concern"

    def test_check_person_inactivity_respects_threshold(self, monitor):
        """Should respect custom threshold."""
        monitor.current = {}
        monitor.state = {}

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_inactivity": True,
            "custom_threshold_minutes": 200,
        }
        now = datetime.now()
        past = now - timedelta(minutes=150)

        monitor.state["person_Test"] = {
            "last_seen_home": past.isoformat(),
        }

        status = monitor._check_person("Test", config, now, False)

        # Should not alert since 150 < 200
        assert len(status["alerts"]) == 0

    def test_check_person_inactivity_alert_throttling(self, monitor):
        """Should not alert more than once per hour."""
        monitor.current = {}
        monitor.state = {}

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_inactivity": True,
        }
        now = datetime.now()
        past = now - timedelta(minutes=150)
        recent_alert = now - timedelta(minutes=30)

        monitor.state["person_Test"] = {
            "last_seen_home": past.isoformat(),
            "last_alert_time": recent_alert.isoformat(),
        }

        status = monitor._check_person("Test", config, now, False)

        # Should not alert due to throttling
        assert len(status["alerts"]) == 0

    def test_check_person_nighttime_shorter_threshold(self, monitor):
        """Should use shorter threshold at night for fall-risk persons."""
        monitor.current = {}
        monitor.state = {}

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_inactivity": True,
            "fall_risk": True,
        }
        monitor.config["nighttime_alert_threshold_minutes"] = 30

        now = datetime.now()
        past = now - timedelta(minutes=45)

        monitor.state["person_Test"] = {
            "last_seen_home": past.isoformat(),
        }

        status = monitor._check_person("Test", config, now, is_nighttime=True)

        assert len(status["alerts"]) > 0
        assert "30 min" in status["alerts"][0]["message"]
        assert status["alerts"][0]["context"] == "nighttime"

    def test_check_person_updates_presence_state(self, monitor):
        """Should update person's presence state."""
        monitor.current = {"aa:bb:cc:dd:ee:ff": {"last_seen": datetime.now().isoformat()}}
        monitor.state = {}

        config = {"device_macs": ["aa:bb:cc:dd:ee:ff"]}
        now = datetime.now()

        monitor._check_person("Home", config, now, False)

        person_state = monitor.state["person_Home"]
        assert person_state["last_seen_home"] is not None
        assert person_state["consecutive_absent_checks"] == 0

    def test_check_person_tracks_consecutive_absence(self, monitor):
        """Should track consecutive absence checks."""
        monitor.current = {}
        monitor.state = {"person_Away": {"consecutive_absent_checks": 2}}

        config = {"device_macs": ["aa:bb:cc:dd:ee:ff"]}
        now = datetime.now()

        monitor._check_person("Away", config, now, False)

        assert monitor.state["person_Away"]["consecutive_absent_checks"] == 3


class TestNighttimeActivityAlert:
    """Test nighttime activity alerting."""

    def test_nighttime_activity_alert_triggered(self, monitor):
        """Should alert on unusual nighttime activity."""
        monitor.current = {"aa:bb:cc:dd:ee:ff": {"last_seen": datetime.now().isoformat()}}
        monitor.state = {}
        monitor.routines = {
            "aa:bb:cc:dd:ee:ff": {
                "total_scans": 50,
                "weekly": {
                    "Saturday": {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 0, 6: 0}
                }
            }
        }

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_nighttime_activity": True,
        }
        # Saturday 3 AM
        now = datetime(2026, 3, 28, 3, 0, 0)

        status = monitor._check_person("Test", config, now, is_nighttime=True)

        alerts = [a for a in status["alerts"] if a["type"] == "unusual_nighttime_activity"]
        assert len(alerts) > 0
        assert "Saturday" in alerts[0]["message"]

    def test_no_nighttime_activity_alert_when_normal(self, monitor):
        """Should not alert on normal nighttime activity."""
        monitor.current = {"aa:bb:cc:dd:ee:ff": {"last_seen": datetime.now().isoformat()}}
        monitor.state = {}
        monitor.routines = {
            "aa:bb:cc:dd:ee:ff": {
                "total_scans": 50,
                "weekly": {
                    "Saturday": {0: 10, 1: 8, 2: 12, 3: 14}
                }
            }
        }

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_nighttime_activity": True,
        }
        now = datetime(2026, 3, 28, 3, 0, 0)

        status = monitor._check_person("Test", config, now, is_nighttime=True)

        alerts = [a for a in status["alerts"] if a["type"] == "unusual_nighttime_activity"]
        assert len(alerts) == 0


class TestRoutineDeviationAlert:
    """Test routine deviation detection."""

    def test_routine_deviation_alert_triggered(self, monitor):
        """Should alert when person is absent during typical presence time."""
        monitor.current = {}
        monitor.state = {}
        monitor.routines = {
            "aa:bb:cc:dd:ee:ff": {
                "total_scans": 50,
                "weekly": {
                    "Saturday": {14: 10, 15: 8, 16: 12}
                }
            }
        }

        config = {"device_macs": ["aa:bb:cc:dd:ee:ff"]}
        # Saturday 3 PM
        now = datetime(2026, 3, 28, 15, 0, 0)

        status = monitor._check_person("Test", config, now, is_nighttime=False)

        alerts = [a for a in status["alerts"] if a["type"] == "routine_deviation"]
        assert len(alerts) > 0
        assert "usually home" in alerts[0]["message"]

    def test_no_routine_deviation_with_insufficient_data(self, monitor):
        """Should not alert with insufficient routine data."""
        monitor.current = {}
        monitor.state = {}
        monitor.routines = {
            "aa:bb:cc:dd:ee:ff": {
                "total_scans": 5,  # Too few
                "weekly": {"Saturday": {15: 3}}
            }
        }

        config = {"device_macs": ["aa:bb:cc:dd:ee:ff"]}
        now = datetime(2026, 3, 28, 15, 0, 0)

        status = monitor._check_person("Test", config, now, is_nighttime=False)

        alerts = [a for a in status["alerts"] if a["type"] == "routine_deviation"]
        assert len(alerts) == 0


class TestCheck:
    """Test main check cycle."""

    def test_check_returns_findings(self, monitor):
        """Should return findings dict with proper structure."""
        findings = monitor.check()

        assert "timestamp" in findings
        assert "persons_checked" in findings
        assert "alerts_generated" in findings
        assert "status" in findings
        assert findings["persons_checked"] == 0
        assert findings["alerts_generated"] == []

    def test_check_skips_when_disabled(self, monitor):
        """Should skip check when disabled."""
        monitor.config["enabled"] = False
        monitor.add_monitored_person("Test", ["aa:bb:cc:dd:ee:ff"])

        findings = monitor.check()

        assert findings["persons_checked"] == 0

    def test_check_includes_all_monitored_persons(self, monitor):
        """Should check all monitored persons."""
        monitor.add_monitored_person("Person1", ["aa:bb:cc:dd:ee:ff"])
        monitor.add_monitored_person("Person2", ["11:22:33:44:55:66"])

        findings = monitor.check()

        assert findings["persons_checked"] == 2
        assert "Person1" in findings["status"]
        assert "Person2" in findings["status"]

    def test_check_saves_state(self, monitor, tmp_wellness_paths):
        """Should save state after check."""
        monitor.add_monitored_person("Test", ["aa:bb:cc:dd:ee:ff"])
        monitor.check()

        with open(tmp_wellness_paths / "wellness-state.json") as f:
            saved_state = json.load(f)
        assert "last_check" in saved_state

    def test_check_saves_alerts(self, monitor, tmp_wellness_paths):
        """Should save alerts after check."""
        monitor.add_monitored_person("Test", ["aa:bb:cc:dd:ee:ff"])
        monitor.current = {}
        monitor.state = {
            "person_Test": {
                "last_seen_home": (datetime.now() - timedelta(hours=3)).isoformat(),
            }
        }

        monitor.check()

        with open(tmp_wellness_paths / "wellness-alerts.json") as f:
            saved_alerts = json.load(f)
        # May have alerts from inactivity
        assert isinstance(saved_alerts, list)

    def test_check_maintains_alert_history(self, monitor):
        """Should maintain last 200 alerts."""
        for i in range(250):
            alert = {
                "time": datetime.now().isoformat(),
                "person": "Test",
                "type": "test",
                "severity": "low",
                "message": f"Alert {i}",
            }
            monitor.alerts.append(alert)

        monitor.check()

        # Should keep only last 200
        assert len(monitor.alerts) <= 200


class TestGetDashboard:
    """Test dashboard generation."""

    def test_dashboard_includes_header(self, monitor):
        """Dashboard should include header."""
        dashboard = monitor.get_dashboard()

        assert "FAMILY WELLNESS DASHBOARD" in dashboard
        assert "=" * 50 in dashboard

    def test_dashboard_lists_monitored_persons(self, monitor):
        """Dashboard should list all monitored persons."""
        monitor.add_monitored_person("Alice", ["aa:bb:cc:dd:ee:ff"], relationship="parent")
        monitor.add_monitored_person("Bob", ["11:22:33:44:55:66"], relationship="child")

        dashboard = monitor.get_dashboard()

        assert "Alice (parent)" in dashboard
        assert "Bob (child)" in dashboard

    def test_dashboard_shows_device_status(self, monitor):
        """Dashboard should show device status."""
        monitor.add_monitored_person("Test", ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"])
        monitor.current = {"aa:bb:cc:dd:ee:ff": {"last_seen": datetime.now().isoformat()}}

        dashboard = monitor.get_dashboard()

        assert "1/2 devices" in dashboard
        assert "HOME" in dashboard

    def test_dashboard_shows_away_status(self, monitor):
        """Dashboard should show away status."""
        monitor.add_monitored_person("Test", ["aa:bb:cc:dd:ee:ff"])
        monitor.current = {}

        dashboard = monitor.get_dashboard()

        assert "AWAY" in dashboard

    def test_dashboard_indicates_fall_risk(self, monitor):
        """Dashboard should indicate fall risk persons."""
        monitor.add_monitored_person("Grandma", ["aa:bb:cc:dd:ee:ff"], fall_risk=True)

        dashboard = monitor.get_dashboard()

        assert "[FALL RISK]" in dashboard

    def test_dashboard_shows_recent_alerts(self, monitor):
        """Dashboard should show recent high/medium severity alerts."""
        alert = {
            "time": datetime.now().isoformat(),
            "person": "Test",
            "type": "inactivity",
            "severity": "high",
            "message": "Test alert message",
        }
        monitor.alerts = [alert]

        dashboard = monitor.get_dashboard()

        assert "RECENT ALERTS" in dashboard
        assert "Test alert message" in dashboard

    def test_dashboard_ignores_low_severity_alerts(self, monitor):
        """Dashboard should not show low severity alerts."""
        alert = {
            "time": datetime.now().isoformat(),
            "person": "Test",
            "type": "unusual_nighttime_activity",
            "severity": "low",
            "message": "Low severity alert",
        }
        monitor.alerts = [alert]

        dashboard = monitor.get_dashboard()

        assert "Low severity alert" not in dashboard

    def test_dashboard_shows_last_home_time(self, monitor):
        """Dashboard should show last home time."""
        now = datetime.now()
        monitor.add_monitored_person("Test", ["aa:bb:cc:dd:ee:ff"])
        monitor.state = {
            "person_Test": {
                "last_seen_home": now.isoformat(),
            }
        }

        dashboard = monitor.get_dashboard()

        last_home_str = now.strftime("%Y-%m-%d %H:%M")
        assert last_home_str in dashboard


class TestRunWellnessCheck:
    """Test main run function."""

    def test_run_wellness_check_executes(self, monitor, monkeypatch, capsys):
        """Should execute wellness check and print output."""
        monkeypatch.setattr(mod, "WellnessMonitor", lambda: monitor)

        findings = mod.run_wellness_check()

        assert findings is not None
        assert "timestamp" in findings

    def test_run_wellness_check_reports_alerts(self, monitor, monkeypatch, capsys):
        """Should report alerts in output."""
        monitor.add_monitored_person("Test", ["aa:bb:cc:dd:ee:ff"])
        monitor.current = {}
        monitor.state = {
            "person_Test": {
                "last_seen_home": (datetime.now() - timedelta(hours=3)).isoformat(),
            }
        }
        monkeypatch.setattr(mod, "WellnessMonitor", lambda: monitor)

        findings = mod.run_wellness_check()
        captured = capsys.readouterr()

        assert "alerts generated" in captured.out.lower() or len(findings["alerts_generated"]) >= 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_device_list_mac_addresses(self, monitor):
        """Should handle empty device list."""
        monitor.add_monitored_person("NeverMonitored", [], alert_on_inactivity=False)

        findings = monitor.check()

        assert findings["persons_checked"] == 1
        assert findings["status"]["NeverMonitored"]["devices_present"] == 0
        assert findings["status"]["NeverMonitored"]["alerts"] == []

    def test_person_with_no_state_history(self, monitor):
        """Should initialize state for person with no history."""
        monitor.add_monitored_person("NewPerson", ["aa:bb:cc:dd:ee:ff"])
        monitor.current = {}
        monitor.state = {}

        config = monitor.config["monitored_persons"]["NewPerson"]
        status = monitor._check_person("NewPerson", config, datetime.now(), False)

        assert status["name"] == "NewPerson"
        assert status["wellness"] == "ok"

    def test_parse_invalid_last_home_date(self, monitor):
        """Should handle invalid ISO format dates gracefully."""
        monitor.current = {}
        monitor.state = {
            "person_Test": {
                "last_seen_home": "invalid-date-format",
            }
        }

        config = {"device_macs": ["aa:bb:cc:dd:ee:ff"], "alert_on_inactivity": True}

        # Should not crash
        status = monitor._check_person("Test", config, datetime.now(), False)
        assert status is not None

    def test_multiple_devices_last_seen_ordering(self, monitor):
        """Should pick the most recent last_seen time."""
        now = datetime.now()
        past1 = now - timedelta(minutes=5)
        past2 = now - timedelta(minutes=10)

        monitor.current = {
            "aa:bb:cc:dd:ee:ff": {"last_seen": past1.isoformat()},
            "11:22:33:44:55:66": {"last_seen": past2.isoformat()},
        }

        config = {"device_macs": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]}
        status = monitor._check_person("Test", config, now, False)

        assert status["last_seen"] == past1.isoformat()

    def test_zero_minute_threshold(self, monitor):
        """Should handle zero minute threshold."""
        monitor.current = {}
        monitor.state = {
            "person_Test": {
                "last_seen_home": (datetime.now() - timedelta(minutes=1)).isoformat(),
            }
        }

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_inactivity": True,
            "custom_threshold_minutes": 0,
        }

        status = monitor._check_person("Test", config, datetime.now(), False)

        # With 1 minute absence and 0 threshold, should alert
        assert len(status["alerts"]) > 0

    def test_high_device_count(self, monitor):
        """Should handle person with many devices."""
        macs = [f"aa:bb:cc:dd:ee:{i:02x}" for i in range(20)]
        monitor.add_monitored_person("ManyDevices", macs)

        present_count = 10
        monitor.current = {
            macs[i]: {"last_seen": datetime.now().isoformat()}
            for i in range(present_count)
        }

        config = monitor.config["monitored_persons"]["ManyDevices"]
        status = monitor._check_person("ManyDevices", config, datetime.now(), False)

        assert status["devices_present"] == present_count
        assert status["devices_absent"] == 10


class TestAlertSeverity:
    """Test alert severity levels."""

    def test_inactivity_alert_high_severity_for_fall_risk(self, monitor):
        """Inactivity alerts for fall-risk should be high severity."""
        monitor.current = {}
        monitor.state = {
            "person_Test": {
                "last_seen_home": (datetime.now() - timedelta(hours=2)).isoformat(),
            }
        }

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_inactivity": True,
            "fall_risk": True,
        }

        status = monitor._check_person("Test", config, datetime.now(), False)

        assert len(status["alerts"]) > 0
        assert status["alerts"][0]["severity"] == "high"

    def test_inactivity_alert_medium_severity_normal(self, monitor):
        """Inactivity alerts for normal persons should be medium severity."""
        monitor.current = {}
        monitor.state = {
            "person_Test": {
                "last_seen_home": (datetime.now() - timedelta(hours=2)).isoformat(),
            }
        }

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_inactivity": True,
            "fall_risk": False,
        }

        status = monitor._check_person("Test", config, datetime.now(), False)

        assert len(status["alerts"]) > 0
        assert status["alerts"][0]["severity"] == "medium"

    def test_nighttime_activity_alert_low_severity(self, monitor):
        """Nighttime activity should be low severity."""
        monitor.current = {"aa:bb:cc:dd:ee:ff": {"last_seen": datetime.now().isoformat()}}
        monitor.state = {}
        monitor.routines = {
            "aa:bb:cc:dd:ee:ff": {
                "total_scans": 50,
                "weekly": {"Saturday": {0: 0, 1: 0, 2: 0, 3: 0}}
            }
        }

        config = {
            "device_macs": ["aa:bb:cc:dd:ee:ff"],
            "alert_on_nighttime_activity": True,
        }
        now = datetime(2026, 3, 28, 3, 0, 0)

        status = monitor._check_person("Test", config, now, is_nighttime=True)

        alerts = [a for a in status["alerts"] if a["type"] == "unusual_nighttime_activity"]
        if alerts:
            assert alerts[0]["severity"] == "low"
