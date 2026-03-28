"""
Tests for rudy.network_defense — NetworkDefense class.

All subprocess and socket calls are mocked; these tests verify
detection logic, baseline management, and alert generation without
requiring a real network or Windows environment.
"""
import json
import os
import re
import socket
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure test directories exist before import
desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
(desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────

def _make_arp_output(entries: list[tuple[str, str]], subnet="192.168.7") -> str:
    """Build fake `arp -a` output.

    entries: list of (ip_suffix, mac) e.g. [("1", "aa-bb-cc-dd-ee-01")]
    """
    lines = [
        "",
        f"Interface: {subnet}.100 --- 0x5",
        "  Internet Address      Physical Address      Type",
    ]
    for suffix, mac in entries:
        ip = f"{subnet}.{suffix}" if "." not in suffix else suffix
        lines.append(f"  {ip:<22}{mac:<22}dynamic")
    return "\n".join(lines)


def _make_netstat_output(ports: list[tuple[int, int]]) -> str:
    """Build fake `netstat -ano -p TCP` output.

    ports: list of (port, pid)
    """
    lines = [
        "",
        "Active Connections",
        "",
        "  Proto  Local Address          Foreign Address        State           PID",
    ]
    for port, pid in ports:
        lines.append(
            f"  TCP    0.0.0.0:{port:<15}0.0.0.0:0              LISTENING       {pid}"
        )
    return "\n".join(lines)


def _subprocess_result(stdout="", returncode=0):
    """Create a mock subprocess.CompletedProcess."""
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def nd(tmp_path, monkeypatch):
    """Create a NetworkDefense instance with temp paths."""
    import rudy.network_defense as mod

    monkeypatch.setattr(mod, "ARP_BASELINE_FILE", tmp_path / "arp.json")
    monkeypatch.setattr(mod, "DNS_BASELINE_FILE", tmp_path / "dns.json")
    monkeypatch.setattr(mod, "TRAFFIC_BASELINE_FILE", tmp_path / "traffic.json")
    monkeypatch.setattr(mod, "DEFENSE_ALERTS_FILE", tmp_path / "alerts.json")
    monkeypatch.setattr(mod, "DEFENSE_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(mod, "SUBNET", "192.168.7")
    monkeypatch.setattr(mod, "GATEWAY_IP", "192.168.7.1")

    return mod.NetworkDefense()


# ── Initialization Tests ─────────────────────────────────────────

class TestInit:
    def test_fresh_init_empty_state(self, nd):
        """Fresh init with no files should produce empty baselines."""
        assert nd.arp_baseline == {}
        assert nd.dns_baseline == {}
        assert nd.traffic_baseline == {}
        assert nd.alerts == []
        assert nd.new_alerts == []

    def test_loads_existing_baseline(self, tmp_path, monkeypatch):
        """Should load saved baselines from disk."""
        import rudy.network_defense as mod

        arp_file = tmp_path / "arp.json"
        arp_file.write_text(json.dumps({"gateway_mac": "aa-bb-cc-dd-ee-ff"}))

        monkeypatch.setattr(mod, "ARP_BASELINE_FILE", arp_file)
        monkeypatch.setattr(mod, "DNS_BASELINE_FILE", tmp_path / "dns.json")
        monkeypatch.setattr(mod, "TRAFFIC_BASELINE_FILE", tmp_path / "traffic.json")
        monkeypatch.setattr(mod, "DEFENSE_ALERTS_FILE", tmp_path / "alerts.json")
        monkeypatch.setattr(mod, "DEFENSE_STATE_FILE", tmp_path / "state.json")

        nd = mod.NetworkDefense()
        assert nd.arp_baseline["gateway_mac"] == "aa-bb-cc-dd-ee-ff"

    def test_corrupt_json_uses_default(self, tmp_path, monkeypatch):
        """Corrupt JSON files should fall back to defaults."""
        import rudy.network_defense as mod

        bad_file = tmp_path / "arp.json"
        bad_file.write_text("{this is not valid json")

        monkeypatch.setattr(mod, "ARP_BASELINE_FILE", bad_file)
        monkeypatch.setattr(mod, "DNS_BASELINE_FILE", tmp_path / "dns.json")
        monkeypatch.setattr(mod, "TRAFFIC_BASELINE_FILE", tmp_path / "traffic.json")
        monkeypatch.setattr(mod, "DEFENSE_ALERTS_FILE", tmp_path / "alerts.json")
        monkeypatch.setattr(mod, "DEFENSE_STATE_FILE", tmp_path / "state.json")

        nd = mod.NetworkDefense()
        assert nd.arp_baseline == {}


# ── Alert System Tests ────────────────────────────────────────────

class TestAlerts:
    def test_alert_records_correctly(self, nd):
        """_alert should add to both new_alerts and alerts."""
        nd._alert("test_cat", "warning", "test message", {"key": "val"})
        assert len(nd.new_alerts) == 1
        assert len(nd.alerts) == 1
        alert = nd.new_alerts[0]
        assert alert["category"] == "test_cat"
        assert alert["severity"] == "warning"
        assert alert["message"] == "test message"
        assert alert["details"] == {"key": "val"}
        assert "time" in alert

    def test_multiple_alerts_accumulate(self, nd):
        """Multiple alerts should accumulate in order."""
        nd._alert("a", "info", "first")
        nd._alert("b", "critical", "second")
        assert len(nd.new_alerts) == 2
        assert nd.new_alerts[0]["message"] == "first"
        assert nd.new_alerts[1]["message"] == "second"

    def test_alert_defaults_empty_details(self, nd):
        """Details should default to empty dict."""
        nd._alert("cat", "info", "msg")
        assert nd.alerts[0]["details"] == {}


# ── ARP Integrity Tests ──────────────────────────────────────────

class TestARPIntegrity:
    @patch("rudy.network_defense.subprocess.run")
    def test_records_gateway_mac_first_time(self, mock_run, nd):
        """First run should record gateway MAC without critical alert."""
        mock_run.return_value = _subprocess_result(
            _make_arp_output([("1", "aa-bb-cc-dd-ee-01"), ("100", "11-22-33-44-55-66")])
        )
        result = nd.check_arp_integrity()
        assert result["status"] == "ok"
        assert nd.arp_baseline["gateway_mac"] == "aa-bb-cc-dd-ee-01"
        # Should have an info alert about recording, not a critical
        assert any(a["severity"] == "info" for a in nd.new_alerts)
        assert not any(a["severity"] == "critical" for a in nd.new_alerts)

    @patch("rudy.network_defense.subprocess.run")
    def test_detects_gateway_mac_change(self, mock_run, nd):
        """Changed gateway MAC should trigger critical alert."""
        nd.arp_baseline["gateway_mac"] = "aa-bb-cc-dd-ee-01"

        mock_run.return_value = _subprocess_result(
            _make_arp_output([("1", "ff-ff-00-00-00-01")])
        )
        result = nd.check_arp_integrity()
        assert result["status"] == "critical"
        assert any(
            a["severity"] == "critical" and "GATEWAY MAC CHANGED" in a["message"]
            for a in nd.new_alerts
        )

    @patch("rudy.network_defense.subprocess.run")
    def test_stable_gateway_no_alert(self, mock_run, nd):
        """Unchanged gateway MAC should not generate alerts."""
        nd.arp_baseline["gateway_mac"] = "aa-bb-cc-dd-ee-01"

        mock_run.return_value = _subprocess_result(
            _make_arp_output([("1", "aa-bb-cc-dd-ee-01")])
        )
        result = nd.check_arp_integrity()
        assert result["status"] == "ok"
        assert not any(a["severity"] == "critical" for a in nd.new_alerts)

    @patch("rudy.network_defense.subprocess.run")
    def test_detects_duplicate_macs(self, mock_run, nd):
        """Same MAC on multiple IPs should trigger ARP poisoning alert."""
        mock_run.return_value = _subprocess_result(
            _make_arp_output([
                ("10", "aa-bb-cc-dd-ee-99"),
                ("20", "aa-bb-cc-dd-ee-99"),
            ])
        )
        result = nd.check_arp_integrity()
        assert result["status"] == "alert"
        assert any("arp_duplicate" in a["category"] for a in nd.new_alerts)

    @patch("rudy.network_defense.subprocess.run")
    def test_detects_known_device_mac_change(self, mock_run, nd):
        """MAC change on known device should trigger warning."""
        nd.arp_baseline["known_mappings"] = {"192.168.7.50": "aa-00-00-00-00-01"}

        mock_run.return_value = _subprocess_result(
            _make_arp_output([("50", "bb-11-11-11-11-02")])
        )
        nd.check_arp_integrity()
        assert any(
            a["category"] == "arp_change" and a["severity"] == "warning"
            for a in nd.new_alerts
        )

    @patch("rudy.network_defense.subprocess.run")
    def test_saves_arp_baseline(self, mock_run, nd, tmp_path):
        """After check, baseline should be saved to disk."""
        import rudy.network_defense as mod

        mock_run.return_value = _subprocess_result(
            _make_arp_output([("1", "aa-bb-cc-dd-ee-01")])
        )
        nd.check_arp_integrity()

        saved = json.loads(mod.ARP_BASELINE_FILE.read_text())
        assert "known_mappings" in saved
        assert "last_check" in saved

    @patch("rudy.network_defense.subprocess.run")
    def test_ignores_broadcast_macs(self, mock_run, nd):
        """Broadcast/multicast MACs should be filtered out."""
        mock_run.return_value = _subprocess_result(
            _make_arp_output([("1", "aa-bb-cc-dd-ee-01")]) +
            "\n  192.168.7.255         ff-ff-ff-ff-ff-ff     static\n" +
            "\n  192.168.7.200         01-00-5e-00-00-16     static\n"
        )
        result = nd.check_arp_integrity()
        # Only the non-broadcast entry should be tracked
        assert result["device_count"] == 1

    @patch("rudy.network_defense.subprocess.run")
    def test_handles_subprocess_error(self, mock_run, nd):
        """Subprocess failure should return error status, not crash."""
        mock_run.side_effect = Exception("Command failed")
        result = nd.check_arp_integrity()
        assert result["status"] == "error"


# ── DNS Integrity Tests ──────────────────────────────────────────

class TestDNSIntegrity:
    @patch("rudy.network_defense.subprocess.run")
    @patch("rudy.network_defense.socket.getaddrinfo")
    def test_clean_dns_no_alert(self, mock_getaddr, mock_run, nd):
        """Matching local and trusted DNS should be clean."""
        # Local resolver returns public IP
        mock_getaddr.return_value = [
            (2, 1, 6, '', ('142.250.80.46', 0)),
        ]
        # Trusted resolver returns same
        mock_run.return_value = _subprocess_result(
            "Server:  dns.google\nAddress:  8.8.8.8\n\n"
            "Non-authoritative answer:\nAddress:  142.250.80.46\n"
        )
        nd.check_dns_integrity()
        assert not any(a["severity"] == "critical" for a in nd.new_alerts)

    @patch("rudy.network_defense.subprocess.run")
    @patch("rudy.network_defense.socket.getaddrinfo")
    def test_detects_private_ip_hijack(self, mock_getaddr, mock_run, nd):
        """Local resolution to private IP should trigger critical alert."""
        # Local resolver returns private IP (hijack!)
        mock_getaddr.return_value = [
            (2, 1, 6, '', ('192.168.1.1', 0)),
        ]
        # Trusted resolver returns public IP
        mock_run.return_value = _subprocess_result(
            "Server:  dns.google\nAddress:  8.8.8.8\n\n"
            "Non-authoritative answer:\nAddress:  142.250.80.46\n"
        )
        result = nd.check_dns_integrity()
        assert result["status"] == "critical"
        assert any(
            a["category"] == "dns_hijack" and a["severity"] == "critical"
            for a in nd.new_alerts
        )

    @patch("rudy.network_defense.subprocess.run")
    @patch("rudy.network_defense.socket.getaddrinfo")
    def test_detects_local_dns_block(self, mock_getaddr, mock_run, nd):
        """Local failure + trusted success should warn about blocking."""
        mock_getaddr.side_effect = socket.gaierror("DNS failed")
        mock_run.return_value = _subprocess_result(
            "Server:  dns.google\nAddress:  8.8.8.8\n\n"
            "Non-authoritative answer:\nAddress:  142.250.80.46\n"
        )
        nd.check_dns_integrity()
        assert any(
            a["category"] == "dns_block" and a["severity"] == "warning"
            for a in nd.new_alerts
        )

    @patch("rudy.network_defense.subprocess.run")
    @patch("rudy.network_defense.socket.getaddrinfo")
    def test_saves_dns_baseline(self, mock_getaddr, mock_run, nd):
        """DNS baseline should be saved after check."""
        import rudy.network_defense as mod

        mock_getaddr.return_value = [(2, 1, 6, '', ('142.250.80.46', 0))]
        mock_run.return_value = _subprocess_result("")

        nd.check_dns_integrity()

        saved = json.loads(mod.DNS_BASELINE_FILE.read_text())
        assert "last_check" in saved
        assert "domains_checked" in saved


# ── Outbound Traffic Tests ───────────────────────────────────────

class TestOutboundTraffic:
    def test_skips_without_psutil(self, nd, monkeypatch):
        """Should return 'skipped' when psutil not available."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("No module named 'psutil'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = nd.check_outbound_traffic()
        assert result["status"] == "skipped"

    @patch("rudy.network_defense.subprocess.run")
    def test_new_destination_flagged(self, mock_run, nd, monkeypatch):
        """New outbound destinations should generate alerts."""
        mock_psutil = MagicMock()

        # Create a mock connection
        conn = MagicMock()
        conn.status = "ESTABLISHED"
        conn.raddr = MagicMock()
        conn.raddr.ip = "203.0.113.50"
        conn.raddr.port = 443
        conn.laddr = MagicMock()
        conn.laddr.port = 54321
        conn.pid = 1234
        mock_psutil.net_connections.return_value = [conn]

        proc = MagicMock()
        proc.name.return_value = "chrome.exe"
        mock_psutil.Process.return_value = proc

        import sys
        monkeypatch.setitem(sys.modules, "psutil", mock_psutil)

        result = nd.check_outbound_traffic()
        assert "203.0.113.50:443" in result["new_destinations"]

    @patch("rudy.network_defense.subprocess.run")
    def test_known_destination_not_flagged(self, mock_run, nd, monkeypatch):
        """Already-known destinations should not generate alerts."""
        nd.traffic_baseline["known_destinations"] = ["203.0.113.50:443"]

        mock_psutil = MagicMock()
        conn = MagicMock()
        conn.status = "ESTABLISHED"
        conn.raddr = MagicMock()
        conn.raddr.ip = "203.0.113.50"
        conn.raddr.port = 443
        conn.laddr = MagicMock()
        conn.laddr.port = 54321
        conn.pid = 1234
        mock_psutil.net_connections.return_value = [conn]

        import sys
        monkeypatch.setitem(sys.modules, "psutil", mock_psutil)

        result = nd.check_outbound_traffic()
        assert result["new_destinations"] == []

    @patch("rudy.network_defense.subprocess.run")
    def test_skips_local_connections(self, mock_run, nd, monkeypatch):
        """Local subnet and localhost connections should be skipped."""
        mock_psutil = MagicMock()
        conn_local = MagicMock()
        conn_local.status = "ESTABLISHED"
        conn_local.raddr = MagicMock()
        conn_local.raddr.ip = "127.0.0.1"
        conn_local.raddr.port = 8080
        conn_local.laddr = MagicMock()
        conn_local.pid = 100

        conn_subnet = MagicMock()
        conn_subnet.status = "ESTABLISHED"
        conn_subnet.raddr = MagicMock()
        conn_subnet.raddr.ip = "192.168.7.50"
        conn_subnet.raddr.port = 445
        conn_subnet.laddr = MagicMock()
        conn_subnet.pid = 200

        mock_psutil.net_connections.return_value = [conn_local, conn_subnet]

        import sys
        monkeypatch.setitem(sys.modules, "psutil", mock_psutil)

        result = nd.check_outbound_traffic()
        assert result["connections"] == 0

    @patch("rudy.network_defense.subprocess.run")
    def test_unusual_port_gets_warning(self, mock_run, nd, monkeypatch):
        """Connections to non-standard ports should get warning severity."""
        mock_psutil = MagicMock()
        conn = MagicMock()
        conn.status = "ESTABLISHED"
        conn.raddr = MagicMock()
        conn.raddr.ip = "203.0.113.50"
        conn.raddr.port = 31337  # Unusual port
        conn.laddr = MagicMock()
        conn.laddr.port = 54321
        conn.pid = 1234

        proc = MagicMock()
        proc.name.return_value = "suspicious.exe"
        mock_psutil.Process.return_value = proc
        mock_psutil.net_connections.return_value = [conn]

        import sys
        monkeypatch.setitem(sys.modules, "psutil", mock_psutil)

        nd.check_outbound_traffic()
        assert any(a["severity"] == "warning" for a in nd.new_alerts)


# ── Rogue Device Tests ───────────────────────────────────────────

class TestRogueDevices:
    @patch("rudy.network_defense.subprocess.run")
    def test_detects_new_device(self, mock_run, nd):
        """New MAC on the network should be flagged."""
        nd.state["known_network_macs"] = ["aa-bb-cc-dd-ee-01"]

        mock_run.return_value = _subprocess_result(
            _make_arp_output([
                ("1", "aa-bb-cc-dd-ee-01"),
                ("50", "ff-ee-dd-cc-bb-aa"),  # New device
            ])
        )
        result = nd.check_rogue_devices()
        assert len(result["new_devices"]) == 1
        assert result["new_devices"][0]["mac"] == "ff-ee-dd-cc-bb-aa"

    @patch("rudy.network_defense.subprocess.run")
    def test_known_devices_not_flagged(self, mock_run, nd):
        """Already-known devices should not trigger alerts."""
        nd.state["known_network_macs"] = ["aa-bb-cc-dd-ee-01"]

        mock_run.return_value = _subprocess_result(
            _make_arp_output([("1", "aa-bb-cc-dd-ee-01")])
        )
        result = nd.check_rogue_devices()
        assert len(result["new_devices"]) == 0

    @patch("rudy.network_defense.subprocess.run")
    def test_updates_known_macs(self, mock_run, nd):
        """After scan, newly seen MACs should be added to known list."""
        nd.state["known_network_macs"] = []

        mock_run.return_value = _subprocess_result(
            _make_arp_output([("1", "aa-bb-cc-dd-ee-01")])
        )
        nd.check_rogue_devices()
        assert "aa-bb-cc-dd-ee-01" in nd.state["known_network_macs"]


# ── SMB Activity Tests ───────────────────────────────────────────

class TestSMBActivity:
    @patch("rudy.network_defense.subprocess.run")
    def test_detects_active_sessions(self, mock_run, nd):
        """Active SMB sessions should trigger warning."""
        # First call: net share (clean)
        # Second call: net session (has sessions)
        mock_run.side_effect = [
            _subprocess_result("Share name   Resource\n----\nC$  C:\\\nIPC$  \n"),
            _subprocess_result("\\\\192.168.7.50  guest  0  0\n"),
        ]
        nd.check_smb_activity()
        assert any(a["category"] == "smb_session" for a in nd.new_alerts)

    @patch("rudy.network_defense.subprocess.run")
    def test_detects_unexpected_shares(self, mock_run, nd):
        """Non-default shares should trigger alert."""
        mock_run.side_effect = [
            _subprocess_result(
                "Share name   Resource\n"
                "----\n"
                "SUSPICIOUS_SHARE  D:\\shared\n"
            ),
            _subprocess_result(""),  # net session — empty
        ]
        nd.check_smb_activity()
        assert any(a["category"] == "unexpected_share" for a in nd.new_alerts)

    @patch("rudy.network_defense.subprocess.run")
    def test_clean_smb_no_alerts(self, mock_run, nd):
        """Clean SMB state should produce no alerts."""
        mock_run.side_effect = [
            _subprocess_result("Share name   Resource\n----\n"),
            _subprocess_result("There are no entries in the list.\n"),
        ]
        nd.check_smb_activity()
        assert len(nd.new_alerts) == 0


# ── Listening Port Tests ─────────────────────────────────────────

class TestListeningPorts:
    @patch("rudy.network_defense.subprocess.run")
    def test_detects_new_listening_port(self, mock_run, nd):
        """New listening port should be flagged."""
        nd.state["known_listening_ports"] = [80, 443]

        # First call: netstat
        # Second call: tasklist for PID lookup
        mock_run.side_effect = [
            _subprocess_result(_make_netstat_output([(80, 100), (443, 200), (4444, 999)])),
            _subprocess_result('"evil.exe","999","Console","1","10,000 K"'),
        ]
        result = nd.check_listening_ports()
        assert 4444 in result["new_ports"]
        assert 80 not in result["new_ports"]

    @patch("rudy.network_defense.subprocess.run")
    def test_known_ports_not_flagged(self, mock_run, nd):
        """Already-known listening ports should not trigger alerts."""
        nd.state["known_listening_ports"] = [80, 443, 8080]

        mock_run.return_value = _subprocess_result(
            _make_netstat_output([(80, 100), (443, 200)])
        )
        result = nd.check_listening_ports()
        assert result["new_ports"] == []

    @patch("rudy.network_defense.subprocess.run")
    def test_low_port_gets_alert_severity(self, mock_run, nd):
        """New port <= 1024 should get 'alert' severity."""
        nd.state["known_listening_ports"] = []

        mock_run.side_effect = [
            _subprocess_result(_make_netstat_output([(22, 500)])),
            _subprocess_result('"sshd.exe","500","Console","1","5,000 K"'),
        ]
        nd.check_listening_ports()
        assert any(
            a["severity"] == "alert" and "22" in a["message"]
            for a in nd.new_alerts
        )

    @patch("rudy.network_defense.subprocess.run")
    def test_high_port_gets_warning_severity(self, mock_run, nd):
        """New port > 1024 should get 'warning' severity."""
        nd.state["known_listening_ports"] = []

        mock_run.side_effect = [
            _subprocess_result(_make_netstat_output([(8080, 500)])),
            _subprocess_result('"node.exe","500","Console","1","50,000 K"'),
        ]
        nd.check_listening_ports()
        assert any(
            a["severity"] == "warning" and "8080" in a["message"]
            for a in nd.new_alerts
        )

    @patch("rudy.network_defense.subprocess.run")
    def test_updates_known_ports(self, mock_run, nd):
        """After scan, all current ports should be saved to state."""
        nd.state["known_listening_ports"] = []

        mock_run.return_value = _subprocess_result(
            _make_netstat_output([(80, 100), (443, 200)])
        )
        nd.check_listening_ports()
        assert set(nd.state["known_listening_ports"]) == {80, 443}


# ── Config Drift Tests ───────────────────────────────────────────

class TestConfigDrift:
    @patch("rudy.network_defense.subprocess.run")
    def test_detects_registry_change(self, mock_run, nd):
        """Changed registry hash should trigger alert."""
        # Set up baseline with known hash
        nd.state["registry_baseline"] = {
            "startup_hklm": {"hash": "abcdef1234567890", "entries": 3},
        }

        # Return different content (different hash)
        mock_run.return_value = _subprocess_result(
            "HKLM\\Software\\...\\Run\n"
            "    SomeApp    REG_SZ    C:\\app.exe\n"
            "    Malware    REG_SZ    C:\\bad.exe\n"
            "    Another    REG_SZ    C:\\x.exe\n"
            "    NewEntry   REG_SZ    C:\\new.exe\n"
        )
        nd.check_config_drift()
        assert any(a["category"] == "config_drift" for a in nd.new_alerts)

    @patch("rudy.network_defense.subprocess.run")
    def test_first_run_no_drift(self, mock_run, nd):
        """First run (no baseline) should not report drift."""
        mock_run.return_value = _subprocess_result(
            "HKLM\\Software\\...\\Run\n    App    REG_SZ    C:\\app.exe\n"
        )
        result = nd.check_config_drift()
        assert len(result["drifts"]) == 0

    @patch("rudy.network_defense.subprocess.run")
    def test_saves_registry_baseline(self, mock_run, nd):
        """After check, registry baseline should be saved to state."""
        mock_run.return_value = _subprocess_result(
            "HKLM\\Software\\...\\Run\n    App    REG_SZ    C:\\app.exe\n"
        )
        nd.check_config_drift()
        assert "registry_baseline" in nd.state
        assert "startup_hklm" in nd.state["registry_baseline"]


# ── Run All Checks Tests ─────────────────────────────────────────

class TestRunAllChecks:
    @patch.object(
        __import__("rudy.network_defense", fromlist=["NetworkDefense"]).NetworkDefense,
        "check_arp_integrity",
        return_value={"status": "ok"},
    )
    @patch.object(
        __import__("rudy.network_defense", fromlist=["NetworkDefense"]).NetworkDefense,
        "check_dns_integrity",
        return_value={"status": "ok"},
    )
    @patch.object(
        __import__("rudy.network_defense", fromlist=["NetworkDefense"]).NetworkDefense,
        "check_outbound_traffic",
        return_value={"status": "ok"},
    )
    @patch.object(
        __import__("rudy.network_defense", fromlist=["NetworkDefense"]).NetworkDefense,
        "check_rogue_devices",
        return_value={"status": "ok"},
    )
    @patch.object(
        __import__("rudy.network_defense", fromlist=["NetworkDefense"]).NetworkDefense,
        "check_smb_activity",
        return_value={"status": "ok"},
    )
    @patch.object(
        __import__("rudy.network_defense", fromlist=["NetworkDefense"]).NetworkDefense,
        "check_config_drift",
        return_value={"status": "ok"},
    )
    @patch.object(
        __import__("rudy.network_defense", fromlist=["NetworkDefense"]).NetworkDefense,
        "check_listening_ports",
        return_value={"status": "ok"},
    )
    def test_all_ok(self, *mocks):
        """All clean checks should produce 'ok' overall."""
        import rudy.network_defense as mod

        nd = mod.NetworkDefense()
        result = nd.run_all_checks()
        assert result["overall_status"] == "ok"
        assert result["alerts_generated"] == 0
        assert len(result["checks"]) == 7

    def test_critical_overrides_all(self, nd):
        """If any check returns 'critical', overall should be critical."""
        nd.check_arp_integrity = lambda: {"status": "critical"}
        nd.check_dns_integrity = lambda: {"status": "ok"}
        nd.check_outbound_traffic = lambda: {"status": "warning"}
        nd.check_rogue_devices = lambda: {"status": "ok"}
        nd.check_smb_activity = lambda: {"status": "ok"}
        nd.check_config_drift = lambda: {"status": "ok"}
        nd.check_listening_ports = lambda: {"status": "ok"}

        result = nd.run_all_checks()
        assert result["overall_status"] == "critical"

    def test_alert_overrides_warning(self, nd):
        """'alert' status should override 'warning' but not 'critical'."""
        nd.check_arp_integrity = lambda: {"status": "ok"}
        nd.check_dns_integrity = lambda: {"status": "warning"}
        nd.check_outbound_traffic = lambda: {"status": "alert"}
        nd.check_rogue_devices = lambda: {"status": "ok"}
        nd.check_smb_activity = lambda: {"status": "ok"}
        nd.check_config_drift = lambda: {"status": "ok"}
        nd.check_listening_ports = lambda: {"status": "ok"}

        result = nd.run_all_checks()
        assert result["overall_status"] == "alert"

    def test_check_exception_caught(self, nd):
        """If a check raises, it should be caught and marked as error."""
        nd.check_arp_integrity = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        nd.check_dns_integrity = lambda: {"status": "ok"}
        nd.check_outbound_traffic = lambda: {"status": "ok"}
        nd.check_rogue_devices = lambda: {"status": "ok"}
        nd.check_smb_activity = lambda: {"status": "ok"}
        nd.check_config_drift = lambda: {"status": "ok"}
        nd.check_listening_ports = lambda: {"status": "ok"}

        # Should not crash
        result = nd.run_all_checks()
        assert result["checks"]["arp_integrity"]["status"] == "error"

    def test_saves_state_and_alerts(self, nd, tmp_path):
        """run_all_checks should save state and alerts files."""
        import rudy.network_defense as mod

        nd.check_arp_integrity = lambda: {"status": "ok"}
        nd.check_dns_integrity = lambda: {"status": "ok"}
        nd.check_outbound_traffic = lambda: {"status": "ok"}
        nd.check_rogue_devices = lambda: {"status": "ok"}
        nd.check_smb_activity = lambda: {"status": "ok"}
        nd.check_config_drift = lambda: {"status": "ok"}
        nd.check_listening_ports = lambda: {"status": "ok"}

        nd.run_all_checks()
        assert mod.DEFENSE_STATE_FILE.exists()
        assert mod.DEFENSE_ALERTS_FILE.exists()

    def test_alerts_capped_at_1000(self, nd):
        """Alert list should be capped at 1000 entries."""
        nd.alerts = [{"severity": "info", "message": f"old-{i}"} for i in range(1500)]

        nd.check_arp_integrity = lambda: {"status": "ok"}
        nd.check_dns_integrity = lambda: {"status": "ok"}
        nd.check_outbound_traffic = lambda: {"status": "ok"}
        nd.check_rogue_devices = lambda: {"status": "ok"}
        nd.check_smb_activity = lambda: {"status": "ok"}
        nd.check_config_drift = lambda: {"status": "ok"}
        nd.check_listening_ports = lambda: {"status": "ok"}

        nd.run_all_checks()
        assert len(nd.alerts) <= 1000


# ── Defense Report Tests ─────────────────────────────────────────

class TestDefenseReport:
    def test_report_includes_header(self, nd):
        """Report should contain header and status."""
        report = nd.get_defense_report()
        assert "NETWORK DEFENSE STATUS" in report

    def test_report_shows_gateway(self, nd):
        """Report should show gateway MAC info."""
        nd.arp_baseline["gateway_mac"] = "aa-bb-cc-dd-ee-ff"
        report = nd.get_defense_report()
        assert "aa-bb-cc-dd-ee-ff" in report

    def test_report_shows_recent_alerts(self, nd):
        """Report should include recent warning/alert/critical alerts."""
        nd.alerts = [
            {"severity": "critical", "message": "Gateway MAC changed!",
             "time": datetime.now().isoformat()},
        ]
        report = nd.get_defense_report()
        assert "Gateway MAC changed!" in report

    def test_report_skips_info_alerts(self, nd):
        """Report should not show info-level alerts in recent section."""
        nd.alerts = [
            {"severity": "info", "message": "All good",
             "time": datetime.now().isoformat()},
        ]
        report = nd.get_defense_report()
        assert "All good" not in report


# ── Gateway Detection Tests ──────────────────────────────────────

class TestGatewayDetection:
    @patch("subprocess.run")
    def test_detect_gateway_parses_ipconfig(self, mock_run):
        """_detect_current_gateway should parse ipconfig output."""
        from rudy.network_defense import _detect_current_gateway

        mock_run.return_value = _subprocess_result(
            "Windows IP Configuration\n\n"
            "   Default Gateway . . . . . . . . . : 10.0.0.1\n"
        )
        gw, subnet = _detect_current_gateway()
        assert gw == "10.0.0.1"
        assert subnet == "10.0.0"

    @patch("subprocess.run")
    def test_detect_gateway_fallback(self, mock_run):
        """Should fall back to defaults on failure."""
        from rudy.network_defense import _detect_current_gateway

        mock_run.side_effect = Exception("no ipconfig")
        gw, subnet = _detect_current_gateway()
        assert gw == "192.168.7.1"
        assert subnet == "192.168.7"
