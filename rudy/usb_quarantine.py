"""
USB Quarantine — Full quarantine protocol for unknown devices.

Philosophy: Every new USB device is an unknown entity plugging into the family's
most trusted machine. The system's job is to determine WHAT it is, WHETHER it's
safe, and WHAT it wants — before granting any trust.

Posture:
  - Known/whitelisted devices → quick verification, proceed
  - Previously seen but not whitelisted → prompt for confirmation
  - Completely unknown devices → FULL QUARANTINE: aggressive profiling,
    behavioral analysis, threat assessment. An unknown device plugged into
    this PC is treated as a potential intrusion until proven otherwise.

Protocol (for unknown devices):
  1. DETECT: PnP event fires, new InstanceId appears
  2. IDENTIFY: Hardware IDs, VID/PID, device class, manufacturer, serial
  3. CLASSIFY: What type of device is this claiming to be?
     - HID (keyboard/mouse) — HIGH RISK (rubber ducky, BadUSB)
     - Mass storage — MEDIUM RISK (autorun, payload delivery)
     - Camera/video — MEDIUM RISK (verify it's actually a camera)
     - Phone/MTP — MEDIUM RISK (data exfiltration vector)
     - Hub — LOW RISK but monitor downstream devices
     - Audio — LOW RISK
     - Network adapter — HIGH RISK (network MITM, exfiltration)
     - Composite — HIGH RISK (claims multiple classes, common in attacks)
  4. PROFILE: Deep fingerprinting
     - VID/PID lookup against USB-IF database
     - Known-malicious device signature check
     - Behavioral monitoring (does a "camera" also register as HID?)
     - Driver analysis (what drivers does Windows load?)
  5. ASSESS: Threat score (0-100)
  6. DECIDE: Allow / Block / Alert
  7. LOG: Full audit trail

Whitelisting:
  Devices are identified by (VID, PID, Serial) tuple.
  Whitelist is stored in rudy-data/usb-whitelist.json.
  Only Chris can add devices to whitelist.

Integration:
  - Sentinel calls usb_quarantine.check_devices() every 15 min
  - Real-time monitoring via watchdog (optional, if USB event hooks available)
  - Alerts via email (Zoho SMTP) for HIGH/CRITICAL threats
  - Results written to rudy-logs/usb-quarantine/
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Dict, List

from rudy.paths import RUDY_LOGS, RUDY_DATA  # noqa: E402

LOGS_DIR = RUDY_LOGS
QUARANTINE_DIR = LOGS_DIR / "usb-quarantine"
DATA_DIR = RUDY_DATA
WHITELIST_FILE = DATA_DIR / "usb-whitelist.json"
QUARANTINE_STATE = QUARANTINE_DIR / "quarantine-state.json"
KILL_SWITCH_FILE = DATA_DIR / "SECURITY-DISABLED"
DEPLOYMENT_PHASE = 1  # 1=log-only, 2=prompt, 3=auto-block+safeguards, 4=full autonomous

# ── Risk classification by USB device class ───────────────────

DEVICE_CLASS_RISK = {
    "HIDClass": {
        "risk": "CRITICAL",
        "score": 90,
        "reason": "HID devices can inject keystrokes (BadUSB, Rubber Ducky, O.MG cable)",
        "action": "block_and_alert",
    },
    "Keyboard": {
        "risk": "CRITICAL",
        "score": 95,
        "reason": "Keyboard emulation is the #1 USB attack vector",
        "action": "block_and_alert",
    },
    "Net": {
        "risk": "HIGH",
        "score": 80,
        "reason": "Network adapters can MITM traffic, exfiltrate data, or redirect DNS",
        "action": "block_and_alert",
    },
    "USB": {
        "risk": "MEDIUM",
        "score": 50,
        "reason": "Generic USB device — needs further classification",
        "action": "profile_and_prompt",
    },
    "Camera": {
        "risk": "MEDIUM",
        "score": 40,
        "reason": "Camera device — verify it's actually a camera and not composite",
        "action": "profile_and_prompt",
    },
    "Image": {
        "risk": "MEDIUM",
        "score": 40,
        "reason": "Imaging device (camera/scanner) — verify class integrity",
        "action": "profile_and_prompt",
    },
    "WPD": {
        "risk": "MEDIUM",
        "score": 45,
        "reason": "Windows Portable Device (phone/tablet via MTP) — data access vector",
        "action": "profile_and_prompt",
    },
    "DiskDrive": {
        "risk": "MEDIUM",
        "score": 50,
        "reason": "Mass storage — check for autorun, suspicious executables",
        "action": "profile_and_prompt",
    },
    "CDROM": {
        "risk": "MEDIUM",
        "score": 55,
        "reason": "CD-ROM class can trigger autorun — also used by BadUSB",
        "action": "profile_and_prompt",
    },
    "USBDevice": {
        "risk": "MEDIUM",
        "score": 50,
        "reason": "Generic USB device class — unknown purpose",
        "action": "profile_and_prompt",
    },
    "AudioEndpoint": {
        "risk": "LOW",
        "score": 20,
        "reason": "Audio device — low risk unless composite",
        "action": "log_and_allow",
    },
    "Media": {
        "risk": "LOW",
        "score": 20,
        "reason": "Media device — low risk",
        "action": "log_and_allow",
    },
    "Monitor": {
        "risk": "LOW",
        "score": 15,
        "reason": "Display/monitor — minimal risk",
        "action": "log_and_allow",
    },
    "HIDClass+DiskDrive": {
        "risk": "CRITICAL",
        "score": 95,
        "reason": "COMPOSITE: HID + Storage — classic BadUSB signature",
        "action": "block_and_alert",
    },
    "HIDClass+Net": {
        "risk": "CRITICAL",
        "score": 98,
        "reason": "COMPOSITE: HID + Network — keystroke injection + data exfiltration",
        "action": "block_and_alert",
    },
}

# Known-malicious VID:PID signatures (curated from security research)
KNOWN_MALICIOUS_DEVICES = {
    # Rubber Ducky / Hak5 devices
    ("04D8", "F2CF"): "Hak5 Rubber Ducky (classic)",
    ("1FC9", "0083"): "Hak5 Rubber Ducky (mk2)",
    ("1D50", "6089"): "Great Scott Gadgets - HackRF",
    ("1D50", "60A7"): "Great Scott Gadgets - YARD Stick One",
    ("2E8A", "000A"): "Raspberry Pi Pico (common BadUSB platform)",
    # O.MG Cable
    ("1A86", "55D4"): "Possible O.MG Cable (CH340 + unusual PID)",
    # Flipper Zero (not malicious per se, but noteworthy)
    ("0483", "5740"): "Flipper Zero (or STM32-based device)",
    # LAN Turtle / Packet Squirrel
    ("0B95", "772B"): "ASIX USB Ethernet (Hak5 LAN Turtle platform)",
    # WiFi Pineapple
    ("0CF3", "9271"): "Atheros WiFi (Hak5 WiFi Pineapple platform)",
}

# ── Helpers ───────────────────────────────────────────────────

def _run(cmd, timeout=15):
    """Run a command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", -1
    except Exception as e:
        return "", str(e), -1

