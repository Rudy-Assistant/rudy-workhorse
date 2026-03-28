"""
Tests for rudy.travel_mode — NetworkFingerprint, TravelMode.

All subprocess, socket, and network calls are mocked.
Tests verify network fingerprinting, travel/home detection,
baseline archival/restore, and state persistence.
"""
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
(desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)
(desktop / "rudy-logs" / "network-profiles").mkdir(parents=True, exist_ok=True)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def tm_paths(tmp_path, monkeypatch):
    """Redirect all travel_mode file paths to tmp_path."""
    import rudy.travel_mode as mod

    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(mod, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(mod, "TRAVEL_STATE_FILE", tmp_path / "travel-state.json")
    monkeypatch.setattr(mod, "NETWORK_HISTORY_FILE", tmp_path / "network-history.json")
    (tmp_path / "profiles").mkdir(exist_ok=True)
    return tmp_path


def _make_fingerprint(gateway_ip="192.168.7.1", gateway_mac="f8-bb-bf-59-c2-d2",
                       subnet="192.168.7", ssid="HomeNet", local_ip="192.168.7.100",
                       public_ip="1.2.3.4"):
    """Create a pre-populated NetworkFingerprint (no network calls)."""
    from rudy.travel_mode import NetworkFingerprint
    fp = NetworkFingerprint.__new__(NetworkFingerprint)
    fp.gateway_ip = gateway_ip
    fp.gateway_mac = gateway_mac
    fp.subnet = subnet
    fp.ssid = ssid
    fp.dns_servers = ["8.8.8.8"]
    fp.public_ip = public_ip
    fp.local_ip = local_ip
    fp.timestamp = datetime.now().isoformat()
    return fp


# ── NetworkFingerprint ───────────────────────────────────────────

class TestNetworkFingerprint:
    def test_fingerprint_id_deterministic(self):
        fp1 = _make_fingerprint()
        fp2 = _make_fingerprint()
        assert fp1.fingerprint_id == fp2.fingerprint_id

    def test_fingerprint_id_changes_with_gateway(self):
        fp1 = _make_fingerprint(gateway_ip="192.168.7.1")
        fp2 = _make_fingerprint(gateway_ip="10.0.0.1")
        assert fp1.fingerprint_id != fp2.fingerprint_id

    def test_to_dict(self):
        fp = _make_fingerprint()
        d = fp.to_dict()
        assert d["gateway_ip"] == "192.168.7.1"
        assert d["subnet"] == "192.168.7"
        assert d["ssid"] == "HomeNet"
        assert "fingerprint_id" in d

    def test_matches(self):
        fp = _make_fingerprint()
        assert fp.matches(fp.fingerprint_id)
        assert not fp.matches("wrong_id")

    def test_capture_mocked(self):
        """capture() calls all sub-methods without crashing when mocked."""
        from rudy.travel_mode import NetworkFingerprint
        fp = NetworkFingerprint()
        with patch.object(fp, "_get_gateway"), \
             patch.object(fp, "_get_ssid"), \
             patch.object(fp, "_get_dns"), \
             patch.object(fp, "_get_local_ip"), \
             patch.object(fp, "_get_public_ip"):
            result = fp.capture()
        assert result is fp

    def test_get_gateway_parses_output(self):
        from rudy.travel_mode import NetworkFingerprint
        fp = NetworkFingerprint()
        ipconfig_output = """
Windows IP Configuration

Ethernet adapter Ethernet:
   Default Gateway . . . . . . . . . : 192.168.1.1
"""
        arp_output = """
Interface: 192.168.1.100 --- 0x5
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic
"""
        mock_results = [
            MagicMock(stdout=ipconfig_output),
            MagicMock(stdout=arp_output),
        ]
        with patch("rudy.travel_mode.subprocess.run", side_effect=mock_results):
            fp._get_gateway()

        assert fp.gateway_ip == "192.168.1.1"
        assert fp.gateway_mac == "aa-bb-cc-dd-ee-ff"
        assert fp.subnet == "192.168.1"

    def test_get_ssid_parses_output(self):
        from rudy.travel_mode import NetworkFingerprint
        fp = NetworkFingerprint()
        netsh_output = """
    Name                   : Wi-Fi
    SSID                   : MyWiFiNetwork
    BSSID                  : aa:bb:cc:dd:ee:ff
"""
        with patch("rudy.travel_mode.subprocess.run",
                   return_value=MagicMock(stdout=netsh_output)):
            fp._get_ssid()

        assert fp.ssid == "MyWiFiNetwork"

    def test_get_local_ip(self):
        from rudy.travel_mode import NetworkFingerprint
        fp = NetworkFingerprint()
        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("192.168.7.100", 0)

        with patch("rudy.travel_mode.socket.socket", return_value=mock_sock):
            fp._get_local_ip()

        assert fp.local_ip == "192.168.7.100"

    def test_get_public_ip_httpx(self):
        from rudy.travel_mode import NetworkFingerprint
        fp = NetworkFingerprint()
        mock_httpx = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ip": "203.0.113.1"}
        mock_httpx.get.return_value = mock_resp

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            fp._get_public_ip()

        assert fp.public_ip == "203.0.113.1"


# ── TravelMode ───────────────────────────────────────────────────

class TestTravelMode:
    def _make(self, tm_paths):
        from rudy.travel_mode import TravelMode
        return TravelMode()

    def test_init_default_state(self, tm_paths):
        tm = self._make(tm_paths)
        assert tm.state["mode"] == "home"
        assert tm.state["known_networks"] == {}

    def test_get_status(self, tm_paths):
        tm = self._make(tm_paths)
        status = tm.get_status()
        assert "mode" in status
        assert "is_home" in status
        assert "known_networks_count" in status

    def test_get_report(self, tm_paths):
        tm = self._make(tm_paths)
        tm.state["current_network"] = {"ssid": "TestNet", "gateway_ip": "1.2.3.4",
                                        "gateway_mac": "aa:bb:cc", "subnet": "1.2.3",
                                        "local_ip": "1.2.3.100", "public_ip": "5.6.7.8"}
        report = tm.get_report()
        assert "TRAVEL MODE STATUS" in report
        assert "Mode:" in report

    def test_check_network_first_run_home(self, tm_paths):
        """First check on home network should establish home."""
        tm = self._make(tm_paths)
        home_fp = _make_fingerprint()

        with patch("rudy.travel_mode.NetworkFingerprint") as MockFP:
            MockFP.return_value.capture.return_value = home_fp
            result = tm.check_network()

        assert result["action"] == "home_established"
        assert tm.state["mode"] == "home"

    def test_check_network_no_change(self, tm_paths):
        """Same network on consecutive checks → no_change."""
        tm = self._make(tm_paths)
        fp = _make_fingerprint()

        # Establish initial network
        tm.state["current_network_id"] = fp.fingerprint_id
        tm.state["current_network"] = fp.to_dict()

        with patch("rudy.travel_mode.NetworkFingerprint") as MockFP:
            MockFP.return_value.capture.return_value = fp
            result = tm.check_network()

        assert result["action"] == "no_change"

    def test_check_network_travel_activated(self, tm_paths):
        """New unknown network → travel mode activated."""
        tm = self._make(tm_paths)
        home_fp = _make_fingerprint()
        travel_fp = _make_fingerprint(
            gateway_ip="10.0.0.1", gateway_mac="aa-bb-cc-dd-ee-ff",
            subnet="10.0.0", ssid="Hotel-WiFi"
        )

        # Establish home first
        tm.state["current_network_id"] = home_fp.fingerprint_id
        tm.state["current_network"] = home_fp.to_dict()
        tm.state["home_network_id"] = home_fp.fingerprint_id

        with patch("rudy.travel_mode.NetworkFingerprint") as MockFP, \
             patch.object(tm, "_first_contact_scan"):
            MockFP.return_value.capture.return_value = travel_fp
            result = tm.check_network()

        assert result["action"] == "travel_activated"
        assert tm.state["mode"] == "travel"

    def test_check_network_home_restored(self, tm_paths):
        """Returning to known home network → home restored."""
        tm = self._make(tm_paths)
        home_fp = _make_fingerprint()

        # Set state as if we're on a travel network
        tm.state["mode"] = "travel"
        tm.state["current_network_id"] = "travel_net_id"
        tm.state["current_network"] = {"ssid": "Hotel"}
        tm.state["home_network_id"] = home_fp.fingerprint_id
        tm.state["known_networks"] = {
            home_fp.fingerprint_id: {
                "name": "Home",
                "trust_level": "home",
                "visits": 1,
            }
        }

        with patch("rudy.travel_mode.NetworkFingerprint") as MockFP, \
             patch.object(tm, "_archive_baselines"), \
             patch.object(tm, "_restore_baselines"):
            MockFP.return_value.capture.return_value = home_fp
            result = tm.check_network()

        assert result["action"] == "home_restored"
        assert tm.state["mode"] == "home"

    def test_archive_baselines(self, tm_paths):
        """Archive copies baseline files to network profile directory."""
        tm = self._make(tm_paths)

        # Create a fake baseline file
        (tm_paths / "defense-arp-baseline.json").write_text('{"test": true}')

        tm._archive_baselines("test_network_id")

        archive = tm_paths / "profiles" / "test_network_id" / "defense-arp-baseline.json"
        assert archive.exists()
        assert json.loads(archive.read_text()) == {"test": True}

    def test_restore_baselines(self, tm_paths):
        """Restore copies files from archive back to logs dir."""
        tm = self._make(tm_paths)

        # Create archive
        archive_dir = tm_paths / "profiles" / "net123"
        archive_dir.mkdir(parents=True)
        (archive_dir / "defense-arp-baseline.json").write_text('{"restored": true}')

        tm._restore_baselines("net123")

        restored = tm_paths / "defense-arp-baseline.json"
        assert restored.exists()
        assert json.loads(restored.read_text()) == {"restored": True}

    def test_restore_baselines_no_archive(self, tm_paths):
        """Restore with no archive dir should not crash."""
        tm = self._make(tm_paths)
        tm._restore_baselines("nonexistent_network")  # Should not raise

    def test_label_network(self, tm_paths):
        """label_network updates name and trust level."""
        tm = self._make(tm_paths)
        net_id = "abc123"
        tm.state["known_networks"][net_id] = {
            "name": "Unknown", "trust_level": "untrusted"
        }
        tm.state["current_network_id"] = net_id

        tm.label_network(name="Mom's House", trust_level="trusted")

        assert tm.state["known_networks"][net_id]["name"] == "Mom's House"
        assert tm.state["known_networks"][net_id]["trust_level"] == "trusted"

    def test_label_network_current(self, tm_paths):
        """label_network without network_id uses current network."""
        tm = self._make(tm_paths)
        net_id = "current_net"
        tm.state["current_network_id"] = net_id
        tm.state["known_networks"][net_id] = {"name": "?", "trust_level": "untrusted"}

        tm.label_network(name="Airbnb Portland", trust_level="trusted")
        assert tm.state["known_networks"][net_id]["name"] == "Airbnb Portland"

    def test_state_persists(self, tm_paths):
        """State is saved to disk."""
        tm = self._make(tm_paths)
        tm.state["mode"] = "travel"
        tm._save_state()

        from rudy.travel_mode import TRAVEL_STATE_FILE
        with open(TRAVEL_STATE_FILE) as f:
            saved = json.load(f)
        assert saved["mode"] == "travel"

    def test_travel_posture_values(self):
        """Travel posture has expected elevated settings."""
        from rudy.travel_mode import TravelMode
        posture = TravelMode.TRAVEL_POSTURE
        assert posture["scan_interval_minutes"] == 5
        assert posture["alert_on_any_new_device"] is True
        assert posture["block_smb"] is True

    def test_baseline_files_list(self):
        """BASELINE_FILES contains expected files."""
        from rudy.travel_mode import BASELINE_FILES
        assert "defense-arp-baseline.json" in BASELINE_FILES
        assert "presence-current.json" in BASELINE_FILES
        assert len(BASELINE_FILES) > 5


# ── First Contact Scan ───────────────────────────────────────────

class TestFirstContactScan:
    def test_no_subnet_returns_early(self, tm_paths):
        from rudy.travel_mode import TravelMode
        tm = TravelMode()
        fp = _make_fingerprint(subnet=None)
        findings = tm._first_contact_scan(fp)
        assert findings["devices"] == []

    def test_arp_duplicate_threat(self, tm_paths):
        """ARP duplicates (same MAC, multiple IPs) flagged as threat."""
        from rudy.travel_mode import TravelMode
        tm = TravelMode()
        fp = _make_fingerprint(subnet="10.0.0")

        # Mock subprocess to return ARP with duplicate MAC
        arp_output = """
  10.0.0.1           aa-bb-cc-dd-ee-01     dynamic
  10.0.0.50          aa-bb-cc-dd-ee-01     dynamic
  10.0.0.100         11-22-33-44-55-66     dynamic
"""
        def mock_run(*args, **kwargs):
            mock = MagicMock()
            mock.stdout = arp_output
            return mock

        with patch("subprocess.run", side_effect=mock_run), \
             patch("subprocess.Popen"), \
             patch("time.sleep"), \
             patch("socket.socket"):
            findings = tm._first_contact_scan(fp)

        # Should detect arp_duplicate threat
        threats = [t for t in findings["threats"] if t["type"] == "arp_duplicate"]
        assert len(threats) >= 1
