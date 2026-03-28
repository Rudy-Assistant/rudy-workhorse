import pytest
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path
import json
import subprocess
from datetime import datetime, timedelta

import rudy.intruder_profiler as mod


@pytest.fixture
def tmp_logs_dir(tmp_path, monkeypatch):
    """Redirect all log/dossier paths to tmp_path."""
    logs_dir = tmp_path / "rudy-logs"
    dossier_dir = logs_dir / "intruder-dossiers"
    dossier_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(mod, "DOSSIER_DIR", dossier_dir)
    monkeypatch.setattr(mod, "INTRUDER_DB", logs_dir / "intruder-database.json")
    monkeypatch.setattr(mod, "CLEARED_DEVICES", logs_dir / "cleared-devices.json")
    monkeypatch.setattr(mod, "THREAT_TIMELINE", logs_dir / "threat-timeline.json")

    return logs_dir


@pytest.fixture
def profiler(tmp_logs_dir):
    """Create a fresh IntruderProfiler instance."""
    return mod.IntruderProfiler()


class TestIntruderProfilerInit:
    """Test initialization and JSON loading."""

    def test_init_creates_empty_dbs(self, profiler):
        assert profiler.database == {"devices": {}, "stats": {}}
        assert profiler.cleared == {}
        assert profiler.timeline == []

    def test_init_loads_existing_database(self, tmp_logs_dir):
        db_path = tmp_logs_dir / "intruder-database.json"
        db_path.write_text(json.dumps({
            "devices": {"aa:bb:cc:dd:ee:ff": {"mac": "aa:bb:cc:dd:ee:ff"}},
            "stats": {"last_scan": "2026-03-28T10:00:00"}
        }))

        profiler = mod.IntruderProfiler()
        assert "aa:bb:cc:dd:ee:ff" in profiler.database["devices"]
        assert profiler.database["stats"]["last_scan"] == "2026-03-28T10:00:00"

    def test_init_loads_cleared_devices(self, tmp_logs_dir):
        cleared_path = tmp_logs_dir / "cleared-devices.json"
        cleared_path.write_text(json.dumps({
            "11:22:33:44:55:66": {"cleared_at": "2026-03-27T12:00:00"}
        }))

        profiler = mod.IntruderProfiler()
        assert "11:22:33:44:55:66" in profiler.cleared

    def test_init_handles_corrupt_json(self, tmp_logs_dir):
        db_path = tmp_logs_dir / "intruder-database.json"
        db_path.write_text("{ invalid json }")

        profiler = mod.IntruderProfiler()
        assert profiler.database == {"devices": {}, "stats": {}}