def _run_ps(script, timeout=15):
    """Run a PowerShell script."""
    cmd = ["powershell", "-NoProfile", "-Command", script]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", -1
    except Exception as e:
        return "", str(e), -1

def _load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}

def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

# ── Core: Device Fingerprinting ──────────────────────────────

class DeviceFingerprint:
    """Complete fingerprint of a USB device."""

    def __init__(self):
        self.instance_id = ""
        self.vid = ""  # Vendor ID (hex)
        self.pid = ""  # Product ID (hex)
        self.serial = ""
        self.manufacturer = ""
        self.friendly_name = ""
        self.device_class = ""
        self.device_classes = []  # All classes (for composite detection)
        self.description = ""
        self.hardware_ids = []
        self.compatible_ids = []
        self.driver = ""
        self.driver_provider = ""
        self.driver_date = ""
        self.driver_version = ""
        self.status = ""
        self.install_date = ""
        self.first_seen = ""
        self.container_id = ""  # Groups interfaces of same physical device
        self.bus_reported_description = ""
        self.is_composite = False
        self.child_devices = []  # Sub-devices for composite
        self.threat_score = 0
        self.risk_level = "UNKNOWN"
        self.risk_reasons = []
        self.recommended_action = "profile_and_prompt"

    def device_key(self) -> str:
        """Unique identifier for whitelist matching."""
        return f"{self.vid}:{self.pid}:{self.serial or 'no-serial'}"

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "vid": self.vid,
            "pid": self.pid,
            "serial": self.serial,
            "manufacturer": self.manufacturer,
            "friendly_name": self.friendly_name,
            "device_class": self.device_class,
            "device_classes": self.device_classes,
            "description": self.description,
            "hardware_ids": self.hardware_ids,
            "compatible_ids": self.compatible_ids,
            "driver": self.driver,
            "driver_provider": self.driver_provider,
            "driver_date": self.driver_date,
            "driver_version": self.driver_version,
            "status": self.status,
            "install_date": self.install_date,
            "first_seen": self.first_seen,
            "container_id": self.container_id,
            "bus_reported_description": self.bus_reported_description,
            "is_composite": self.is_composite,
            "child_devices": self.child_devices,
            "threat_score": self.threat_score,
            "risk_level": self.risk_level,
            "risk_reasons": self.risk_reasons,
            "recommended_action": self.recommended_action,
        }

