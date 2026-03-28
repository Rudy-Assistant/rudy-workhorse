import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
from datetime import datetime, timedelta
import json

import rudy.presence as mod


@pytest.fixture
def tmp_logs_dir(tmp_path):
    """Fixture that redirects LOGS_DIR to a temporary directory."""
    return tmp_path / "rudy-logs"


@pytest.fixture
def monkeypatch_logs(monkeypatch, tmp_logs_dir):
    """Monkeypatch all log file constants to use tmp_logs_dir."""
    tmp_logs_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "LOGS_DIR", tmp_logs_dir)
    monkeypatch.setattr(mod, "DEVICES_FILE", tmp_logs_dir / "presence-devices.json")
    monkeypatch.setattr(mod, "LOG_FILE", tmp_logs_dir / "presence-log.json")
    monkeypatch.setattr(mod, "CURRENT_FILE", tmp_logs_dir / "presence-current.json")
    monkeypatch.setattr(mod, "ROUTINES_FILE", tmp_logs_dir / "presence-routines.json")

    return tmp_logs_dir


@pytest.fixture
def mock_subnet_gateway(monkeypatch):
    """Mock subnet and gateway detection."""
    monkeypatch.setattr(mod, "LOCAL_SUBNET", "192.168.1")
    monkeypatch.setattr(mod, "GATEWAY", "192.168.1.1")


@pytest.fixture
def monitor(monkeypatch_logs, mock_subnet_gateway):
    """Create a PresenceMonitor with mocked filesystem."""
    return mod.PresenceMonitor()


# ============================================================================
# Tests for _detect_subnet()
# ============================================================================

class TestDetectSubnet:
    """Tests for subnet detection logic."""

    def test_detect_subnet_success(self, monkeypatch):
        """Test successful subnet detection from socket."""
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("192.168.42.100", 0)

        def mock_socket_init(*args, **kwargs):
            return mock_socket

        monkeypatch.setattr("socket.socket", mock_socket_init)

        subnet = mod._detect_subnet()
        assert subnet == "192.168.42"

    def test_detect_subnet_fallback_on_error(self, monkeypatch):
        """Test fallback subnet when socket fails."""
        def mock_socket_error(*args, **kwargs):
            raise Exception("Network error")

        monkeypatch.setattr("socket.socket", mock_socket_error)

        subnet = mod._detect_subnet()
        assert subnet == "192.168.7"

    def test_detect_subnet_various_ips(self, monkeypatch):
        """Test subnet detection with various IP addresses."""
        test_cases = [
            ("10.0.0.50", "10.0.0"),
            ("172.16.5.200", "172.16.5"),
            ("192.168.100.1", "192.168.100"),
        ]

        for ip, expected_subnet in test_cases:
            mock_socket = MagicMock()
            mock_socket.getsockname.return_value = (ip, 0)

            def mock_socket_init(*args, **kwargs):
                return mock_socket

            monkeypatch.setattr("socket.socket", mock_socket_init)
            subnet = mod._detect_subnet()
            assert subnet == expected_subnet


class TestDetectGateway:
    """Tests for gateway detection logic."""

    def test_detect_gateway_success(self, monkeypatch):
        """Test successful gateway detection from ipconfig."""
        ipconfig_output = """
Windows IP Configuration
  Default Gateway . . . . . . . . . : 192.168.1.254
  DHCP Server . . . . . . . . . . . : 192.168.1.1
        """

        mock_result = MagicMock()
        mock_result.stdout = ipconfig_output

        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        gateway = mod._detect_gateway()
        assert gateway == "192.168.1.254"

    def test_detect_gateway_fallback_on_error(self, monkeypatch):
        """Test fallback gateway when ipconfig fails."""
        def mock_run_error(*args, **kwargs):
            raise Exception("Command failed")

        monkeypatch.setattr("subprocess.run", mock_run_error)

        gateway = mod._detect_gateway()
        assert gateway == "192.168.7.1"

    def test_detect_gateway_no_match(self, monkeypatch):
        """Test fallback when no gateway found in output."""
        mock_result = MagicMock()
        mock_result.stdout = "No gateway info here"

        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        gateway = mod._detect_gateway()
        assert gateway == "192.168.7.1"