class TestNewDossier:
    """Test dossier creation."""

    def test_new_dossier_structure(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")

        assert dossier["mac"] == "aa:bb:cc:dd:ee:ff"
        assert dossier["current_ip"] == "192.168.7.50"
        assert dossier["total_sightings"] == 0
        assert dossier["departures"] == 0
        assert dossier["sightings"] == []
        assert dossier["threat_score"] == 0
        assert dossier["status"] == "uncleared"
        assert dossier["label"] == "Unknown"
        assert dossier["currently_present"] is True
        assert dossier["threat_factors"] == []
        assert dossier["correlated_unknowns"] == []


class TestDeepProfile:
    """Test device profiling (MAC, IP, hostname, ports, TTL)."""

    def test_mac_randomized_detection(self, profiler):
        # MAC with randomized bit (bit 1 of first octet set)
        dossier = profiler._new_dossier("02:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["mac_randomized"] is True
        assert dossier["profile"]["oui"] == "randomized"

    def test_mac_not_randomized(self, profiler):
        # MAC without randomized bit
        dossier = profiler._new_dossier("00:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["mac_randomized"] is False
        assert dossier["profile"]["oui"] == "00:bb:cc"

    def test_ip_analysis_in_dhcp_range(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["ip_last_octet"] == 50
        assert dossier["profile"]["ip_in_dhcp_range"] is True

    def test_ip_analysis_outside_dhcp_range(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.10")
        dossier = profiler._deep_profile(dossier, "192.168.7.10")

        assert dossier["profile"]["ip_last_octet"] == 10
        assert dossier["profile"]["ip_in_dhcp_range"] is False

    @patch('subprocess.run')
    def test_hostname_via_nbtstat(self, mock_run, profiler):
        mock_run.return_value = MagicMock(
            stdout="MYDEVICE        <00> UNIQUE\nOther line\n",
            returncode=0
        )

        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["hostname"] == "MYDEVICE"
        assert dossier["label"] == "MYDEVICE"

    @patch('subprocess.run')
    def test_hostname_via_nslookup_fallback(self, mock_run, profiler):
        # First call (nbtstat) fails, second call (nslookup) succeeds
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="Name: laptop.local\nAddress: 192.168.7.50")
        ]

        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["hostname"] == "laptop.local"

    @patch('subprocess.run')
    def test_hostname_resolution_timeout(self, mock_run, profiler):
        mock_run.side_effect = subprocess.TimeoutExpired("nbtstat", 5)

        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["hostname"] is None
        assert "Unknown (192.168.7.50)" in dossier["label"]

    @patch('socket.socket')
    def test_port_scanning(self, mock_socket_class, profiler):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock

        # Simulate ports 80 and 443 open (return 0), others closed (return 1)
        mock_sock.connect_ex.side_effect = [0, 0, 1, 1, 1, 1, 1, 1]

        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert set(dossier["profile"]["open_ports"]) == {80, 443}

    @patch('socket.socket')
    def test_port_scanning_timeout(self, mock_socket_class, profiler):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        mock_sock.connect_ex.side_effect = OSError("Connection timeout")

        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        # Should handle gracefully
        assert "open_ports" in dossier["profile"]

    @patch('subprocess.run')
    def test_ttl_fingerprinting_linux(self, mock_run, profiler):
        mock_run.return_value = MagicMock(
            stdout="Pinging 192.168.7.50 with 32 bytes of data:\nTTL=64 time=5ms\n",
            returncode=0
        )

        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["ttl"] == 64
        assert dossier["profile"]["os_family"] == "Linux/Android/iOS"

    @patch('subprocess.run')
    def test_ttl_fingerprinting_windows(self, mock_run, profiler):
        mock_run.return_value = MagicMock(
            stdout="Pinging 192.168.7.50 with 32 bytes of data:\nTTL=128 time=2ms\n",
            returncode=0
        )

        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["ttl"] == 128
        assert dossier["profile"]["os_family"] == "Windows"

    @patch('subprocess.run')
    def test_ttl_fingerprinting_unknown(self, mock_run, profiler):
        mock_run.return_value = MagicMock(
            stdout="Pinging 192.168.7.50 with 32 bytes of data:\nTTL=255 time=1ms\n",
            returncode=0
        )

        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier = profiler._deep_profile(dossier, "192.168.7.50")

        assert dossier["profile"]["ttl"] == 255
        assert dossier["profile"]["os_family"] == "Unknown"


class TestThreatScoring:
    """Test threat score computation."""

    def test_score_randomized_mac(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {"mac_randomized": True}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 1

        score = profiler._compute_threat_score(dossier, is_night=False)

        assert score >= mod.THREAT_WEIGHTS["randomized_mac"]
        assert "randomized_mac" in dossier["threat_factors"]

    def test_score_first_appearance(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 1

        score = profiler._compute_threat_score(dossier, is_night=False)

        assert score >= mod.THREAT_WEIGHTS["first_appearance"]
        assert "first_seen" in dossier["threat_factors"]

    def test_score_nighttime_appearance(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {}
        dossier["sightings"] = [{"nighttime": True}]
        dossier["total_sightings"] = 1

        profiler._compute_threat_score(dossier, is_night=False)

        assert "nighttime" in dossier["threat_factors"]

    def test_score_no_hostname(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {"hostname": None}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 1

        profiler._compute_threat_score(dossier, is_night=False)

        assert "no_hostname" in dossier["threat_factors"]

    def test_score_open_ports(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {"open_ports": [80, 443, 22]}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 1

        profiler._compute_threat_score(dossier, is_night=False)

        # The factor is stored with a prefix like "open_ports:[80, 443, 22]"
        assert any("open_ports" in f for f in dossier["threat_factors"])

    def test_score_outside_dhcp_range(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.10")
        dossier["profile"] = {"ip_in_dhcp_range": False}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 1

        profiler._compute_threat_score(dossier, is_night=False)

        assert "outside_dhcp" in dossier["threat_factors"]

    def test_score_correlated_with_unknowns(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 1
        dossier["correlated_unknowns"] = ["bb:cc:dd:ee:ff:00", "cc:dd:ee:ff:00:11"]

        profiler._compute_threat_score(dossier, is_night=False)

        assert "correlated" in " ".join(dossier["threat_factors"])

    def test_score_recurrent_unknown_reduces_score(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 10

        score = profiler._compute_threat_score(dossier, is_night=False)

        assert "recurrent" in dossier["threat_factors"]
        # Score should be reduced due to negative weight
        assert score < 20

    def test_score_brief_visit(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 1
        dossier["last_visit_duration_min"] = 15
        dossier["departures"] = 1

        profiler._compute_threat_score(dossier, is_night=False)

        assert "brief_visit" in dossier["threat_factors"]

    def test_score_never_negative(self, profiler):
        dossier = profiler._new_dossier("aa:bb:cc:dd:ee:ff", "192.168.7.50")
        dossier["profile"] = {}
        dossier["sightings"] = [{"nighttime": False}]
        dossier["total_sightings"] = 50  # Many sightings => negative weight
        dossier["last_visit_duration_min"] = 500
        dossier["departures"] = 10

        score = profiler._compute_threat_score(dossier, is_night=False)

        assert score >= 0


class TestProcessScan:
    """Test the main scan processing pipeline."""

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_known_device(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="")
        ]

        current = {
            "aa:bb:cc:dd:ee:ff": {"ip": "192.168.7.50", "last_seen": "now"}
        }
        known = {
            "aa:bb:cc:dd:ee:ff": {"name": "Laptop", "owner": "Chris"}
        }

        result = profiler.process_scan(current, known)

        assert result["known"] == 1
        assert result["unknown"] == 0
        assert result["new_intruders"] == []

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_cleared_device(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="")
        ]

        profiler.cleared["aa:bb:cc:dd:ee:ff"] = {
            "cleared_at": "2026-03-27T12:00:00",
            "reason": "Family iPad"
        }

        current = {
            "aa:bb:cc:dd:ee:ff": {"ip": "192.168.7.50", "last_seen": "now"}
        }
        known = {}

        result = profiler.process_scan(current, known)

        assert result["cleared"] == 1
        assert result["unknown"] == 0

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_new_intruder(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="UNKNOWN        <00> UNIQUE\n", returncode=0),
            MagicMock(stdout="Pinging 192.168.7.50\nTTL=64\n", returncode=0)
        ]

        current = {
            "aa:bb:cc:dd:ee:ff": {"ip": "192.168.7.50", "last_seen": "now"}
        }
        known = {}

        result = profiler.process_scan(current, known)

        assert result["unknown"] == 1
        assert len(result["new_intruders"]) == 1
        assert result["new_intruders"][0]["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result["new_intruders"][0]["ip"] == "192.168.7.50"

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_existing_intruder_repeated_sighting(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        # Pre-populate with existing dossier
        mac = "aa:bb:cc:dd:ee:ff"
        profiler.database["devices"][mac] = profiler._new_dossier(mac, "192.168.7.50")
        profiler.database["devices"][mac]["total_sightings"] = 3
        profiler.database["devices"][mac]["sightings"] = [
            {"time": "2026-03-28T08:00:00", "ip": "192.168.7.50"}
        ]

        current = {mac: {"ip": "192.168.7.50", "last_seen": "now"}}
        known = {}

        result = profiler.process_scan(current, known)

        assert result["unknown"] == 1
        assert result["new_intruders"] == []  # Not new
        assert profiler.database["devices"][mac]["total_sightings"] == 4

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_tracks_departures(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        # Pre-populate with device that was present
        mac = "aa:bb:cc:dd:ee:ff"
        profiler.database["devices"][mac] = profiler._new_dossier(mac, "192.168.7.50")
        profiler.database["devices"][mac]["currently_present"] = True
        profiler.database["devices"][mac]["last_seen"] = (
            datetime.now() - timedelta(minutes=30)
        ).isoformat()
        profiler.database["devices"][mac]["total_sightings"] = 5

        current = {}  # Device is no longer present
        known = {}

        profiler.process_scan(current, known)

        assert profiler.database["devices"][mac]["currently_present"] is False
        assert profiler.database["devices"][mac]["departures"] >= 1

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_correlates_unknowns(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 16
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="TTL=64\n", returncode=0),
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        current = {
            "aa:bb:cc:dd:ee:ff": {"ip": "192.168.7.50"},
            "bb:cc:dd:ee:ff:00": {"ip": "192.168.7.51"}
        }
        known = {}

        result = profiler.process_scan(current, known)

        assert result["unknown"] == 2
        # Both devices should have each other in correlated_unknowns
        mac1_dossier = profiler.database["devices"]["aa:bb:cc:dd:ee:ff"]
        mac2_dossier = profiler.database["devices"]["bb:cc:dd:ee:ff:00"]
        assert "bb:cc:dd:ee:ff:00" in mac1_dossier["correlated_unknowns"]
        assert "aa:bb:cc:dd:ee:ff" in mac2_dossier["correlated_unknowns"]

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_threat_levels(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [0] * 8
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="TTL=255\n", returncode=0)
        ]

        # Create a high-threat device (many factors)
        current = {
            "02:bb:cc:dd:ee:ff": {"ip": "192.168.7.5"}  # Outside DHCP + randomized
        }
        known = {}

        result = profiler.process_scan(current, known)

        dossier = profiler.database["devices"]["02:bb:cc:dd:ee:ff"]
        if dossier["threat_score"] >= 15:
            assert len(result["active_threats"]) > 0

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_threat_level_colors(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        current = {}
        known = {}

        result = profiler.process_scan(current, known)

        assert result["threat_level"] in ["green", "yellow", "orange", "red"]

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_timeline_recorded(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="NEWDEVICE      <00> UNIQUE\n", returncode=0),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        current = {
            "aa:bb:cc:dd:ee:ff": {"ip": "192.168.7.50"}
        }
        known = {}

        profiler.process_scan(current, known)

        timeline_entries = [e for e in profiler.timeline if e.get("event") == "new_intruder"]
        assert len(timeline_entries) > 0
        assert timeline_entries[0]["mac"] == "aa:bb:cc:dd:ee:ff"


class TestClearDevice:
    """Test device clearance workflow."""

    def test_clear_device_updates_cleared_db(self, profiler):
        mac = "aa:bb:cc:dd:ee:ff"
        profiler.clear_device(mac, "Family iPad", "Chris")

        assert mac in profiler.cleared
        assert profiler.cleared[mac]["reason"] == "Family iPad"
        assert profiler.cleared[mac]["cleared_by"] == "Chris"

    def test_clear_device_updates_device_status(self, profiler):
        mac = "aa:bb:cc:dd:ee:ff"
        profiler.database["devices"][mac] = profiler._new_dossier(mac, "192.168.7.50")

        profiler.clear_device(mac, "Visitor laptop", "John")

        assert profiler.database["devices"][mac]["status"] == "cleared"
        assert any("Cleared by John" in note for note in profiler.database["devices"][mac]["notes"])

    def test_clear_device_preserves_dossier(self, profiler):
        mac = "aa:bb:cc:dd:ee:ff"
        profiler.database["devices"][mac] = profiler._new_dossier(mac, "192.168.7.50")
        profiler.database["devices"][mac]["threat_score"] = 20

        profiler.clear_device(mac, "Approved", "Chris")

        # Dossier should still exist
        assert mac in profiler.database["devices"]
        assert profiler.database["devices"][mac]["threat_score"] == 20

    def test_clear_device_normalizes_mac(self, profiler):
        mac_upper = "AA:BB:CC:DD:EE:FF"
        profiler.clear_device(mac_upper, "Test", "Chris")

        mac_lower = "aa:bb:cc:dd:ee:ff"
        assert mac_lower in profiler.cleared


class TestWriteDossierFile:
    """Test individual dossier file writing."""

    def test_write_dossier_file_creates_json(self, profiler, tmp_logs_dir):
        mac = "aa:bb:cc:dd:ee:ff"
        dossier = profiler._new_dossier(mac, "192.168.7.50")
        dossier["threat_score"] = 15

        profiler._write_dossier_file(mac, dossier)

        filepath = tmp_logs_dir / "intruder-dossiers" / "dossier-aa-bb-cc-dd-ee-ff.json"
        assert filepath.exists()

        with open(filepath) as f:
            saved = json.load(f)

        assert saved["mac"] == mac
        assert saved["threat_score"] == 15

    def test_write_dossier_file_sanitizes_mac(self, profiler, tmp_logs_dir):
        mac = "aa:bb:cc:dd:ee:ff"
        dossier = profiler._new_dossier(mac, "192.168.7.50")

        profiler._write_dossier_file(mac, dossier)

        filepath = tmp_logs_dir / "intruder-dossiers" / "dossier-aa-bb-cc-dd-ee-ff.json"
        assert filepath.exists()


class TestThreatSummary:
    """Test threat summary generation."""

    def test_threat_summary_includes_header(self, profiler):
        summary = profiler.get_threat_summary()

        assert "COUNTER-INTELLIGENCE THREAT BOARD" in summary
        assert "=" * 55 in summary

    def test_threat_summary_counts_devices(self, profiler):
        mac1 = "aa:bb:cc:dd:ee:ff"
        mac2 = "bb:cc:dd:ee:ff:00"

        profiler.database["devices"][mac1] = profiler._new_dossier(mac1, "192.168.7.50")
        profiler.database["devices"][mac1]["currently_present"] = True

        profiler.database["devices"][mac2] = profiler._new_dossier(mac2, "192.168.7.51")
        profiler.database["devices"][mac2]["currently_present"] = False

        profiler.cleared["cc:dd:ee:ff:00:11"] = {"reason": "Test"}

        summary = profiler.get_threat_summary()

        assert "Tracked unknowns: 2" in summary
        assert "Currently present: 1" in summary
        assert "Historical: 1" in summary
        assert "Cleared: 1" in summary

    def test_threat_summary_lists_active_unknowns(self, profiler):
        mac = "aa:bb:cc:dd:ee:ff"
        dossier = profiler._new_dossier(mac, "192.168.7.50")
        dossier["currently_present"] = True
        dossier["threat_score"] = 20
        dossier["label"] = "Suspicious Device"
        dossier["threat_factors"] = ["randomized_mac", "first_seen"]
        dossier["total_sightings"] = 5
        dossier["first_seen"] = "2026-03-28T10:00:00"

        profiler.database["devices"][mac] = dossier

        summary = profiler.get_threat_summary()

        assert "ACTIVE UNKNOWNS:" in summary
        assert "Suspicious Device" in summary
        assert "192.168.7.50" in summary

    def test_threat_summary_recent_timeline(self, profiler):
        profiler.timeline.append({
            "time": "2026-03-28T10:30:00",
            "event": "new_intruder",
            "mac": "aa:bb:cc:dd:ee:ff"
        })

        summary = profiler.get_threat_summary()

        assert "RECENT EVENTS:" in summary
        assert "new_intruder" in summary


class TestSaveLoadJson:
    """Test JSON persistence."""

    def test_save_json_writes_file(self, profiler, tmp_logs_dir):
        data = {"test": "value", "number": 42}
        filepath = tmp_logs_dir / "test.json"

        profiler._save_json(filepath, data)

        assert filepath.exists()
        with open(filepath) as f:
            loaded = json.load(f)
        assert loaded["test"] == "value"
        assert loaded["number"] == 42

    def test_save_json_handles_datetime_objects(self, profiler, tmp_logs_dir):
        now = datetime.now()
        data = {"timestamp": now}
        filepath = tmp_logs_dir / "test.json"

        profiler._save_json(filepath, data)

        with open(filepath) as f:
            content = f.read()

        # Should be readable JSON (datetime converted to string)
        loaded = json.loads(content)
        assert "timestamp" in loaded

    def test_load_json_returns_existing_data(self, profiler, tmp_logs_dir):
        filepath = tmp_logs_dir / "test.json"
        original = {"key": "value"}
        filepath.write_text(json.dumps(original))

        loaded = profiler._load_json(filepath, {})

        assert loaded["key"] == "value"

    def test_load_json_returns_default_on_missing(self, profiler, tmp_logs_dir):
        filepath = tmp_logs_dir / "nonexistent.json"

        loaded = profiler._load_json(filepath, {"default": "data"})

        assert loaded["default"] == "data"


class TestEdgeCases:
    """Test edge cases and error handling."""

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_empty_devices(self, mock_socket, mock_run, profiler):
        result = profiler.process_scan({}, {})

        assert result["total_devices"] == 0
        assert result["known"] == 0
        assert result["unknown"] == 0
        assert result["threat_level"] == "green"

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_caps_sightings_list(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        mac = "aa:bb:cc:dd:ee:ff"
        dossier = profiler._new_dossier(mac, "192.168.7.50")
        # Create many sightings
        dossier["sightings"] = [
            {"time": f"2026-03-28T{i:02d}:00:00", "ip": "192.168.7.50"}
            for i in range(600)
        ]
        dossier["total_sightings"] = 600
        profiler.database["devices"][mac] = dossier

        current = {mac: {"ip": "192.168.7.50"}}
        known = {}

        profiler.process_scan(current, known)

        # Should cap at 500
        assert len(profiler.database["devices"][mac]["sightings"]) == 500

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_process_scan_caps_timeline(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        # Populate timeline with many entries
        profiler.timeline = [
            {"time": f"2026-03-28T{i:02d}:00:00", "event": "test"}
            for i in range(2500)
        ]

        current = {"aa:bb:cc:dd:ee:ff": {"ip": "192.168.7.50"}}
        known = {}

        profiler.process_scan(current, known)

        # Should cap at 2000
        assert len(profiler.timeline) == 2000

    def test_process_scan_handles_malformed_iso_timestamp(self, profiler):
        mac = "aa:bb:cc:dd:ee:ff"
        dossier = profiler._new_dossier(mac, "192.168.7.50")
        dossier["currently_present"] = True
        dossier["last_seen"] = "invalid-timestamp"
        profiler.database["devices"][mac] = dossier

        # Should not crash
        result = profiler.process_scan({}, {})

        assert result["threat_level"] == "green"


class TestIntegration:
    """Integration tests combining multiple components."""

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_full_workflow(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 8
        mock_run.side_effect = [
            MagicMock(stdout="UNKNOWN        <00> UNIQUE\n", returncode=0),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        # First scan: detect intruder
        current_1 = {"aa:bb:cc:dd:ee:ff": {"ip": "192.168.7.50"}}
        known = {}

        result_1 = profiler.process_scan(current_1, known)

        assert len(result_1["new_intruders"]) == 1
        assert "aa:bb:cc:dd:ee:ff" in profiler.database["devices"]

        # Clear the device
        profiler.clear_device("aa:bb:cc:dd:ee:ff", "Family device", "Chris")

        # Second scan: device is cleared
        mock_run.side_effect = [
            MagicMock(stdout="UNKNOWN        <00> UNIQUE\n", returncode=0),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]
        mock_socket.return_value.connect_ex.side_effect = [1] * 8

        result_2 = profiler.process_scan(current_1, known)

        assert result_2["cleared"] == 1
        assert result_2["unknown"] == 0

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_multiple_unknowns_tracked_independently(self, mock_socket, mock_run, profiler):
        mock_socket.return_value.connect_ex.side_effect = [1] * 16
        mock_run.side_effect = [
            MagicMock(stdout="DEV1           <00> UNIQUE\n", returncode=0),
            MagicMock(stdout="TTL=64\n", returncode=0),
            MagicMock(stdout="DEV2           <00> UNIQUE\n", returncode=0),
            MagicMock(stdout="TTL=64\n", returncode=0)
        ]

        current = {
            "aa:bb:cc:dd:ee:ff": {"ip": "192.168.7.50"},
            "bb:cc:dd:ee:ff:00": {"ip": "192.168.7.51"}
        }
        known = {}

        result = profiler.process_scan(current, known)

        assert len(result["new_intruders"]) == 2

        # Each should have independent dossier
        d1 = profiler.database["devices"]["aa:bb:cc:dd:ee:ff"]
        d2 = profiler.database["devices"]["bb:cc:dd:ee:ff:00"]

        assert d1["label"] == "DEV1"
        assert d2["label"] == "DEV2"
        assert d1["mac"] != d2["mac"]