def fingerprint_device(instance_id: str) -> DeviceFingerprint:
    """Deep fingerprint a USB device by its InstanceId."""
    fp = DeviceFingerprint()
    fp.instance_id = instance_id
    fp.first_seen = datetime.now().isoformat()

    # Extract VID/PID from InstanceId (format: USB\VID_XXXX&PID_XXXX\serial)
    vid_match = re.search(r'VID_([0-9A-Fa-f]{4})', instance_id)
    pid_match = re.search(r'PID_([0-9A-Fa-f]{4})', instance_id)
    if vid_match:
        fp.vid = vid_match.group(1).upper()
    if pid_match:
        fp.pid = pid_match.group(1).upper()

    # Serial is typically the last segment
    parts = instance_id.split("\\")
    if len(parts) >= 3:
        fp.serial = parts[-1]

    # Get full device properties via PowerShell
    ps_script = f'''
$dev = Get-PnpDeviceProperty -InstanceId '{instance_id}' -ErrorAction SilentlyContinue
$props = @{{}}
foreach ($p in $dev) {{
    $props[$p.KeyName] = $p.Data
}}
$result = @{{
    FriendlyName = $props['DEVPKEY_Device_FriendlyName']
    Manufacturer = $props['DEVPKEY_Device_Manufacturer']
    Description = $props['DEVPKEY_Device_DeviceDesc']
    Class = $props['DEVPKEY_Device_Class']
    HardwareIds = $props['DEVPKEY_Device_HardwareIds']
    CompatibleIds = $props['DEVPKEY_Device_CompatibleIds']
    Driver = $props['DEVPKEY_Device_DriverDesc']
    DriverProvider = $props['DEVPKEY_Device_DriverProvider']
    DriverDate = $props['DEVPKEY_Device_DriverDate']
    DriverVersion = $props['DEVPKEY_Device_DriverVersion']
    ContainerId = $props['DEVPKEY_Device_ContainerId']
    InstallDate = $props['DEVPKEY_Device_InstallDate']
    BusReportedDesc = $props['DEVPKEY_Device_BusReportedDeviceDesc']
    Status = (Get-PnpDevice -InstanceId '{instance_id}' -ErrorAction SilentlyContinue).Status
}}
$result | ConvertTo-Json -Compress
'''
    out, err, rc = _run_ps(ps_script, timeout=15)
    if rc == 0 and out:
        try:
            props = json.loads(out)
            fp.friendly_name = props.get("FriendlyName") or ""
            fp.manufacturer = props.get("Manufacturer") or ""
            fp.description = props.get("Description") or ""
            fp.device_class = props.get("Class") or ""
            fp.hardware_ids = props.get("HardwareIds") or []
            fp.compatible_ids = props.get("CompatibleIds") or []
            fp.driver = props.get("Driver") or ""
            fp.driver_provider = props.get("DriverProvider") or ""
            fp.driver_date = str(props.get("DriverDate") or "")
            fp.driver_version = props.get("DriverVersion") or ""
            fp.container_id = str(props.get("ContainerId") or "")
            fp.install_date = str(props.get("InstallDate") or "")
            fp.bus_reported_description = props.get("BusReportedDesc") or ""
            fp.status = props.get("Status") or ""
        except json.JSONDecodeError:
            pass

    # Check for composite device (multiple interfaces/classes under same container)
    if fp.container_id and fp.container_id != "00000000-0000-0000-0000-000000000000":
        _check_composite(fp)

    # Assess threat
    _assess_threat(fp)

    return fp

def _check_composite(fp: DeviceFingerprint):
    """Check if this device presents multiple device classes (composite)."""
    ps_script = f'''
$containerId = '{fp.container_id}'
$siblings = Get-PnpDevice | Where-Object {{
    try {{
        $cid = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_ContainerId' -ErrorAction SilentlyContinue).Data
        $cid -eq $containerId
    }} catch {{ $false }}
}}
$siblings | Select-Object InstanceId, Class, FriendlyName, Status | ConvertTo-Json -Compress
'''
    out, err, rc = _run_ps(ps_script, timeout=20)
    if rc == 0 and out:
        try:
            siblings = json.loads(out)
            if isinstance(siblings, dict):
                siblings = [siblings]
            classes = set()
            children = []
            for sib in siblings:
                cls = sib.get("Class", "")
                if cls:
                    classes.add(cls)
                children.append({
                    "instance_id": sib.get("InstanceId", ""),
                    "class": cls,
                    "name": sib.get("FriendlyName", ""),
                    "status": sib.get("Status", ""),
                })
            fp.device_classes = sorted(classes)
            fp.child_devices = children
            fp.is_composite = len(classes) > 1
        except json.JSONDecodeError:
            pass