# ============================================================================
# Tests for PresenceMonitor initialization and JSON handling
# ============================================================================

class TestPresenceMonitorInit:
    """Tests for PresenceMonitor initialization."""

    def test_init_empty_state(self, monitor):
        """Test initialization with no existing data."""
        assert monitor.known_devices == {}
        assert monitor.current_presence == {}
        assert monitor.event_log == []
        assert monitor.routines == {}

    def test_init_loads_existing_data(self, monkeypatch_logs, mock_subnet_gateway):
        """Test initialization loads existing JSON files."""
        # Prepare existing data
        devices_data = {"aa:bb:cc:dd:ee:ff": {"name": "Phone", "type": "phone"}}
        presence_data = {"aa:bb:cc:dd:ee:ff": {"mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.100"}}

        (monkeypatch_logs / "presence-devices.json").write_text(json.dumps(devices_data))
        (monkeypatch_logs / "presence-current.json").write_text(json.dumps(presence_data))

        monitor = mod.PresenceMonitor()
        assert monitor.known_devices == devices_data
        assert monitor.current_presence == presence_data

    def test_load_json_handles_missing_file(self, monitor):
        """Test _load_json returns default for missing file."""
        result = monitor._load_json(Path("/nonexistent/file.json"), {})
        assert result == {}

    def test_load_json_handles_invalid_json(self, monkeypatch_logs, monitor):
        """Test _load_json returns default for invalid JSON."""
        bad_file = monkeypatch_logs / "bad.json"
        bad_file.write_text("{ invalid json }")

        result = monitor._load_json(bad_file, [])
        assert result == []

    def test_save_json_creates_file(self, monitor, monkeypatch_logs):
        """Test _save_json creates and writes file."""
        test_data = {"test": "data", "nested": {"value": 123}}
        test_file = monkeypatch_logs / "test.json"

        monitor._save_json(test_file, test_data)

        assert test_file.exists()
        loaded = json.loads(test_file.read_text())
        assert loaded == test_data

    def test_save_json_handles_non_serializable(self, monitor, monkeypatch_logs):
        """Test _save_json uses default=str for non-serializable objects."""
        test_data = {
            "date": datetime(2026, 3, 28, 10, 30, 0),
            "path": Path("/some/path"),
        }
        test_file = monkeypatch_logs / "test.json"

        monitor._save_json(test_file, test_data)

        assert test_file.exists()
        loaded = json.loads(test_file.read_text())
        assert loaded["date"] == "2026-03-28 10:30:00"
        assert loaded["path"] == "/some/path"


# ============================================================================
# Tests for ARP table parsing
# ============================================================================

