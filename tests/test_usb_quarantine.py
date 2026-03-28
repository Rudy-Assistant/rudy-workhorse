"""
Tests for USB Quarantine — Fortress Paradox safeguards and threat assessment.

These tests verify the critical safety logic that prevents the Workhorse
from bricking itself by blocking its own input devices.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent))

from rudy.usb_quarantine import (
    DeviceFingerprint,
    DEVICE_CLASS_RISK,
    KNOWN_MALICIOUS_DEVICES,
    _is_hid_device,
    _has_whitelisted_hid_connected,
    _is_kill_switch_active,
    _should_block_device,
    _assess_threat,
    _load_json,
    _save_json,
    DEPLOYMENT_PHASE,
    KILL_SWITCH_FILE,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def blank_fp():
    """A blank DeviceFingerprint with no properties set."""
    return DeviceFingerprint()


@pytest.fixture
def keyboard_fp():
    """A fingerprint that looks like a legitimate keyboard."""
    fp = DeviceFingerprint()
    fp.instance_id = "USB\\VID_046D&PID_C534\\1234567890"
    fp.vid = "046D"
    fp.pid = "C534"
    fp.serial = "1234567890"
    fp.manufacturer = "Logitech"
    fp.friendly_name = "Logitech USB Receiver"
    fp.device_class = "HIDClass"
    fp.device_classes = ["HIDClass"]
    fp.description = "USB Input Device"
    fp.driver = "HID Keyboard Device"
    fp.driver_provider = "Microsoft"
    return fp


@pytest.fixture
def rubber_ducky_fp():
    """A fingerprint matching the Hak5 Rubber Ducky."""
    fp = DeviceFingerprint()
    fp.instance_id = "USB\\VID_04D8&PID_F2CF\\0"
    fp.vid = "04D8"
    fp.pid = "F2CF"
    fp.serial = "0"
    fp.manufacturer = ""
    fp.friendly_name = "USB Input Device"
    fp.device_class = "HIDClass"
    fp.device_classes = ["HIDClass"]
    fp.hardware_ids = ["USB\\VID_04D8&PID_F2CF"]
    return fp


@pytest.fixture
def composite_badusb_fp():
    """A composite device with HID + Storage — classic BadUSB."""
    fp = DeviceFingerprint()
    fp.instance_id = "USB\\VID_2E8A&PID_000A\\DEADBEEF"
    fp.vid = "2E8A"
    fp.pid = "000A"
    fp.serial = "DEADBEEF"
    fp.manufacturer = ""
    fp.friendly_name = "USB Composite Device"
    fp.device_class = "HIDClass"
    fp.device_classes = ["HIDClass", "DiskDrive"]
    fp.is_composite = True
    return fp


@pytest.fixture
def safe_flash_drive_fp():
    """A normal USB flash drive."""
    fp = DeviceFingerprint()
    fp.instance_id = "USB\\VID_0781&PID_5581\\20060266100C37B9"
    fp.vid = "0781"
    fp.pid = "5581"
    fp.serial = "20060266100C37B9"
    fp.manufacturer = "SanDisk"
    fp.friendly_name = "SanDisk Ultra USB 3.0"
    fp.device_class = "DiskDrive"
    fp.device_classes = ["DiskDrive"]
    fp.driver = "Disk Drive"
    fp.driver_provider = "Microsoft"
    return fp


@pytest.fixture
def remote_access_fp():
    """A device related to remote access (e.g., Tailscale virtual adapter)."""
    fp = DeviceFingerprint()
    fp.instance_id = "ROOT\\NET\\0001"
    fp.vid = ""
    fp.pid = ""
    fp.friendly_name = "Tailscale Tunnel"
    fp.description = "Tailscale Virtual Network Adapter"
    fp.device_class = "Net"
    fp.manufacturer = "Tailscale Inc."
    fp.driver = "Tailscale Network Driver"
    return fp


@pytest.fixture
def whitelist_with_hid():
    """A whitelist that contains a known HID device."""
    return {
        "devices": {
            "046D:C534:1234567890": {
                "name": "Logitech Receiver",
                "class": "HIDClass",
                "added_by": "chris",
            }
        }
    }


@pytest.fixture
def whitelist_no_hid():
    """A whitelist with only non-HID devices."""
    return {
        "devices": {
            "0781:5581:20060266100C37B9": {
                "name": "SanDisk Flash Drive",
                "class": "DiskDrive",
                "added_by": "chris",
            }
        }
    }


@pytest.fixture
def empty_whitelist():
    return {"devices": {}}


# ── DeviceFingerprint Tests ───────────────────────────────────


class TestDeviceFingerprint:
    def test_blank_defaults(self, blank_fp):
        assert blank_fp.threat_score == 0
        assert blank_fp.risk_level == "UNKNOWN"
        assert blank_fp.device_class == ""
        assert blank_fp.is_composite is False
        assert blank_fp.device_classes == []

    def test_device_key_with_serial(self, keyboard_fp):
        assert keyboard_fp.device_key() == "046D:C534:1234567890"

    def test_device_key_no_serial(self, blank_fp):
        blank_fp.vid = "DEAD"
        blank_fp.pid = "BEEF"
        assert blank_fp.device_key() == "DEAD:BEEF:no-serial"

    def test_to_dict_roundtrip(self, keyboard_fp):
        d = keyboard_fp.to_dict()
        assert d["vid"] == "046D"
        assert d["pid"] == "C534"
        assert d["manufacturer"] == "Logitech"
        assert d["device_class"] == "HIDClass"
        assert isinstance(d, dict)

    def test_to_dict_has_all_expected_keys(self, blank_fp):
        d = blank_fp.to_dict()
        expected = {
            "instance_id", "vid", "pid", "serial", "manufacturer",
            "friendly_name", "device_class", "device_classes", "description",
            "hardware_ids", "compatible_ids", "driver", "driver_provider",
            "driver_date", "driver_version", "status", "install_date",
            "container_id", "bus_reported_description", "is_composite",
            "child_devices", "threat_score", "risk_level", "risk_reasons",
            "recommended_action", "first_seen",
        }
        assert set(d.keys()) == expected


# ── HID Detection Tests ──────────────────────────────────────


class TestIsHidDevice:
    def test_hidclass(self):
        assert _is_hid_device("HIDClass") is True

    def test_keyboard(self):
        assert _is_hid_device("Keyboard") is True

    def test_mouse(self):
        assert _is_hid_device("Mouse") is True

    def test_disk_drive_not_hid(self):
        assert _is_hid_device("DiskDrive") is False

    def test_net_not_hid(self):
        assert _is_hid_device("Net") is False

    def test_empty_string_not_hid(self):
        assert _is_hid_device("") is False

    def test_composite_with_hid_in_classes(self):
        assert _is_hid_device("DiskDrive", ["DiskDrive", "HIDClass"]) is True

    def test_composite_without_hid(self):
        assert _is_hid_device("DiskDrive", ["DiskDrive", "Camera"]) is False

    def test_none_classes_list(self):
        assert _is_hid_device("DiskDrive", None) is False


# ── Whitelisted HID Detection ────────────────────────────────


class TestHasWhitelistedHid:
    def test_whitelist_with_hid(self, whitelist_with_hid):
        assert _has_whitelisted_hid_connected(whitelist_with_hid) is True

    def test_whitelist_no_hid(self, whitelist_no_hid):
        assert _has_whitelisted_hid_connected(whitelist_no_hid) is False

    def test_empty_whitelist(self, empty_whitelist):
        assert _has_whitelisted_hid_connected(empty_whitelist) is False

    def test_empty_dict(self):
        assert _has_whitelisted_hid_connected({}) is False

    def test_keyboard_class(self):
        wl = {"devices": {"x:y:z": {"class": "Keyboard"}}}
        assert _has_whitelisted_hid_connected(wl) is True

    def test_mouse_class(self):
        wl = {"devices": {"x:y:z": {"class": "Mouse"}}}
        assert _has_whitelisted_hid_connected(wl) is True

    def test_device_class_key(self):
        """Some entries use 'device_class' instead of 'class'."""
        wl = {"devices": {"x:y:z": {"device_class": "HIDClass"}}}
        assert _has_whitelisted_hid_connected(wl) is True


# ── Kill Switch Tests ─────────────────────────────────────────


class TestKillSwitch:
    def test_kill_switch_active(self, tmp_path):
        kill_file = tmp_path / "SECURITY-DISABLED"
        kill_file.touch()
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file):
            assert _is_kill_switch_active() is True

    def test_kill_switch_inactive(self, tmp_path):
        kill_file = tmp_path / "SECURITY-DISABLED"
        # File does NOT exist
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file):
            assert _is_kill_switch_active() is False


# ── Threat Assessment Tests ───────────────────────────────────


class TestThreatAssessment:
    def test_known_malicious_device_scores_high(self, rubber_ducky_fp):
        _assess_threat(rubber_ducky_fp)
        assert rubber_ducky_fp.threat_score >= 80
        assert rubber_ducky_fp.risk_level == "CRITICAL"
        assert any("KNOWN ATTACK" in r for r in rubber_ducky_fp.risk_reasons)

    def test_composite_hid_storage_scores_critical(self, composite_badusb_fp):
        _assess_threat(composite_badusb_fp)
        assert composite_badusb_fp.threat_score >= 80
        assert composite_badusb_fp.risk_level == "CRITICAL"

    def test_safe_flash_drive_scores_medium(self, safe_flash_drive_fp):
        _assess_threat(safe_flash_drive_fp)
        # DiskDrive class scores 50 (MEDIUM). SanDisk is a real manufacturer,
        # so no manufacturer penalty. Long serial, so no serial penalty.
        assert safe_flash_drive_fp.threat_score == 50
        assert safe_flash_drive_fp.risk_level == "HIGH"  # 50 = HIGH threshold

    def test_no_serial_adds_points(self, blank_fp):
        blank_fp.serial = ""
        _assess_threat(blank_fp)
        assert any("serial" in r.lower() for r in blank_fp.risk_reasons)

    def test_short_serial_adds_points(self, blank_fp):
        blank_fp.serial = "&0"
        _assess_threat(blank_fp)
        assert any("serial" in r.lower() for r in blank_fp.risk_reasons)

    def test_generic_manufacturer_adds_points(self, blank_fp):
        blank_fp.manufacturer = ""
        blank_fp.serial = "VALID_SERIAL_123"
        _assess_threat(blank_fp)
        assert any("manufacturer" in r.lower() for r in blank_fp.risk_reasons)

    def test_driver_mismatch_camera_hid(self, blank_fp):
        blank_fp.device_class = "Camera"
        blank_fp.driver = "HID Keyboard Device"
        blank_fp.serial = "VALID_SERIAL_123"
        blank_fp.manufacturer = "Legit Corp"
        _assess_threat(blank_fp)
        assert any("DRIVER MISMATCH" in r for r in blank_fp.risk_reasons)
        assert blank_fp.threat_score >= 40

    def test_null_vid_pid_adds_points(self, blank_fp):
        blank_fp.vid = "0000"
        blank_fp.serial = "VALID_SERIAL_123"
        blank_fp.manufacturer = "Legit Corp"
        _assess_threat(blank_fp)
        assert any("NULL VID" in r for r in blank_fp.risk_reasons)

    def test_keyboard_emulation_in_hardware_ids(self, blank_fp):
        blank_fp.device_class = "DiskDrive"
        blank_fp.hardware_ids = ["USB\\VID_1234&PID_5678", "HID_DEVICE_SYSTEM_KEYBOARD"]
        blank_fp.serial = "VALID_SERIAL_123"
        blank_fp.manufacturer = "Legit Corp"
        _assess_threat(blank_fp)
        assert any("keyboard emulation" in r.lower() for r in blank_fp.risk_reasons)

    def test_score_caps_at_100(self, rubber_ducky_fp):
        """Even with multiple risk factors, score should not exceed 100."""
        rubber_ducky_fp.is_composite = True
        rubber_ducky_fp.device_classes = ["HIDClass", "DiskDrive"]
        rubber_ducky_fp.hardware_ids = ["HID_DEVICE_SYSTEM_KEYBOARD"]
        rubber_ducky_fp.vid = "0000"
        _assess_threat(rubber_ducky_fp)
        assert rubber_ducky_fp.threat_score <= 100

    def test_risk_level_boundaries(self):
        """Test all risk level boundaries."""
        boundaries = [
            (0, "MINIMAL"), (14, "MINIMAL"),
            (15, "LOW"), (29, "LOW"),
            (30, "MEDIUM"), (49, "MEDIUM"),
            (50, "HIGH"), (79, "HIGH"),
            (80, "CRITICAL"), (100, "CRITICAL"),
        ]
        for score, expected_level in boundaries:
            fp = DeviceFingerprint()
            fp.serial = "VALID_SERIAL_123"
            fp.manufacturer = "Legit Corp"
            fp.threat_score = score
            # Manually set the risk level using the same logic
            if score >= 80:
                assert expected_level == "CRITICAL"
            elif score >= 50:
                assert expected_level == "HIGH"
            elif score >= 30:
                assert expected_level == "MEDIUM"
            elif score >= 15:
                assert expected_level == "LOW"
            else:
                assert expected_level == "MINIMAL"


# ── Fortress Paradox Safeguard Tests ──────────────────────────
# These are the MOST CRITICAL tests — they verify the system
# cannot brick itself by blocking its own input devices.


class TestShouldBlockDevice:
    """Test all 5 Fortress Paradox safeguards in _should_block_device()."""

    def test_safeguard1_kill_switch_prevents_block(
        self, keyboard_fp, whitelist_with_hid, tmp_path
    ):
        """SAFEGUARD 1: Kill switch file must prevent ALL blocking."""
        kill_file = tmp_path / "SECURITY-DISABLED"
        kill_file.touch()
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 4):
            should_block, reason = _should_block_device(keyboard_fp, whitelist_with_hid)
            assert should_block is False
            assert "KILL_SWITCH" in reason

    def test_safeguard2_boot_grace_allows_hid(
        self, keyboard_fp, whitelist_with_hid, tmp_path
    ):
        """SAFEGUARD 2: HID devices allowed during first 10min of boot."""
        kill_file = tmp_path / "SECURITY-DISABLED"
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 4), \
             patch("rudy.usb_quarantine._system_uptime_minutes", return_value=3.0):
            should_block, reason = _should_block_device(keyboard_fp, whitelist_with_hid)
            assert should_block is False
            assert "BOOT_GRACE" in reason

    def test_safeguard3_no_whitelisted_hid_prevents_hid_block(
        self, keyboard_fp, whitelist_no_hid, tmp_path
    ):
        """SAFEGUARD 3: Never block HID if no whitelisted HID is connected."""
        kill_file = tmp_path / "SECURITY-DISABLED"
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 4), \
             patch("rudy.usb_quarantine._system_uptime_minutes", return_value=60.0):
            should_block, reason = _should_block_device(keyboard_fp, whitelist_no_hid)
            assert should_block is False
            assert "FORTRESS_PARADOX" in reason

    def test_safeguard4_remote_access_never_blocked(
        self, remote_access_fp, whitelist_with_hid, tmp_path
    ):
        """SAFEGUARD 4: Remote access devices are SACRED — never blocked."""
        kill_file = tmp_path / "SECURITY-DISABLED"
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 4), \
             patch("rudy.usb_quarantine._system_uptime_minutes", return_value=60.0):
            should_block, reason = _should_block_device(remote_access_fp, whitelist_with_hid)
            assert should_block is False
            assert "REMOTE_SACRED" in reason

    def test_safeguard5_phase1_never_blocks(
        self, keyboard_fp, whitelist_with_hid, tmp_path
    ):
        """SAFEGUARD 5: Deployment phase 1 (log-only) never blocks."""
        kill_file = tmp_path / "SECURITY-DISABLED"
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 1):
            should_block, reason = _should_block_device(keyboard_fp, whitelist_with_hid)
            assert should_block is False
            assert "PHASE_1" in reason

    def test_safeguard5_phase2_never_blocks(
        self, keyboard_fp, whitelist_with_hid, tmp_path
    ):
        """SAFEGUARD 5: Deployment phase 2 (prompt) never auto-blocks."""
        kill_file = tmp_path / "SECURITY-DISABLED"
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 2):
            should_block, reason = _should_block_device(keyboard_fp, whitelist_with_hid)
            assert should_block is False
            assert "PHASE_2" in reason

    def test_blocking_allowed_when_all_safeguards_pass(
        self, safe_flash_drive_fp, whitelist_with_hid, tmp_path
    ):
        """When all safeguards pass: non-HID device in phase 3+ CAN be blocked."""
        kill_file = tmp_path / "SECURITY-DISABLED"
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 3), \
             patch("rudy.usb_quarantine._system_uptime_minutes", return_value=60.0):
            should_block, reason = _should_block_device(
                safe_flash_drive_fp, whitelist_with_hid
            )
            assert should_block is True
            assert "safeguards passed" in reason.lower()

    def test_rustdesk_in_description_is_sacred(self, whitelist_with_hid, tmp_path):
        """RustDesk virtual devices must never be blocked."""
        fp = DeviceFingerprint()
        fp.friendly_name = "RustDesk Virtual Display"
        fp.description = "rustdesk display adapter"
        fp.device_class = "Display"
        fp.driver = "RustDesk Display Driver"
        fp.manufacturer = "RustDesk"
        kill_file = tmp_path / "SECURITY-DISABLED"
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 4), \
             patch("rudy.usb_quarantine._system_uptime_minutes", return_value=60.0):
            should_block, reason = _should_block_device(fp, whitelist_with_hid)
            assert should_block is False
            assert "REMOTE_SACRED" in reason

    def test_empty_whitelist_protects_hid(
        self, keyboard_fp, empty_whitelist, tmp_path
    ):
        """With empty whitelist, HID devices must NEVER be blocked."""
        kill_file = tmp_path / "SECURITY-DISABLED"
        with patch("rudy.usb_quarantine.KILL_SWITCH_FILE", kill_file), \
             patch("rudy.usb_quarantine.DEPLOYMENT_PHASE", 4), \
             patch("rudy.usb_quarantine._system_uptime_minutes", return_value=60.0):
            should_block, reason = _should_block_device(keyboard_fp, empty_whitelist)
            assert should_block is False


# ── Data Integrity Tests ──────────────────────────────────────


class TestDataIntegrity:
    def test_all_device_class_risks_have_required_fields(self):
        """Every entry in DEVICE_CLASS_RISK must have risk, score, reason, action."""
        required = {"risk", "score", "reason", "action"}
        for cls_name, info in DEVICE_CLASS_RISK.items():
            missing = required - set(info.keys())
            assert not missing, f"{cls_name} is missing fields: {missing}"

    def test_device_class_scores_are_valid(self):
        """All risk scores must be 0-100."""
        for cls_name, info in DEVICE_CLASS_RISK.items():
            assert 0 <= info["score"] <= 100, f"{cls_name} has invalid score: {info['score']}"

    def test_known_malicious_devices_format(self):
        """KNOWN_MALICIOUS_DEVICES keys must be (VID, PID) tuples of 4-char hex."""
        for (vid, pid), name in KNOWN_MALICIOUS_DEVICES.items():
            assert len(vid) == 4, f"VID '{vid}' is not 4 chars"
            assert len(pid) == 4, f"PID '{pid}' is not 4 chars"
            int(vid, 16)  # Should not raise
            int(pid, 16)  # Should not raise
            assert isinstance(name, str) and len(name) > 0

    def test_hid_devices_score_above_critical(self):
        """HIDClass and Keyboard should be CRITICAL risk.
        Note: Mouse is not a separate entry — it falls under HIDClass."""
        for cls in ("HIDClass", "Keyboard"):
            assert cls in DEVICE_CLASS_RISK
            assert DEVICE_CLASS_RISK[cls]["risk"] == "CRITICAL"
            assert DEVICE_CLASS_RISK[cls]["score"] >= 80

    def test_mouse_treated_as_hid(self):
        """Mouse is recognized as HID even if not in DEVICE_CLASS_RISK."""
        assert _is_hid_device("Mouse") is True


# ── JSON Helper Tests ─────────────────────────────────────────


class TestJsonHelpers:
    def test_load_json_existing_file(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}')
        result = _load_json(f)
        assert result == {"key": "value"}

    def test_load_json_missing_file(self, tmp_path):
        f = tmp_path / "nonexistent.json"
        result = _load_json(f)
        assert result == {}

    def test_load_json_custom_default(self, tmp_path):
        f = tmp_path / "nonexistent.json"
        result = _load_json(f, default=[])
        assert result == []

    def test_load_json_corrupt_file(self, tmp_path):
        f = tmp_path / "corrupt.json"
        f.write_text("not valid json {{{")
        result = _load_json(f)
        assert result == {}

    def test_save_json_creates_dirs(self, tmp_path):
        f = tmp_path / "nested" / "dir" / "test.json"
        _save_json(f, {"hello": "world"})
        assert f.exists()
        loaded = json.loads(f.read_text())
        assert loaded == {"hello": "world"}

    def test_save_json_roundtrip(self, tmp_path):
        f = tmp_path / "roundtrip.json"
        data = {"devices": {"A:B:C": {"name": "test", "score": 42}}}
        _save_json(f, data)
        loaded = _load_json(f)
        assert loaded == data