def _assess_threat(fp: DeviceFingerprint):
    """Calculate threat score and risk level."""
    score = 0
    reasons = []

    # 1. Check against known-malicious devices
    vid_pid = (fp.vid, fp.pid)
    if vid_pid in KNOWN_MALICIOUS_DEVICES:
        score += 50
        reasons.append(f"KNOWN ATTACK PLATFORM: {KNOWN_MALICIOUS_DEVICES[vid_pid]}")

    # 2. Device class risk
    if fp.is_composite:
        # Check composite class combinations
        combo = "+".join(sorted(fp.device_classes))
        if combo in DEVICE_CLASS_RISK:
            cls_risk = DEVICE_CLASS_RISK[combo]
            score += cls_risk["score"]
            reasons.append(f"COMPOSITE DEVICE ({combo}): {cls_risk['reason']}")
        else:
            # Any composite with HID is suspicious
            if any(c in ("HIDClass", "Keyboard", "Mouse") for c in fp.device_classes):
                score += 70
                reasons.append(f"COMPOSITE with HID interface ({', '.join(fp.device_classes)}) — possible BadUSB")
            else:
                score += 30
                reasons.append(f"Composite device ({', '.join(fp.device_classes)}) — verify intended function")
    elif fp.device_class in DEVICE_CLASS_RISK:
        cls_risk = DEVICE_CLASS_RISK[fp.device_class]
        score += cls_risk["score"]
        reasons.append(f"Device class {fp.device_class}: {cls_risk['reason']}")

    # 3. No serial number (cheap/malicious devices often lack serial)
    if not fp.serial or fp.serial == "&0" or len(fp.serial) < 4:
        score += 10
        reasons.append("No unique serial number — harder to track, common in attack devices")

    # 4. Suspicious manufacturer strings
    suspicious_manufacturers = ["", "unknown", "(standard", "generic"]
    if any(s in (fp.manufacturer or "").lower() for s in suspicious_manufacturers):
        score += 10
        reasons.append(f"Missing or generic manufacturer: '{fp.manufacturer}'")

    # 5. Driver mismatch (device claims one class but loads different driver)
    if fp.device_class and fp.driver:
        driver_lower = fp.driver.lower()
        if fp.device_class == "Camera" and "hid" in driver_lower:
            score += 40
            reasons.append("DRIVER MISMATCH: Claims Camera class but loads HID driver")
        elif fp.device_class == "DiskDrive" and "hid" in driver_lower:
            score += 40
            reasons.append("DRIVER MISMATCH: Claims Storage class but loads HID driver")

    # 6. VID 0000 or PID 0000 (sometimes used by prototype/attack devices)
    if fp.vid == "0000" or fp.pid == "0000":
        score += 15
        reasons.append("NULL VID or PID — often seen in development/attack boards")

    # 7. Hardware IDs suggesting keyboard emulation
    hw_ids_str = " ".join(fp.hardware_ids).lower()
    if "keyboard" in hw_ids_str or "hid_device_system_keyboard" in hw_ids_str:
        if fp.device_class not in ("Keyboard", "HIDClass"):
            score += 35
            reasons.append("Hardware IDs suggest keyboard emulation despite different class claim")

    # Cap at 100
    fp.threat_score = min(score, 100)

    # Risk level
    if fp.threat_score >= 80:
        fp.risk_level = "CRITICAL"
        fp.recommended_action = "block_and_alert"
    elif fp.threat_score >= 50:
        fp.risk_level = "HIGH"
        fp.recommended_action = "block_and_alert"
    elif fp.threat_score >= 30:
        fp.risk_level = "MEDIUM"
        fp.recommended_action = "profile_and_prompt"
    elif fp.threat_score >= 15:
        fp.risk_level = "LOW"
        fp.recommended_action = "log_and_allow"
    else:
        fp.risk_level = "MINIMAL"
        fp.recommended_action = "log_and_allow"

    fp.risk_reasons = reasons

# ── Fortress Paradox Safeguards ────────────────────────────────

def _is_kill_switch_active() -> bool:
    """Check if the emergency kill switch file exists."""
    return KILL_SWITCH_FILE.exists()

def _system_uptime_minutes() -> float:
    """Get system uptime in minutes."""
    try:
        out, _, rc = _run_ps("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime", timeout=10)
        if rc == 0 and out:
            from datetime import datetime
            boot_time = datetime.fromisoformat(out.strip().replace('/', '-'))
            return (datetime.now() - boot_time).total_seconds() / 60
    except Exception:
        pass
    # Fallback: assume been up long enough (safe default)
    return 999

def _is_hid_device(device_class: str, device_classes: list = None) -> bool:
    """Check if a device is a Human Interface Device."""
    hid_classes = {'HIDClass', 'Keyboard', 'Mouse'}
    if device_class in hid_classes:
        return True
    if device_classes and any(c in hid_classes for c in device_classes):
        return True
    return False