class TestReadArpTable:
    """Tests for ARP table reading and parsing."""

    def test_read_arp_table_success(self, monitor, monkeypatch):
        """Test successful ARP table parsing."""
        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-dd-ee-01     dynamic
  192.168.1.50          aa-bb-cc-dd-ee-02     static
  192.168.1.100         aa-bb-cc-dd-ee-03     static
        """

        mock_result = MagicMock()
        mock_result.stdout = arp_output
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        discovered = monitor._read_arp_table()

        assert len(discovered) == 3
        assert discovered["aa-bb-cc-dd-ee-01"]["ip"] == "192.168.1.1"
        assert discovered["aa-bb-cc-dd-ee-02"]["ip"] == "192.168.1.50"
        assert discovered["aa-bb-cc-dd-ee-03"]["type"] == "static"

    def test_read_arp_table_filters_broadcast_mac(self, monitor, monkeypatch):
        """Test that broadcast MACs are filtered out."""
        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.255         ff-ff-ff-ff-ff-ff     dynamic
  192.168.1.50          aa-bb-cc-dd-ee-02     static
        """

        mock_result = MagicMock()
        mock_result.stdout = arp_output
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        discovered = monitor._read_arp_table()

        assert len(discovered) == 1
        assert "ff-ff-ff-ff-ff-ff" not in discovered
        assert "aa-bb-cc-dd-ee-02" in discovered

    def test_read_arp_table_filters_multicast_mac(self, monitor, monkeypatch):
        """Test that multicast MACs are filtered out."""
        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.50          01-00-5e-00-00-01     dynamic
  192.168.1.51          aa-bb-cc-dd-ee-02     static
        """

        mock_result = MagicMock()
        mock_result.stdout = arp_output
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        discovered = monitor._read_arp_table()

        assert len(discovered) == 1
        assert "01-00-5e-00-00-01" not in discovered

    def test_read_arp_table_filters_wrong_subnet(self, monitor, monkeypatch):
        """Test that IPs not on our subnet are filtered."""
        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.50          aa-bb-cc-dd-ee-02     static
  10.0.0.1              aa-bb-cc-dd-ee-03     dynamic
  192.168.1.51          aa-bb-cc-dd-ee-04     static
        """

        mock_result = MagicMock()
        mock_result.stdout = arp_output
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        discovered = monitor._read_arp_table()

        assert len(discovered) == 2
        assert "aa-bb-cc-dd-ee-03" not in discovered  # 10.0.0.1

    def test_read_arp_table_case_insensitive_mac(self, monitor, monkeypatch):
        """Test that MAC addresses are normalized to lowercase."""
        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.50          AA-BB-CC-DD-EE-02     static
        """

        mock_result = MagicMock()
        mock_result.stdout = arp_output
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        discovered = monitor._read_arp_table()

        assert "aa-bb-cc-dd-ee-02" in discovered
        assert "AA-BB-CC-DD-EE-02" not in discovered

    def test_read_arp_table_subprocess_failure(self, monitor, monkeypatch):
        """Test graceful handling of subprocess failure."""
        def mock_run_error(*args, **kwargs):
            raise Exception("ARP command failed")

        monkeypatch.setattr("subprocess.run", mock_run_error)

        discovered = monitor._read_arp_table()

        assert discovered == {}

    def test_read_arp_table_empty_output(self, monitor, monkeypatch):
        """Test handling of empty ARP output."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        discovered = monitor._read_arp_table()

        assert discovered == {}


# ============================================================================
# Tests for change detection
# ============================================================================

class TestDetectChanges:
    """Tests for arrival/departure detection."""

    def test_detect_arrival_known_device(self, monitor):
        """Test detecting arrival of a known device."""
        monitor.known_devices = {
            "aa-bb-cc-dd-ee-01": {"name": "Alice's Phone", "type": "phone"}
        }

        discovered = {
            "aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "type": "dynamic"}
        }

        events = monitor._detect_changes(discovered)

        assert len(events) == 1
        assert events[0]["type"] == "arrival"
        assert events[0]["mac"] == "aa-bb-cc-dd-ee-01"
        assert events[0]["name"] == "Alice's Phone"
        assert events[0]["known"] is True

    def test_detect_arrival_unknown_device(self, monitor):
        """Test detecting arrival of an unknown device."""
        discovered = {
            "xx-yy-zz-aa-bb-cc": {"ip": "192.168.1.150", "type": "dynamic"}
        }

        events = monitor._detect_changes(discovered)

        assert len(events) == 1
        assert events[0]["type"] == "arrival"
        assert events[0]["name"] == "Unknown Device"
        assert events[0]["known"] is False

    def test_detect_departure_known_device(self, monitor):
        """Test detecting departure of a known device."""
        monitor.known_devices = {
            "aa-bb-cc-dd-ee-01": {"name": "Bob's Laptop", "type": "laptop"}
        }
        monitor.current_presence = {
            "aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "mac": "aa-bb-cc-dd-ee-01"}
        }

        discovered = {}  # Device no longer present

        events = monitor._detect_changes(discovered)

        assert len(events) == 1
        assert events[0]["type"] == "departure"
        assert events[0]["mac"] == "aa-bb-cc-dd-ee-01"
        assert events[0]["name"] == "Bob's Laptop"
        assert events[0]["ip"] == "192.168.1.100"

    def test_detect_no_changes(self, monitor):
        """Test that no events are recorded when nothing changes."""
        monitor.known_devices = {
            "aa-bb-cc-dd-ee-01": {"name": "Device A", "type": "phone"}
        }
        monitor.current_presence = {
            "aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "mac": "aa-bb-cc-dd-ee-01"}
        }

        discovered = {
            "aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "type": "dynamic"}
        }

        events = monitor._detect_changes(discovered)

        assert len(events) == 0

    def test_detect_multiple_arrivals_and_departures(self, monitor):
        """Test detecting multiple simultaneous arrivals and departures."""
        monitor.known_devices = {
            "aa-bb-cc-dd-ee-01": {"name": "Device A", "type": "phone"},
            "aa-bb-cc-dd-ee-02": {"name": "Device B", "type": "phone"},
        }
        monitor.current_presence = {
            "aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "mac": "aa-bb-cc-dd-ee-01"},
            "aa-bb-cc-dd-ee-03": {"ip": "192.168.1.150", "mac": "aa-bb-cc-dd-ee-03"},
        }

        discovered = {
            "aa-bb-cc-dd-ee-02": {"ip": "192.168.1.101", "type": "dynamic"},
            "aa-bb-cc-dd-ee-04": {"ip": "192.168.1.151", "type": "dynamic"},
        }

        events = monitor._detect_changes(discovered)

        arrivals = [e for e in events if e["type"] == "arrival"]
        departures = [e for e in events if e["type"] == "departure"]

        assert len(arrivals) == 2
        assert len(departures) == 2


# ============================================================================
# Tests for routine learning
# ============================================================================

class TestUpdateRoutines:
    """Tests for routine tracking and learning."""

    @patch("rudy.presence.datetime")
    def test_update_routines_creates_new_entry(self, mock_datetime, monitor):
        """Test creating a new routine entry for a device."""
        mock_now = datetime(2026, 3, 23, 14, 0, 0)  # Monday, 2 PM
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        monitor.known_devices = {
            "aa-bb-cc-dd-ee-01": {"name": "Alice's Phone", "type": "phone"}
        }

        discovered = {
            "aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "type": "dynamic"}
        }

        monitor._update_routines(discovered)

        assert "aa-bb-cc-dd-ee-01" in monitor.routines
        assert monitor.routines["aa-bb-cc-dd-ee-01"]["name"] == "Alice's Phone"
        assert monitor.routines["aa-bb-cc-dd-ee-01"]["weekly"]["Monday"][14] == 1

    @patch("rudy.presence.datetime")
    def test_update_routines_increments_count(self, mock_datetime, monitor):
        """Test that routine counts increment on repeated scans."""
        mock_now = datetime(2026, 3, 23, 14, 0, 0)  # Monday, 2 PM
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        discovered = {"aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "type": "dynamic"}}

        # First scan
        monitor._update_routines(discovered)
        first_count = monitor.routines["aa-bb-cc-dd-ee-01"]["weekly"]["Monday"][14]

        # Second scan
        monitor._update_routines(discovered)
        second_count = monitor.routines["aa-bb-cc-dd-ee-01"]["weekly"]["Monday"][14]

        assert second_count == first_count + 1

    @patch("rudy.presence.datetime")
    def test_update_routines_tracks_all_days(self, mock_datetime, monitor):
        """Test that routines track all days of the week."""
        mock_now = datetime(2026, 3, 23, 10, 0, 0)  # Monday
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        discovered = {"aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "type": "dynamic"}}

        monitor._update_routines(discovered)

        expected_days = [
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"
        ]

        for day in expected_days:
            assert day in monitor.routines["aa-bb-cc-dd-ee-01"]["weekly"]


# ============================================================================
# Tests for device registration
# ============================================================================

class TestRegisterDevice:
    """Tests for device registration."""

    def test_register_device_basic(self, monitor, monkeypatch_logs):
        """Test basic device registration."""
        monitor.register_device("AA:BB:CC:DD:EE:01", "Alice's Phone", "phone", "alice")

        assert "aa:bb:cc:dd:ee:01" in monitor.known_devices
        device = monitor.known_devices["aa:bb:cc:dd:ee:01"]
        assert device["name"] == "Alice's Phone"
        assert device["type"] == "phone"
        assert device["owner"] == "alice"

    def test_register_device_case_normalized(self, monitor):
        """Test that MAC addresses are normalized to lowercase."""
        monitor.register_device("AA:BB:CC:DD:EE:01", "Device", "phone", "owner")

        assert "aa:bb:cc:dd:ee:01" in monitor.known_devices
        assert "AA:BB:CC:DD:EE:01" not in monitor.known_devices

    def test_register_device_saves_file(self, monitor, monkeypatch_logs):
        """Test that registration saves to devices file."""
        monitor.register_device("aa:bb:cc:dd:ee:01", "Device", "phone", "owner")

        devices_file = monkeypatch_logs / "presence-devices.json"
        assert devices_file.exists()
        loaded = json.loads(devices_file.read_text())
        assert "aa:bb:cc:dd:ee:01" in loaded

    def test_register_device_overwrites_existing(self, monitor):
        """Test that registering an existing device updates it."""
        monitor.register_device("aa:bb:cc:dd:ee:01", "Old Name", "phone", "alice")
        monitor.register_device("aa:bb:cc:dd:ee:01", "New Name", "laptop", "bob")

        device = monitor.known_devices["aa:bb:cc:dd:ee:01"]
        assert device["name"] == "New Name"
        assert device["type"] == "laptop"
        assert device["owner"] == "bob"


# ============================================================================
# Tests for full scan cycle
# ============================================================================

class TestScan:
    """Tests for the complete scan cycle."""

    def test_scan_basic_flow(self, monitor, monkeypatch, monkeypatch_logs):
        """Test basic scan flow with mocked subprocess."""
        # Mock ping sweep
        monkeypatch.setattr("subprocess.Popen", MagicMock())

        # Mock ARP table read
        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-dd-ee-01     dynamic
  192.168.1.50          aa-bb-cc-dd-ee-02     static
        """
        mock_result = MagicMock()
        mock_result.stdout = arp_output

        def mock_run(cmd, *args, **kwargs):
            if cmd[0] == "arp":
                return mock_result
            return MagicMock(stdout="")

        monkeypatch.setattr("subprocess.run", mock_run)

        # Mock time.sleep
        monkeypatch.setattr("time.sleep", MagicMock())

        monitor.known_devices = {
            "aa-bb-cc-dd-ee-01": {"name": "Gateway", "type": "router"}
        }

        result = monitor.scan()

        assert result["devices_found"] == 2
        assert result["known_present"] == 1
        assert result["unknown_present"] == 1
        assert "timestamp" in result
        assert "events" in result

    def test_scan_updates_presence_file(self, monitor, monkeypatch, monkeypatch_logs):
        """Test that scan updates the current presence file."""
        monkeypatch.setattr("subprocess.Popen", MagicMock())

        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.50          aa-bb-cc-dd-ee-02     dynamic
        """
        mock_result = MagicMock()
        mock_result.stdout = arp_output

        def mock_run(cmd, *args, **kwargs):
            if cmd[0] == "arp":
                return mock_result
            return MagicMock(stdout="")

        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("time.sleep", MagicMock())

        monitor.scan()

        current_file = monkeypatch_logs / "presence-current.json"
        assert current_file.exists()
        current_data = json.loads(current_file.read_text())
        assert "aa-bb-cc-dd-ee-02" in current_data

    def test_scan_preserves_first_seen_today(self, monitor, monkeypatch, monkeypatch_logs):
        """Test that first_seen_today persists across scans."""
        monkeypatch.setattr("subprocess.Popen", MagicMock())
        monkeypatch.setattr("time.sleep", MagicMock())

        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.50          aa-bb-cc-dd-ee-02     dynamic
        """
        mock_result = MagicMock()
        mock_result.stdout = arp_output

        def mock_run(cmd, *args, **kwargs):
            if cmd[0] == "arp":
                return mock_result
            return MagicMock(stdout="")

        monkeypatch.setattr("subprocess.run", mock_run)

        monitor.scan()
        first_seen_timestamp = monitor.current_presence["aa-bb-cc-dd-ee-02"]["first_seen_today"]

        # Second scan
        monitor.scan()
        second_seen_timestamp = monitor.current_presence["aa-bb-cc-dd-ee-02"]["first_seen_today"]

        assert second_seen_timestamp == first_seen_timestamp

    def test_scan_limits_event_log_to_1000(self, monitor, monkeypatch, monkeypatch_logs):
        """Test that event log is trimmed to 1000 most recent events."""
        monkeypatch.setattr("subprocess.Popen", MagicMock())
        monkeypatch.setattr("time.sleep", MagicMock())

        # Pre-populate with 1050 events
        monitor.event_log = [{"type": "test", "index": i} for i in range(1050)]

        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.50          aa-bb-cc-dd-ee-02     dynamic
        """
        mock_result = MagicMock()
        mock_result.stdout = arp_output

        def mock_run(cmd, *args, **kwargs):
            if cmd[0] == "arp":
                return mock_result
            return MagicMock(stdout="")

        monkeypatch.setattr("subprocess.run", mock_run)

        monitor.scan()

        log_file = monkeypatch_logs / "presence-log.json"
        loaded_log = json.loads(log_file.read_text())
        assert len(loaded_log) <= 1000


# ============================================================================
# Tests for presence summary
# ============================================================================

class TestGetPresenceSummary:
    """Tests for human-readable presence summary."""

    def test_presence_summary_no_data(self, monitor):
        """Test summary when no presence data is available."""
        summary = monitor.get_presence_summary()
        assert "No presence data available" in summary

    def test_presence_summary_known_devices(self, monitor):
        """Test summary includes known devices."""
        monitor.known_devices = {
            "aa-bb-cc-dd-ee-01": {"name": "Alice's Phone", "type": "phone"}
        }
        monitor.current_presence = {
            "aa-bb-cc-dd-ee-01": {
                "name": "Alice's Phone",
                "mac": "aa-bb-cc-dd-ee-01",
                "ip": "192.168.1.100",
                "type": "phone",
            }
        }

        summary = monitor.get_presence_summary()
        assert "Known devices" in summary
        assert "Alice's Phone" in summary
        assert "192.168.1.100" in summary

    def test_presence_summary_unknown_devices(self, monitor):
        """Test summary includes unknown devices."""
        monitor.current_presence = {
            "xx-yy-zz-aa-bb-cc": {
                "name": "Unknown",
                "mac": "xx-yy-zz-aa-bb-cc",
                "ip": "192.168.1.150",
                "type": "unknown",
                "first_seen_today": "2026-03-28T10:30:45.123456",
            }
        }

        summary = monitor.get_presence_summary()
        assert "Unknown devices" in summary
        assert "192.168.1.150" in summary

    def test_presence_summary_mixed_devices(self, monitor):
        """Test summary with both known and unknown devices."""
        monitor.known_devices = {
            "aa-bb-cc-dd-ee-01": {"name": "Alice's Phone", "type": "phone"}
        }
        monitor.current_presence = {
            "aa-bb-cc-dd-ee-01": {
                "name": "Alice's Phone",
                "mac": "aa-bb-cc-dd-ee-01",
                "ip": "192.168.1.100",
                "type": "phone",
            },
            "xx-yy-zz-aa-bb-cc": {
                "name": "Unknown",
                "mac": "xx-yy-zz-aa-bb-cc",
                "ip": "192.168.1.150",
                "type": "unknown",
                "first_seen_today": "2026-03-28T10:30:45.123456",
            }
        }

        summary = monitor.get_presence_summary()
        assert "Known devices (1)" in summary
        assert "Unknown devices (1)" in summary


# ============================================================================
# Tests for ping sweep
# ============================================================================

class TestPingSweep:
    """Tests for ARP table population via ping sweep."""

    def test_ping_sweep_initiates_pings(self, monitor, monkeypatch):
        """Test that ping sweep initiates pings to common addresses."""
        popen_calls = []

        def mock_popen(*args, **kwargs):
            popen_calls.append(args[0])
            return MagicMock()

        monkeypatch.setattr("subprocess.Popen", mock_popen)
        monkeypatch.setattr("time.sleep", MagicMock())

        monitor._ping_sweep()

        # Should have pings to .1, .2, .20-34, .100-114, and .255
        assert len(popen_calls) > 0
        # Verify some expected pings
        assert any("192.168.1.1" in str(c) for c in popen_calls)
        assert any("192.168.1.100" in str(c) for c in popen_calls)
        assert any("192.168.1.255" in str(c) for c in popen_calls)

    def test_ping_sweep_handles_exception(self, monitor, monkeypatch):
        """Test ping sweep handles exceptions gracefully."""
        def mock_popen_error(*args, **kwargs):
            raise Exception("Popen failed")

        monkeypatch.setattr("subprocess.Popen", mock_popen_error)

        # Should not raise
        monitor._ping_sweep()


# ============================================================================
# Edge cases and integration
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_scan_with_empty_arp_table(self, monitor, monkeypatch, monkeypatch_logs):
        """Test scan handles empty ARP table."""
        monkeypatch.setattr("subprocess.Popen", MagicMock())
        monkeypatch.setattr("time.sleep", MagicMock())

        mock_result = MagicMock()
        mock_result.stdout = ""

        def mock_run(cmd, *args, **kwargs):
            if cmd[0] == "arp":
                return mock_result
            return MagicMock(stdout="")

        monkeypatch.setattr("subprocess.run", mock_run)

        result = monitor.scan()

        assert result["devices_found"] == 0
        assert result["known_present"] == 0

    def test_multiple_device_registrations(self, monitor):
        """Test registering multiple devices."""
        devices = [
            ("aa-bb-cc-dd-ee-01", "Alice Phone", "phone", "alice"),
            ("aa-bb-cc-dd-ee-02", "Bob Laptop", "laptop", "bob"),
            ("aa-bb-cc-dd-ee-03", "Smart Speaker", "iot", "shared"),
        ]

        for mac, name, dtype, owner in devices:
            monitor.register_device(mac, name, dtype, owner)

        assert len(monitor.known_devices) == 3
        assert monitor.known_devices["aa-bb-cc-dd-ee-01"]["name"] == "Alice Phone"
        assert monitor.known_devices["aa-bb-cc-dd-ee-02"]["name"] == "Bob Laptop"
        assert monitor.known_devices["aa-bb-cc-dd-ee-03"]["name"] == "Smart Speaker"

    def test_gateway_ip_handling(self, monitor, monkeypatch):
        """Test that gateway IP is properly handled in detection."""
        # Gateway should be detected and potentially excluded if needed
        # This test verifies the mechanism is in place
        assert mod.GATEWAY is not None
        assert "." in mod.GATEWAY  # Should be a dotted IP

    def test_local_subnet_consistency(self, monitor, monkeypatch):
        """Test that LOCAL_SUBNET is consistent across operations."""
        # Verify subnet format
        assert "." in mod.LOCAL_SUBNET
        parts = mod.LOCAL_SUBNET.split(".")
        assert len(parts) == 3

    @patch("rudy.presence.datetime")
    def test_event_timestamp_format(self, mock_datetime, monitor):
        """Test that event timestamps are in ISO format."""
        mock_now = datetime(2026, 3, 28, 14, 30, 45)
        mock_datetime.now.return_value = mock_now

        discovered = {
            "aa-bb-cc-dd-ee-01": {"ip": "192.168.1.100", "type": "dynamic"}
        }

        events = monitor._detect_changes(discovered)

        assert len(events) == 1
        # Should match ISO format (contains T and Z or offset)
        assert "2026-03-28" in events[0]["time"]

    def test_device_info_structure(self, monitor, monkeypatch):
        """Test the structure of device info in scan results."""
        monkeypatch.setattr("subprocess.Popen", MagicMock())
        monkeypatch.setattr("time.sleep", MagicMock())

        arp_output = """Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.50          aa-bb-cc-dd-ee-02     dynamic
        """
        mock_result = MagicMock()
        mock_result.stdout = arp_output

        def mock_run(cmd, *args, **kwargs):
            if cmd[0] == "arp":
                return mock_result
            return MagicMock(stdout="")

        monkeypatch.setattr("subprocess.run", mock_run)

        monitor.known_devices = {
            "aa-bb-cc-dd-ee-02": {"name": "Test Device", "type": "phone"}
        }

        result = monitor.scan()
        device_info = result["devices"]["aa-bb-cc-dd-ee-02"]

        assert "name" in device_info
        assert "ip" in device_info
        assert "type" in device_info