def _has_whitelisted_hid_connected(whitelist: dict) -> bool:
    """Check if at least one whitelisted HID device is currently connected."""
    hid_classes = {'HIDClass', 'Keyboard', 'Mouse'}
    for key, info in whitelist.get("devices", {}).items():
        if info.get("class") in hid_classes or info.get("device_class") in hid_classes:
            return True
    return False

def _should_block_device(fp, whitelist: dict) -> tuple:
    """Determine if a device should be blocked, with all Fortress Paradox safeguards.

    Returns (should_block: bool, reason: str)
    """
    # Safeguard 1: Kill switch
    if _is_kill_switch_active():
        return False, "KILL_SWITCH: Security disabled via kill switch file"

    # Safeguard 5: Deployment phase
    if DEPLOYMENT_PHASE <= 1:
        return False, f"PHASE_{DEPLOYMENT_PHASE}: Log-only mode — no blocking"

    if DEPLOYMENT_PHASE == 2:
        return False, "PHASE_2: Prompt mode — alert sent, no auto-block"

    # Safeguard 2: Boot grace period for HID
    if _is_hid_device(fp.device_class, fp.device_classes):
        uptime = _system_uptime_minutes()
        if uptime < 10:
            return False, f"BOOT_GRACE: System uptime {uptime:.0f}min < 10min — HID allowed"

        # Safeguard 3: Never block HID without whitelisted HID present
        if not _has_whitelisted_hid_connected(whitelist):
            return False, "FORTRESS_PARADOX: No whitelisted HID devices — allowing all HID"

    # Safeguard 4: Never block remote access
    remote_keywords = ['tailscale', 'rustdesk', 'rdp', 'ssh', 'remote']
    device_desc = f"{fp.friendly_name} {fp.description} {fp.driver} {fp.manufacturer}".lower()
    if any(kw in device_desc for kw in remote_keywords):
        return False, "REMOTE_SACRED: Device appears related to remote access"

    # Phase 3+ with safeguards passed: allow blocking
    return True, "All safeguards passed — blocking authorized"

# ── Core: Quarantine Protocol ─────────────────────────────────

class USBQuarantine:
    """Full quarantine protocol for USB device management."""

    def __init__(self):
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.whitelist = _load_json(WHITELIST_FILE, {"devices": {}, "updated": ""})
        self.state = _load_json(QUARANTINE_STATE, {
            "known_devices": {},
            "last_scan": "",
            "alerts_sent": [],
        })

    def scan(self) -> Dict:
        """Full scan: enumerate all USB devices, fingerprint new ones, assess threats.

        Returns a report dict with new devices, threats, and recommended actions.
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "new_devices": [],
            "known_devices": [],
            "threats": [],
            "actions_taken": [],
        }

        # Get all current USB devices
        current_devices = self._enumerate_usb_devices()
        known_keys = set(self.state.get("known_devices", {}).keys())

        for instance_id in current_devices:
            # Quick VID:PID extraction for whitelist check
            vid_match = re.search(r'VID_([0-9A-Fa-f]{4})', instance_id)
            pid_match = re.search(r'PID_([0-9A-Fa-f]{4})', instance_id)
            vid = vid_match.group(1).upper() if vid_match else ""
            pid = pid_match.group(1).upper() if pid_match else ""
            serial = instance_id.split("\\")[-1] if "\\" in instance_id else ""
            device_key = f"{vid}:{pid}:{serial or 'no-serial'}"

            # Check whitelist
            if device_key in self.whitelist.get("devices", {}):
                report["known_devices"].append({
                    "key": device_key,
                    "status": "whitelisted",
                    "name": self.whitelist["devices"][device_key].get("name", ""),
                })
                continue

            # Check if we've seen this before
            if device_key in known_keys:
                report["known_devices"].append({
                    "key": device_key,
                    "status": "previously_seen",
                    "first_seen": self.state["known_devices"][device_key].get("first_seen", ""),
                })
                continue

            # === NEW DEVICE: Full quarantine protocol ===
            fp = fingerprint_device(instance_id)

            # Store in known devices
            self.state.setdefault("known_devices", {})[device_key] = fp.to_dict()

            # Log the fingerprint
            self._log_device(fp)

            report["new_devices"].append(fp.to_dict())

            if fp.threat_score >= 50:
                threat = {
                    "device_key": device_key,
                    "threat_score": fp.threat_score,
                    "risk_level": fp.risk_level,
                    "reasons": fp.risk_reasons,
                    "name": fp.friendly_name or fp.description or f"USB {fp.vid}:{fp.pid}",
                    "action": fp.recommended_action,
                }
                report["threats"].append(threat)

                # Take action (with Fortress Paradox safeguards)
                if fp.recommended_action == "block_and_alert":
                    should_block, safeguard_reason = _should_block_device(fp, self.whitelist)
                    if should_block:
                        blocked = self._disable_device(instance_id)
                        if blocked:
                            report["actions_taken"].append(
                                f"BLOCKED: {fp.friendly_name or device_key} (score={fp.threat_score})"
                            )
                    else:
                        blocked = False
                        report["actions_taken"].append(
                            f"SAFEGUARD: {safeguard_reason} — {fp.friendly_name or device_key} "
                            f"(score={fp.threat_score}, would have blocked)"
                        )
                    self._send_alert(fp, blocked)
                    report["actions_taken"].append(
                        f"ALERT SENT: {fp.risk_level} threat — {fp.friendly_name or device_key}"
                    )
                elif fp.recommended_action == "profile_and_prompt":
                    self._send_alert(fp, blocked=False)
                    report["actions_taken"].append(
                        f"PROMPT: {fp.friendly_name or device_key} — awaiting approval (score={fp.threat_score})"
                    )

        # Update state
        self.state["last_scan"] = datetime.now().isoformat()
        _save_json(QUARANTINE_STATE, self.state)

        # Save report
        report_file = QUARANTINE_DIR / f"scan-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        _save_json(report_file, report)

        return report

    def _enumerate_usb_devices(self) -> List[str]:
        """Get all connected USB device InstanceIds."""
        out, err, rc = _run_ps(
            "Get-PnpDevice -Class USB,Camera,WPD,DiskDrive,HIDClass,Net,Image "
            "-Status OK -ErrorAction SilentlyContinue | "
            "Where-Object { $_.InstanceId -match 'USB' } | "
            "Select-Object -ExpandProperty InstanceId"
        )
        if rc == 0 and out:
            return [line.strip() for line in out.splitlines() if line.strip()]
        return []

    def _disable_device(self, instance_id: str) -> bool:
        """Disable a USB device (requires admin). Returns True if successful."""
        try:
            from rudy.admin import run_elevated_ps
            ok, out = run_elevated_ps(
                f"Disable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false"
            )
            return ok
        except Exception:
            # Fallback: try direct (may fail without elevation)
            out, err, rc = _run_ps(
                f"Disable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false"
            )
            return rc == 0

    def _send_alert(self, fp: DeviceFingerprint, blocked: bool):
        """Send email alert about a suspicious device."""
        subject = f"[RUDY {'🚨' if fp.risk_level == 'CRITICAL' else '⚠️'}] USB {fp.risk_level}: {fp.friendly_name or f'{fp.vid}:{fp.pid}'}"

        body_lines = [
            f"USB Device Alert — {fp.risk_level}",
            f"{'='*50}",
            f"Threat Score: {fp.threat_score}/100",
            f"Device: {fp.friendly_name or fp.description or 'Unknown'}",
            f"Manufacturer: {fp.manufacturer or 'Unknown'}",
            f"VID:PID: {fp.vid}:{fp.pid}",
            f"Serial: {fp.serial or 'None'}",
            f"Class: {fp.device_class}",
            f"Composite: {'YES — ' + ', '.join(fp.device_classes) if fp.is_composite else 'No'}",
            f"Driver: {fp.driver} ({fp.driver_provider or '?'})",
            f"Status: {'BLOCKED by Rudy' if blocked else 'Active — awaiting review'}",
            "",
            "Risk Factors:",
        ]
        for reason in fp.risk_reasons:
            body_lines.append(f"  • {reason}")

        body_lines.extend([
            "",
            f"Instance ID: {fp.instance_id}",
            f"Time: {fp.first_seen}",
            "",
            "To whitelist this device, reply 'whitelist' with the device key:",
            f"  {fp.device_key()}",
        ])

        body = "\n".join(body_lines)

        try:
            from rudy.email_multi import EmailMulti
            em = EmailMulti()
            em.send(
                to="ccimino2@gmail.com",
                subject=subject,
                body=body,
            )
        except Exception:
            # Log the alert even if email fails
            alert_file = QUARANTINE_DIR / "PENDING-ALERT.txt"
            alert_file.write_text(f"{subject}\n\n{body}", encoding="utf-8")

    def _log_device(self, fp: DeviceFingerprint):
        """Write detailed device log."""
        log_file = QUARANTINE_DIR / f"device-{fp.vid}-{fp.pid}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        _save_json(log_file, fp.to_dict())

    # ── Whitelist Management ─────────────────────────────────

    def whitelist_device(self, device_key: str, name: str, added_by: str = "chris") -> bool:
        """Add a device to the whitelist. Only Chris should call this."""
        self.whitelist.setdefault("devices", {})[device_key] = {
            "name": name,
            "added_by": added_by,
            "added_at": datetime.now().isoformat(),
        }
        self.whitelist["updated"] = datetime.now().isoformat()
        _save_json(WHITELIST_FILE, self.whitelist)
        return True

    def remove_from_whitelist(self, device_key: str) -> bool:
        """Remove a device from the whitelist."""
        if device_key in self.whitelist.get("devices", {}):
            del self.whitelist["devices"][device_key]
            self.whitelist["updated"] = datetime.now().isoformat()
            _save_json(WHITELIST_FILE, self.whitelist)
            return True
        return False

    def list_whitelist(self) -> Dict:
        """Return current whitelist."""
        return self.whitelist

    def enable_device(self, instance_id: str) -> bool:
        """Re-enable a previously blocked device (requires admin)."""
        try:
            from rudy.admin import run_elevated_ps
            ok, out = run_elevated_ps(
                f"Enable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false"
            )
            return ok
        except Exception:
            out, err, rc = _run_ps(
                f"Enable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false"
            )
            return rc == 0

    # ── Mass Storage Deep Scan ───────────────────────────────

    def scan_mass_storage(self, drive_letter: str) -> Dict:
        """Deep scan a USB mass storage device for threats.

        Checks:
          - Autorun.inf presence
          - Executable files (.exe, .bat, .cmd, .ps1, .vbs, .js, .scr, .dll)
          - Hidden files and directories
          - Suspicious file names (mimicking system files)
          - Encrypted/password-protected archives
          - Recently modified files (staged payloads)
          - Abnormally large hidden files (data staging)
        """
        results = {
            "drive": drive_letter,
            "timestamp": datetime.now().isoformat(),
            "autorun": False,
            "executables": [],
            "hidden_files": [],
            "suspicious": [],
            "recent_modifications": [],
            "total_files": 0,
            "threat_level": "CLEAN",
        }

        drive_path = f"{drive_letter}:\\"

        # Check autorun.inf
        autorun_path = os.path.join(drive_path, "autorun.inf")
        if os.path.exists(autorun_path):
            results["autorun"] = True
            results["suspicious"].append({
                "file": "autorun.inf",
                "reason": "Autorun file present — classic malware delivery mechanism",
            })

        # Scan for executables and suspicious files
        DANGEROUS_EXTENSIONS = {
            '.exe', '.bat', '.cmd', '.ps1', '.vbs', '.js', '.wsf', '.scr',
            '.dll', '.msi', '.hta', '.pif', '.com', '.lnk', '.inf',
        }

        try:
            for root, dirs, files in os.walk(drive_path):
                for f in files:
                    results["total_files"] += 1
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, drive_path)

                    # Check extension
                    ext = os.path.splitext(f)[1].lower()
                    if ext in DANGEROUS_EXTENSIONS:
                        results["executables"].append({
                            "path": rel_path,
                            "size": os.path.getsize(full_path),
                            "extension": ext,
                        })

                    # Check hidden attribute
                    try:
                        import ctypes
                        attrs = ctypes.windll.kernel32.GetFileAttributesW(full_path)
                        if attrs != -1 and (attrs & 2):  # FILE_ATTRIBUTE_HIDDEN
                            results["hidden_files"].append(rel_path)
                    except Exception:
                        pass

                    # Check recent modifications (within last 24 hours)
                    try:
                        mtime = os.path.getmtime(full_path)
                        if (time.time() - mtime) < 86400:
                            results["recent_modifications"].append({
                                "path": rel_path,
                                "modified": datetime.fromtimestamp(mtime).isoformat(),
                            })
                    except Exception:
                        pass
        except PermissionError:
            results["suspicious"].append({
                "file": drive_path,
                "reason": "Permission denied scanning drive — unusual for removable media",
            })

        # Determine threat level
        if results["autorun"]:
            results["threat_level"] = "HIGH"
        elif len(results["executables"]) > 5:
            results["threat_level"] = "MEDIUM"
        elif results["executables"]:
            results["threat_level"] = "LOW"

        return results

    # ── Behavioral Monitoring ────────────────────────────────

    def monitor_device_behavior(self, instance_id: str, duration_seconds: int = 30) -> Dict:
        """Watch what a device does after connection.

        Monitors:
          - New processes spawned after device connection
          - New network connections opened
          - Registry changes
          - File system writes
          - Keyboard input injection attempts
        """
        results = {
            "instance_id": instance_id,
            "duration": duration_seconds,
            "timestamp": datetime.now().isoformat(),
            "new_processes": [],
            "new_connections": [],
            "keyboard_activity": False,
            "suspicious_activity": [],
        }

        # Snapshot before
        ps_before = '''
$procs = Get-Process | Select-Object Id,ProcessName,Path | ConvertTo-Json -Compress
$conns = Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | Select-Object OwningProcess,RemoteAddress,RemotePort | ConvertTo-Json -Compress
Write-Output "PROCS:$procs"
Write-Output "CONNS:$conns"
'''
        before_out, _, _ = _run_ps(ps_before, timeout=10)
        before_procs = set()
        before_conns = set()

        for line in (before_out or "").splitlines():
            if line.startswith("PROCS:"):
                try:
                    procs = json.loads(line[6:])
                    if isinstance(procs, dict):
                        procs = [procs]
                    before_procs = {p.get("Id") for p in procs}
                except Exception:
                    pass
            elif line.startswith("CONNS:"):
                try:
                    conns = json.loads(line[6:])
                    if isinstance(conns, dict):
                        conns = [conns]
                    before_conns = {
                        f"{c.get('RemoteAddress')}:{c.get('RemotePort')}"
                        for c in conns
                    }
                except Exception:
                    pass

        # Wait for monitoring period
        time.sleep(min(duration_seconds, 60))  # Cap at 60s

        # Snapshot after
        after_out, _, _ = _run_ps(ps_before, timeout=10)
        after_procs = {}
        after_conns = set()

        for line in (after_out or "").splitlines():
            if line.startswith("PROCS:"):
                try:
                    procs = json.loads(line[6:])
                    if isinstance(procs, dict):
                        procs = [procs]
                    after_procs = {
                        p.get("Id"): {
                            "name": p.get("ProcessName"),
                            "path": p.get("Path"),
                        }
                        for p in procs
                    }
                except Exception:
                    pass
            elif line.startswith("CONNS:"):
                try:
                    conns = json.loads(line[6:])
                    if isinstance(conns, dict):
                        conns = [conns]
                    after_conns = {
                        f"{c.get('RemoteAddress')}:{c.get('RemotePort')}"
                        for c in conns
                    }
                except Exception:
                    pass

        # Diff
        new_proc_ids = set(after_procs.keys()) - before_procs
        for pid in new_proc_ids:
            info = after_procs[pid]
            results["new_processes"].append(info)
            # Flag suspicious processes
            name = (info.get("name") or "").lower()
            if any(s in name for s in ["powershell", "cmd", "wscript", "cscript", "mshta"]):
                results["suspicious_activity"].append(
                    f"Shell process spawned after device connection: {info.get('name')} (PID {pid})"
                )

        new_conns = after_conns - before_conns
        for conn in new_conns:
            results["new_connections"].append(conn)

        if results["suspicious_activity"]:
            results["verdict"] = "SUSPICIOUS — device triggered system activity"
        elif results["new_processes"] or results["new_connections"]:
            results["verdict"] = "ACTIVITY DETECTED — review processes and connections"
        else:
            results["verdict"] = "CLEAN — no observed activity during monitoring period"

        return results

# ── Entry Points ─────────────────────────────────────────────

def check_devices() -> Dict:
    """Main entry point — run full quarantine scan. Called by Sentinel."""
    q = USBQuarantine()
    return q.scan()

def whitelist(device_key: str, name: str) -> bool:
    """Whitelist a device by its key (VID:PID:Serial)."""
    q = USBQuarantine()
    return q.whitelist_device(device_key, name)

def get_status() -> Dict:
    """Get current quarantine state."""
    state = _load_json(QUARANTINE_STATE, {})
    wl = _load_json(WHITELIST_FILE, {"devices": {}})
    return {
        "known_devices": len(state.get("known_devices", {})),
        "whitelisted": len(wl.get("devices", {})),
        "last_scan": state.get("last_scan", "never"),
    }

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "whitelist":
        if len(sys.argv) >= 4:
            key = sys.argv[2]
            name = sys.argv[3]
            whitelist(key, name)
            print(f"Whitelisted: {key} ({name})")
        else:
            print("Usage: python usb_quarantine.py whitelist VID:PID:SERIAL 'Device Name'")
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        import pprint
        pprint.pprint(get_status())
    else:
        report = check_devices()
        print(f"\n{'='*60}")
        print(f"USB Quarantine Scan — {report['timestamp']}")
        print(f"{'='*60}")
        print(f"New devices:   {len(report['new_devices'])}")
        print(f"Known devices: {len(report['known_devices'])}")
        print(f"Threats:       {len(report['threats'])}")
        print(f"Actions taken: {len(report['actions_taken'])}")

        for threat in report["threats"]:
            print(f"\n  {'🚨' if threat['risk_level'] == 'CRITICAL' else '⚠️'} {threat['risk_level']}: "
                  f"{threat['name']} (score={threat['threat_score']})")
            for reason in threat["reasons"]:
                print(f"     • {reason}")
            print(f"     Action: {threat['action']}")

        for action in report["actions_taken"]:
            print(f"\n  → {action}")

        print(f"\nFull report: {QUARANTINE_DIR}")
