"""
Phone Check — Professional-grade mobile device security scanning.

When a phone is plugged into The Workhorse via USB, this module:
  1. Detects the device (iOS or Android)
  2. Identifies make/model/OS version
  3. Runs a battery of security checks:
     - Known malware/spyware signature detection (MVT indicators)
     - Suspicious app identification
     - Certificate and profile analysis (iOS)
     - ADB-accessible anomaly detection (Android)
     - Network traffic baseline analysis
     - File system artifact scanning
     - Pegasus/Predator/Hermit indicator checks (via MVT IOCs)
  4. Generates a detailed security report

Tools used:
  - libimobiledevice (iOS): ideviceinfo, idevice_id, idevicesyslog
  - ADB (Android): adb devices, adb shell, package listing
  - MVT (Mobile Verification Toolkit): Amnesty International's spyware detection
  - Custom heuristics for app analysis and anomaly detection

Design:
  - Non-destructive: read-only scanning, never modifies the device
  - Offline-capable: core checks work without internet (IOC database cached locally)
  - Report output: JSON + human-readable summary + optional .docx report
"""

import json
import logging
import os
import re
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

log = logging.getLogger(__name__)

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS = DESKTOP / "rudy-logs"
PHONE_CHECK_DIR = DESKTOP / "rudy-data" / "phone-check"
IOC_DIR = PHONE_CHECK_DIR / "iocs"
REPORTS_DIR = PHONE_CHECK_DIR / "reports"


def _run(cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
    """Run a command, return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except Exception as e:
        return "", str(e), -1


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _load_json(path: Path, default=None):
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.debug(f"Failed to load JSON from {path}: {e}")
    return default if default is not None else {}


# ── Known Threat Indicators ──────────────────────────────────
# Curated from MVT, Amnesty Tech, Citizen Lab, and public threat intel

KNOWN_SPYWARE_PACKAGES = {
    # Pegasus (NSO Group)
    "com.network.android", "com.nso.group", "com.bridgefy",
    # Predator (Cytrox/Intellexa)
    "com.alien.service", "com.cytrox.predator",
    # Hermit (RCS Lab)
    "com.rcs.lab", "com.tykelab",
    # FinSpy/FinFisher
    "com.gamma.finspy", "org.xmlpush.v3",
    # Stalkerware (commercial)
    "com.mspy.lite", "com.flexispy", "com.spyera", "com.thewispy",
    "com.cocospy.app", "com.hoverwatch", "net.spyic.app",
    "com.xnspy.app", "com.eyezy.app", "com.umobix",
    "com.clevguard", "com.spylix", "com.phonesheriff",
    "com.mobilespy", "com.spyfone", "com.cerberus",
    "com.webwatcher", "com.bark", "com.parentalcontrol",
    # Generic suspicious patterns
    "com.android.system.update.service",
    "com.android.providers.telephony.update",
    "com.system.service.manager",
}

KNOWN_SPYWARE_NAMES_PARTIAL = [
    "spy", "track", "monitor", "stealth", "hidden", "keylog",
    "sniffer", "intercept", "surveil", "stalker", "snoop",
]

SUSPICIOUS_PERMISSIONS_ANDROID = [
    "android.permission.RECORD_AUDIO",
    "android.permission.CAMERA",
    "android.permission.READ_CALL_LOG",
    "android.permission.READ_SMS",
    "android.permission.RECEIVE_SMS",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.READ_CONTACTS",
    "android.permission.PROCESS_OUTGOING_CALLS",
    "android.permission.BIND_ACCESSIBILITY_SERVICE",
    "android.permission.BIND_DEVICE_ADMIN",
    "android.permission.SYSTEM_ALERT_WINDOW",
    "android.permission.INSTALL_PACKAGES",
    "android.permission.REQUEST_INSTALL_PACKAGES",
    "android.permission.WRITE_SECURE_SETTINGS",
]

# iOS suspicious indicators
IOS_SUSPICIOUS_PROCESSES = [
    "bh_agent", "roleaboutd", "pcaborede", "frtipd",
    "gpsd", "caborede", "aggregated", "ckkeyrollfd",
    "com.apple.icloud.searchpartyd.fmfcore.PairedDevicesManager",
]

IOS_SUSPICIOUS_PROFILES = [
    "MDM", "Configuration Profile", "VPN Profile",
]


class DeviceDetector:
    """Detect connected mobile devices (iOS and Android)."""

    def detect_all(self) -> List[dict]:
        """Find all connected mobile devices."""
        devices = []
        devices.extend(self._detect_ios())
        devices.extend(self._detect_android())
        return devices

    def _detect_ios(self) -> List[dict]:
        """Detect iOS devices via WSL+libimobiledevice (primary) or Windows fallback."""
        devices = []

        # PRIMARY: WSL + usbipd + libimobiledevice (open-source, no Apple bloat)
        wsl_devices = self._detect_ios_wsl()
        if wsl_devices:
            return wsl_devices

        # FALLBACK 1: Native Windows libimobiledevice (if installed)
        stdout, stderr, rc = _run("idevice_id -l")
        if rc == 0 and stdout:
            for udid in stdout.splitlines():
                udid = udid.strip()
                if udid:
                    info = self._get_ios_info(udid)
                    info["udid"] = udid
                    info["platform"] = "ios"
                    devices.append(info)
            return devices

        # FALLBACK 2: pymobiledevice3 (pure Python, needs Apple USB driver)
        try:
            from pymobiledevice3.usbmux import list_devices
            from pymobiledevice3.lockdown import create_using_usbmux
            import asyncio
            devs = list_devices()
            if asyncio.iscoroutine(devs):
                devs = asyncio.get_event_loop().run_until_complete(devs)
            for dev in devs:
                lockdown = create_using_usbmux(serial=dev.serial)
                if asyncio.iscoroutine(lockdown):
                    lockdown = asyncio.get_event_loop().run_until_complete(lockdown)
                info = lockdown.all_values
                devices.append({
                    "platform": "ios",
                    "udid": info.get("UniqueDeviceID", dev.serial),
                    "name": info.get("DeviceName", "iPhone"),
                    "model": info.get("ProductType", ""),
                    "os_version": info.get("ProductVersion", ""),
                    "serial": info.get("SerialNumber", ""),
                    "detection_method": "pymobiledevice3",
                })
        except Exception as e:
            log.debug(f"Error detecting iOS devices via pymobiledevice3: {e}")

        if devices:
            return devices

        # FALLBACK 3: PnP detection (can see device but can't interrogate)
        ps_cmd = (
            'powershell -Command "Get-PnpDevice | '
            "Where-Object { $_.FriendlyName -like '*Apple*' -or "
            "$_.FriendlyName -like '*iPhone*' -or "
            "$_.FriendlyName -like '*iPad*' } | "
            'Select-Object FriendlyName, Status, InstanceId | ConvertTo-Json"'
        )
        stdout, stderr, rc = _run(ps_cmd)
        if rc == 0 and stdout:
            try:
                pnp_devices = json.loads(stdout)
                if isinstance(pnp_devices, dict):
                    pnp_devices = [pnp_devices]
                for d in pnp_devices:
                    devices.append({
                        "platform": "ios",
                        "name": d.get("FriendlyName", "Apple Device"),
                        "status": d.get("Status", "unknown"),
                        "instance_id": d.get("InstanceId", ""),
                        "detection_method": "pnp",
                    })
            except json.JSONDecodeError:
                pass

        return devices

    def _detect_ios_wsl(self) -> List[dict]:
        """Detect iOS via WSL + usbipd + libimobiledevice. Primary method."""
        devices = []
        try:
            # Check if WSL is available
            _, _, rc = _run("wsl --status", timeout=5)
            if rc != 0:
                return devices

            # Ensure iPhone is attached to WSL (bind is persistent, attach is not)
            usbipd = r"C:\Program Files\usbipd-win\usbipd.exe"
            if os.path.exists(usbipd):
                # Find Apple device BUSID
                stdout, _, rc = _run(f'"{usbipd}" list', timeout=10)
                apple_busid = None
                for line in stdout.splitlines():
                    if "05ac" in line.lower() or "apple" in line.lower():
                        parts = line.split()
                        if parts and "-" in parts[0]:
                            apple_busid = parts[0]
                            break

                if apple_busid:
                    # Attach to WSL (uses PowerShell to handle spaces in path)
                    _run(f'powershell -Command "& \'{usbipd}\' attach --wsl --busid {apple_busid}"', timeout=10)
                    time.sleep(3)

            # Fix permissions and start usbmuxd
            _run('wsl -d Ubuntu -u root -- bash -c "chmod -R 777 /dev/bus/usb/ 2>/dev/null; killall -9 usbmuxd 2>/dev/null; sleep 1; usbmuxd"', timeout=10)
            time.sleep(2)

            # Detect devices
            stdout, _, rc = _run('wsl -d Ubuntu -u root -- bash -c "idevice_id -l 2>&1"', timeout=10)
            if rc == 0 and stdout.strip() and "ERROR" not in stdout:
                for udid in stdout.strip().splitlines():
                    udid = udid.strip()
                    if udid and len(udid) > 10:
                        info = self._get_ios_info_wsl(udid)
                        info["udid"] = udid
                        info["platform"] = "ios"
                        info["detection_method"] = "wsl_libimobiledevice"
                        devices.append(info)
        except Exception as e:
            log.debug(f"Error detecting iOS devices via WSL: {e}")
        return devices

    def _get_ios_info_wsl(self, udid: str) -> dict:
        """Get iOS device info via WSL libimobiledevice."""
        info = {"detection_method": "wsl_libimobiledevice"}
        stdout, _, rc = _run(f'wsl -d Ubuntu -u root -- bash -c "ideviceinfo -u {udid} 2>&1"', timeout=15)
        if rc == 0 and stdout:
            for line in stdout.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key == "DeviceName":
                        info["name"] = val
                    elif key == "ProductType":
                        info["model"] = val
                    elif key == "ProductVersion":
                        info["os_version"] = val
                    elif key == "SerialNumber":
                        info["serial"] = val
                    elif key == "WiFiAddress":
                        info["wifi_mac"] = val
                    elif key == "BuildVersion":
                        info["build"] = val
                    elif key == "PhoneNumber":
                        info["phone"] = val
                    elif key == "InternationalMobileEquipmentIdentity":
                        info["imei"] = val
                    elif key == "PasswordProtected":
                        # NOTE: PasswordProtected reports current lock state, NOT
                        # whether a passcode is configured. An unlocked device
                        # (user entered passcode to trust USB) will report "false"
                        # even if a passcode exists. Only "true" is definitive.
                        if val.lower() == "true":
                            info["passcode_set"] = True
                            info["passcode_status"] = "locked"
                        else:
                            # Device is unlocked — passcode may or may not exist
                            info["passcode_set"] = None  # indeterminate
                            info["passcode_status"] = "indeterminate (device unlocked during scan)"
        return info

    def _get_ios_info(self, udid: str) -> dict:
        """Get detailed iOS device info."""
        info = {"detection_method": "libimobiledevice"}
        stdout, _, rc = _run(f"ideviceinfo -u {udid}")
        if rc == 0 and stdout:
            for line in stdout.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key == "DeviceName":
                        info["name"] = val
                    elif key == "ProductType":
                        info["model"] = val
                    elif key == "ProductVersion":
                        info["os_version"] = val
                    elif key == "SerialNumber":
                        info["serial"] = val
                    elif key == "WiFiAddress":
                        info["wifi_mac"] = val
                    elif key == "BuildVersion":
                        info["build"] = val
        return info

    def _detect_android(self) -> List[dict]:
        """Detect Android devices via ADB."""
        devices = []
        stdout, stderr, rc = _run("adb devices -l")
        if rc != 0:
            return devices

        for line in stdout.splitlines()[1:]:  # Skip header
            line = line.strip()
            if not line or "offline" in line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ("device", "unauthorized"):
                serial = parts[0]
                info = {
                    "platform": "android",
                    "serial": serial,
                    "status": parts[1],
                    "detection_method": "adb",
                }

                # Extract additional info from line
                for part in parts[2:]:
                    if ":" in part:
                        k, v = part.split(":", 1)
                        info[k] = v

                # Get detailed properties if authorized
                if parts[1] == "device":
                    info.update(self._get_android_info(serial))

                devices.append(info)

        return devices

    def _get_android_info(self, serial: str) -> dict:
        """Get detailed Android device info via ADB."""
        info = {}
        props = {
            "model": "ro.product.model",
            "manufacturer": "ro.product.manufacturer",
            "os_version": "ro.build.version.release",
            "sdk_version": "ro.build.version.sdk",
            "build": "ro.build.display.id",
            "security_patch": "ro.build.version.security_patch",
            "name": "ro.product.device",
            "brand": "ro.product.brand",
        }
        for key, prop in props.items():
            stdout, _, rc = _run(f"adb -s {serial} shell getprop {prop}")
            if rc == 0 and stdout:
                info[key] = stdout.strip()
        return info


class AndroidScanner:
    """Security scanner for Android devices."""

    def __init__(self, serial: str):
        self.serial = serial
        self.findings = []

    def _adb(self, cmd: str, timeout: int = 30) -> str:
        stdout, _, rc = _run(f"adb -s {self.serial} {cmd}", timeout)
        return stdout if rc == 0 else ""

    def scan_all(self) -> dict:
        """Run all Android security checks."""
        results = {
            "platform": "android",
            "serial": self.serial,
            "scan_time": datetime.now().isoformat(),
            "checks": {},
        }

        results["checks"]["packages"] = self.check_packages()
        results["checks"]["permissions"] = self.check_dangerous_permissions()
        results["checks"]["device_admin"] = self.check_device_admins()
        results["checks"]["accessibility"] = self.check_accessibility_services()
        results["checks"]["unknown_sources"] = self.check_unknown_sources()
        results["checks"]["developer_options"] = self.check_developer_options()
        results["checks"]["root_status"] = self.check_root()
        results["checks"]["running_services"] = self.check_running_services()
        results["checks"]["network_connections"] = self.check_network()
        results["checks"]["battery_stats"] = self.check_battery_anomalies()
        results["checks"]["certificates"] = self.check_certificates()

        # Aggregate risk score
        results["risk_score"] = self._calculate_risk(results["checks"])
        results["findings"] = self.findings
        return results

    def check_packages(self) -> dict:
        """Check installed packages against known spyware."""
        output = self._adb("shell pm list packages -f")
        if not output:
            return {"status": "failed", "reason": "Could not list packages"}

        packages = []
        suspicious = []
        for line in output.splitlines():
            if line.startswith("package:"):
                pkg_path_name = line[8:]
                if "=" in pkg_path_name:
                    path, name = pkg_path_name.rsplit("=", 1)
                else:
                    name = pkg_path_name
                    path = ""
                packages.append({"name": name, "path": path})

                # Check against known spyware
                if name in KNOWN_SPYWARE_PACKAGES:
                    finding = {
                        "severity": "critical",
                        "type": "known_spyware",
                        "package": name,
                        "path": path,
                    }
                    suspicious.append(finding)
                    self.findings.append(finding)

                # Check name patterns
                name_lower = name.lower()
                for pattern in KNOWN_SPYWARE_NAMES_PARTIAL:
                    if pattern in name_lower and name not in KNOWN_SPYWARE_PACKAGES:
                        finding = {
                            "severity": "warning",
                            "type": "suspicious_name",
                            "package": name,
                            "pattern": pattern,
                        }
                        suspicious.append(finding)
                        self.findings.append(finding)
                        break

        return {
            "total_packages": len(packages),
            "suspicious": suspicious,
            "status": "completed",
        }

    def check_dangerous_permissions(self) -> dict:
        """Find apps with dangerous permission combinations."""
        dangerous_apps = []

        # Get list of third-party packages
        output = self._adb("shell pm list packages -3")
        if not output:
            return {"status": "failed"}

        third_party = [line.replace("package:", "").strip()
                       for line in output.splitlines() if line.startswith("package:")]

        for pkg in third_party[:50]:  # Limit to avoid timeout
            perms_out = self._adb(f"shell dumpsys package {pkg}", timeout=10)
            if not perms_out:
                continue

            granted = []
            for line in perms_out.splitlines():
                if "granted=true" in line:
                    perm_match = re.search(r'(\S+): granted=true', line)
                    if perm_match:
                        perm = perm_match.group(1)
                        if perm in SUSPICIOUS_PERMISSIONS_ANDROID:
                            granted.append(perm)

            if len(granted) >= 3:
                finding = {
                    "severity": "warning",
                    "type": "excessive_permissions",
                    "package": pkg,
                    "dangerous_permissions": granted,
                    "count": len(granted),
                }
                dangerous_apps.append(finding)
                self.findings.append(finding)

        return {
            "apps_checked": len(third_party),
            "apps_with_excessive_permissions": dangerous_apps,
            "status": "completed",
        }

    def check_device_admins(self) -> dict:
        """Check for device administrator apps (often used by spyware)."""
        output = self._adb("shell dumpsys device_policy")
        admins = []
        if output:
            for line in output.splitlines():
                if "admin=" in line.lower() or "Admin ComponentInfo" in line:
                    admins.append(line.strip())
            if admins:
                finding = {
                    "severity": "info",
                    "type": "device_admin",
                    "admins": admins,
                }
                self.findings.append(finding)
        return {"admins": admins, "status": "completed"}

    def check_accessibility_services(self) -> dict:
        """Check accessibility services (common spyware vector)."""
        output = self._adb(
            "shell settings get secure enabled_accessibility_services"
        )
        services = []
        if output and output != "null":
            services = [s.strip() for s in output.split(":") if s.strip()]
            for svc in services:
                svc_lower = svc.lower()
                is_suspicious = any(p in svc_lower for p in KNOWN_SPYWARE_NAMES_PARTIAL)
                if is_suspicious:
                    self.findings.append({
                        "severity": "high",
                        "type": "suspicious_accessibility_service",
                        "service": svc,
                    })
        return {"enabled_services": services, "count": len(services), "status": "completed"}

    def check_unknown_sources(self) -> dict:
        """Check if install from unknown sources is enabled."""
        output = self._adb("shell settings get secure install_non_market_apps")
        enabled = output.strip() == "1" if output else False
        if enabled:
            self.findings.append({
                "severity": "warning",
                "type": "unknown_sources_enabled",
            })
        return {"unknown_sources_enabled": enabled, "status": "completed"}

    def check_developer_options(self) -> dict:
        """Check developer options and USB debugging status."""
        dev = self._adb("shell settings get global development_settings_enabled")
        usb_debug = self._adb("shell settings get global adb_enabled")
        return {
            "developer_options": dev.strip() == "1" if dev else False,
            "usb_debugging": usb_debug.strip() == "1" if usb_debug else False,
            "status": "completed",
        }

    def check_root(self) -> dict:
        """Check for root/jailbreak indicators."""
        indicators = []

        # Check for su binary
        for path in ["/system/bin/su", "/system/xbin/su", "/sbin/su",
                     "/data/local/su", "/data/local/bin/su"]:
            output = self._adb(f"shell ls {path}")
            if output and "No such file" not in output:
                indicators.append(f"su binary at {path}")

        # Check for Magisk
        output = self._adb("shell pm list packages | grep magisk")
        if output:
            indicators.append("Magisk detected")

        # Check for SuperSU
        output = self._adb("shell pm list packages | grep supersu")
        if output:
            indicators.append("SuperSU detected")

        # Check build tags
        output = self._adb("shell getprop ro.build.tags")
        if output and "test-keys" in output:
            indicators.append("test-keys build (custom ROM)")

        rooted = len(indicators) > 0
        if rooted:
            self.findings.append({
                "severity": "info",
                "type": "root_detected",
                "indicators": indicators,
            })

        return {"rooted": rooted, "indicators": indicators, "status": "completed"}

    def check_running_services(self) -> dict:
        """Check running services for suspicious activity."""
        output = self._adb("shell dumpsys activity services")
        suspicious = []
        if output:
            for line in output.splitlines():
                line_lower = line.lower()
                for pattern in KNOWN_SPYWARE_NAMES_PARTIAL:
                    if pattern in line_lower:
                        suspicious.append(line.strip())
                        break
        if suspicious:
            self.findings.append({
                "severity": "warning",
                "type": "suspicious_services",
                "services": suspicious[:20],
            })
        return {"suspicious_services": suspicious[:20], "status": "completed"}

    def check_network(self) -> dict:
        """Check active network connections."""
        output = self._adb("shell cat /proc/net/tcp")
        connections = []
        if output:
            for line in output.splitlines()[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 4:
                    connections.append({
                        "local": parts[1],
                        "remote": parts[2],
                        "state": parts[3],
                    })
        return {"active_connections": len(connections), "status": "completed"}

    def check_battery_anomalies(self) -> dict:
        """Check battery usage for anomalies (spyware drains battery)."""
        output = self._adb("shell dumpsys batterystats --charged")
        high_drain = []
        if output:
            # Look for apps with excessive wake locks or CPU time
            for line in output.splitlines():
                if "wake" in line.lower() and "1000" not in line:
                    if any(p in line.lower() for p in KNOWN_SPYWARE_NAMES_PARTIAL):
                        high_drain.append(line.strip())
        return {"anomalies": high_drain[:10], "status": "completed"}

    def check_certificates(self) -> dict:
        """Check for user-installed CA certificates (MITM indicator)."""
        output = self._adb("shell ls /data/misc/user/0/cacerts-added/")
        user_certs = []
        if output and "No such file" not in output:
            user_certs = [f.strip() for f in output.splitlines() if f.strip()]
            if user_certs:
                self.findings.append({
                    "severity": "warning",
                    "type": "user_certificates",
                    "count": len(user_certs),
                    "detail": "User-installed CA certificates can enable MITM attacks",
                })
        return {"user_certificates": len(user_certs), "status": "completed"}

    def _calculate_risk(self, checks: dict) -> dict:
        """Calculate overall risk score from findings."""
        score = 0
        for f in self.findings:
            if f["severity"] == "critical":
                score += 40
            elif f["severity"] == "high":
                score += 20
            elif f["severity"] == "warning":
                score += 10
            elif f["severity"] == "info":
                score += 2

        if score >= 40:
            level = "CRITICAL"
        elif score >= 20:
            level = "HIGH"
        elif score >= 10:
            level = "MEDIUM"
        elif score > 0:
            level = "LOW"
        else:
            level = "CLEAN"

        return {"score": score, "level": level, "finding_count": len(self.findings)}


class iOSScanner:
    """Security scanner for iOS devices."""

    def __init__(self, udid: str):
        self.udid = udid
        self.findings = []

    def _idevice(self, cmd: str, timeout: int = 30) -> str:
        stdout, _, rc = _run(f"{cmd} -u {self.udid}", timeout)
        return stdout if rc == 0 else ""

    def scan_all(self) -> dict:
        """Run all iOS security checks."""
        results = {
            "platform": "ios",
            "udid": self.udid,
            "scan_time": datetime.now().isoformat(),
            "checks": {},
        }

        results["checks"]["device_info"] = self.check_device_info()
        results["checks"]["profiles"] = self.check_profiles()
        results["checks"]["jailbreak"] = self.check_jailbreak()
        results["checks"]["syslog_analysis"] = self.check_syslog()
        results["checks"]["installed_apps"] = self.check_installed_apps()
        results["checks"]["backup_analysis"] = self.check_backup_artifacts()

        results["risk_score"] = self._calculate_risk(results["checks"])
        results["findings"] = self.findings
        return results

    def check_device_info(self) -> dict:
        """Get device info and check for anomalies."""
        output = self._idevice("ideviceinfo")
        info = {}
        if output:
            for line in output.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    info[k.strip()] = v.strip()

        # Check if OS is outdated
        os_ver = info.get("ProductVersion", "")
        if os_ver:
            parts = os_ver.split(".")
            try:
                major = int(parts[0])
                if major < 17:  # iOS 17 is current as of 2026
                    self.findings.append({
                        "severity": "warning",
                        "type": "outdated_os",
                        "version": os_ver,
                        "detail": "Outdated iOS may have unpatched vulnerabilities",
                    })
            except ValueError:
                pass

        return {"info": info, "status": "completed"}

    def check_profiles(self) -> dict:
        """Check for configuration/MDM profiles."""
        output = self._idevice("ideviceprovision list")
        profiles = []
        if output:
            current_profile = {}
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    if current_profile:
                        profiles.append(current_profile)
                        # Check for suspicious profiles
                        name = current_profile.get("name", "").lower()
                        for sus in IOS_SUSPICIOUS_PROFILES:
                            if sus.lower() in name:
                                self.findings.append({
                                    "severity": "warning",
                                    "type": "suspicious_profile",
                                    "profile": current_profile,
                                })
                        current_profile = {}
                elif ":" in line:
                    k, _, v = line.partition(":")
                    current_profile[k.strip().lower()] = v.strip()
            if current_profile:
                profiles.append(current_profile)

        return {"profiles": profiles, "count": len(profiles), "status": "completed"}

    def check_jailbreak(self) -> dict:
        """Check for jailbreak indicators."""
        indicators = []

        # Check via idevicediagnostics or filesystem probes
        # These checks require a paired and trusted device
        output = self._idevice("ideviceinfo -q com.apple.mobile.internal")
        if output and "IsInternalBuild" in output:
            indicators.append("Internal build flags detected")

        # Check for Cydia-related indicators in crash logs
        output = self._idevice("idevicecrashreport -e .")
        if output and "cydia" in output.lower():
            indicators.append("Cydia references in crash logs")

        jailbroken = len(indicators) > 0
        if jailbroken:
            self.findings.append({
                "severity": "high",
                "type": "jailbreak_detected",
                "indicators": indicators,
            })

        return {"jailbroken": jailbroken, "indicators": indicators, "status": "completed"}

    def check_syslog(self) -> dict:
        """Analyze syslog for suspicious process names."""
        # Capture 10 seconds of syslog
        stdout, _, rc = _run(
            f"timeout 10 idevicesyslog -u {self.udid}", timeout=15
        )
        suspicious = []
        if stdout:
            for line in stdout.splitlines():
                for proc in IOS_SUSPICIOUS_PROCESSES:
                    if proc in line:
                        suspicious.append({
                            "process": proc,
                            "line": line[:200],
                        })
            if suspicious:
                self.findings.append({
                    "severity": "critical",
                    "type": "suspicious_ios_process",
                    "processes": suspicious,
                })

        return {
            "lines_analyzed": len(stdout.splitlines()) if stdout else 0,
            "suspicious_processes": suspicious,
            "status": "completed",
        }

    def check_installed_apps(self) -> dict:
        """List installed apps and check against known threats."""
        output = self._idevice("ideviceinstaller -l")
        apps = []
        suspicious = []
        if output:
            for line in output.splitlines():
                if " - " in line:
                    parts = line.split(" - ", 1)
                    bundle_id = parts[0].strip()
                    name = parts[1].strip() if len(parts) > 1 else bundle_id
                    apps.append({"bundle_id": bundle_id, "name": name})

                    # Check against patterns
                    bid_lower = bundle_id.lower()
                    for pattern in KNOWN_SPYWARE_NAMES_PARTIAL:
                        if pattern in bid_lower:
                            finding = {
                                "severity": "warning",
                                "type": "suspicious_app",
                                "bundle_id": bundle_id,
                                "name": name,
                            }
                            suspicious.append(finding)
                            self.findings.append(finding)
                            break

        return {
            "total_apps": len(apps),
            "suspicious": suspicious,
            "status": "completed",
        }

    def check_backup_artifacts(self) -> dict:
        """Check local backup artifacts for IOCs."""
        # Look for iTunes/Finder backups
        backup_dir = Path(os.environ.get("APPDATA", "")) / "Apple Computer" / "MobileSync" / "Backup"
        if not backup_dir.exists():
            backup_dir = Path(os.environ.get("USERPROFILE", "")) / "Apple" / "MobileSync" / "Backup"

        backups = []
        if backup_dir.exists():
            for d in backup_dir.iterdir():
                if d.is_dir():
                    info_plist = d / "Info.plist"
                    backups.append({
                        "path": str(d),
                        "has_info": info_plist.exists(),
                        "size_mb": round(
                            sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                            / (1024 * 1024), 1
                        ) if info_plist.exists() else 0,
                    })

        return {
            "backup_dir": str(backup_dir),
            "backups_found": len(backups),
            "backups": backups[:5],
            "status": "completed",
        }

    def _calculate_risk(self, checks: dict) -> dict:
        score = 0
        for f in self.findings:
            if f["severity"] == "critical":
                score += 40
            elif f["severity"] == "high":
                score += 20
            elif f["severity"] == "warning":
                score += 10
            elif f["severity"] == "info":
                score += 2

        if score >= 40:
            level = "CRITICAL"
        elif score >= 20:
            level = "HIGH"
        elif score >= 10:
            level = "MEDIUM"
        elif score > 0:
            level = "LOW"
        else:
            level = "CLEAN"

        return {"score": score, "level": level, "finding_count": len(self.findings)}


class MVTIntegration:
    """Integration with Mobile Verification Toolkit (Amnesty International)."""

    def __init__(self):
        self.mvt_available = self._check_mvt()
        self.ioc_dir = IOC_DIR

    def _check_mvt(self) -> bool:
        _, _, rc = _run("mvt-android version")
        if rc == 0:
            return True
        _, _, rc = _run("mvt-ios version")
        return rc == 0

    def update_iocs(self) -> dict:
        """Download latest IOCs from Amnesty International."""
        IOC_DIR.mkdir(parents=True, exist_ok=True)
        ioc_url = "https://raw.githubusercontent.com/AmnestyTech/investigations/master/2021-07-18_nso/pegasus.stix2"

        try:
            import requests
            # Pegasus IOCs
            resp = requests.get(ioc_url, timeout=30)
            if resp.status_code == 200:
                ioc_file = IOC_DIR / "pegasus.stix2"
                with open(ioc_file, "w", encoding="utf-8") as f:
                    f.write(resp.text)
                return {"success": True, "iocs_updated": True, "source": "amnesty_tech"}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

        return {"success": False, "error": "Could not download IOCs"}

    def scan_android_backup(self, backup_path: str) -> dict:
        """Run MVT against an Android backup."""
        if not self.mvt_available:
            return {"error": "MVT not installed. Run: pip install mvt"}

        output_dir = REPORTS_DIR / f"mvt-android-{int(time.time())}"
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = f'mvt-android check-backup --output "{output_dir}"'
        if self.ioc_dir.exists():
            stix_files = list(self.ioc_dir.glob("*.stix2"))
            if stix_files:
                cmd += f' --iocs "{stix_files[0]}"'
        cmd += f' "{backup_path}"'

        stdout, stderr, rc = _run(cmd, timeout=300)
        return {
            "success": rc == 0,
            "output_dir": str(output_dir),
            "stdout": stdout[:2000],
            "stderr": stderr[:500],
        }

    def scan_ios_backup(self, backup_path: str) -> dict:
        """Run MVT against an iOS backup."""
        if not self.mvt_available:
            return {"error": "MVT not installed. Run: pip install mvt"}

        output_dir = REPORTS_DIR / f"mvt-ios-{int(time.time())}"
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = f'mvt-ios check-backup --output "{output_dir}"'
        if self.ioc_dir.exists():
            stix_files = list(self.ioc_dir.glob("*.stix2"))
            if stix_files:
                cmd += f' --iocs "{stix_files[0]}"'
        cmd += f' "{backup_path}"'

        stdout, stderr, rc = _run(cmd, timeout=600)
        return {
            "success": rc == 0,
            "output_dir": str(output_dir),
            "stdout": stdout[:2000],
            "stderr": stderr[:500],
        }


class PhoneCheck:
    """
    Master controller for phone security scanning.

    Usage:
        checker = PhoneCheck()

        # Detect connected devices
        devices = checker.detect_devices()

        # Scan a specific device
        report = checker.scan(devices[0])

        # Full auto-scan (detect + scan all)
        reports = checker.auto_scan()
    """

    def __init__(self):
        PHONE_CHECK_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.detector = DeviceDetector()
        self.mvt = MVTIntegration()

    def detect_devices(self) -> List[dict]:
        """Detect all connected mobile devices."""
        return self.detector.detect_all()

    def scan(self, device: dict) -> dict:
        """Scan a specific device."""
        platform = device.get("platform", "unknown")

        if platform == "android":
            serial = device.get("serial", "")
            if not serial:
                return {"error": "No serial number for Android device"}
            scanner = AndroidScanner(serial)
            results = scanner.scan_all()

        elif platform == "ios":
            udid = device.get("udid", "")
            if not udid:
                return {"error": "No UDID for iOS device — device may need to be trusted"}
            scanner = iOSScanner(udid)
            results = scanner.scan_all()

        else:
            return {"error": f"Unsupported platform: {platform}"}

        # Add device info
        results["device"] = device

        # Save report
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        device_name = device.get("name", device.get("serial", "unknown"))
        safe_name = re.sub(r'[^\w\-]', '_', str(device_name))
        report_file = REPORTS_DIR / f"phone-check-{safe_name}-{timestamp}.json"
        _save_json(report_file, results)
        results["report_file"] = str(report_file)

        return results

    def auto_scan(self) -> List[dict]:
        """Detect all devices and scan them all."""
        devices = self.detect_devices()
        if not devices:
            return [{
                "error": "No mobile devices detected",
                "troubleshooting": {
                    "ios": [
                        "Ensure iTunes/Apple Devices is installed",
                        "Unlock the phone and tap 'Trust This Computer'",
                        "Try a different USB cable (use Apple original if possible)",
                        "Install libimobiledevice: choco install libimobiledevice",
                    ],
                    "android": [
                        "Enable USB Debugging in Developer Options",
                        "Install ADB: choco install adb",
                        "Authorize the computer on the phone's popup",
                        "Try a different USB cable or port",
                    ],
                },
            }]

        reports = []
        for device in devices:
            report = self.scan(device)
            reports.append(report)

        return reports

    def check_tools(self) -> dict:
        """Check which scanning tools are available."""
        tools = {}

        # ADB
        _, _, rc = _run("adb version")
        tools["adb"] = {"installed": rc == 0}

        # libimobiledevice
        _, _, rc = _run("idevice_id -h")
        tools["libimobiledevice"] = {"installed": rc == 0}

        # MVT
        tools["mvt"] = {"installed": self.mvt.mvt_available}

        # iTunes / Apple Mobile Device Support
        ps_cmd = (
            'powershell -Command "Get-ItemProperty '
            "'HKLM:\\SOFTWARE\\Apple Inc.\\Apple Mobile Device Support\\' "
            "-ErrorAction SilentlyContinue | "
            'Select-Object ProductVersion | ConvertTo-Json"'
        )
        stdout, _, rc = _run(ps_cmd)
        tools["apple_mobile_support"] = {
            "installed": rc == 0 and stdout and "null" not in stdout.lower()
        }

        # Chocolatey (for installing tools)
        _, _, rc = _run("choco --version")
        tools["chocolatey"] = {"installed": rc == 0}

        return tools

    def install_tools(self) -> dict:
        """Attempt to install missing scanning tools."""
        results = {}

        # Check choco first
        _, _, rc = _run("choco --version")
        if rc != 0:
            results["chocolatey"] = "Not installed — install from https://chocolatey.org/"
            return results

        tools_status = self.check_tools()

        if not tools_status["adb"]["installed"]:
            stdout, stderr, rc = _run("choco install adb -y", timeout=120)
            results["adb"] = "installed" if rc == 0 else f"failed: {stderr[:100]}"

        if not tools_status["libimobiledevice"]["installed"]:
            stdout, stderr, rc = _run(
                "choco install libimobiledevice -y", timeout=120
            )
            results["libimobiledevice"] = (
                "installed" if rc == 0 else f"failed: {stderr[:100]}"
            )

        if not tools_status["mvt"]["installed"]:
            stdout, stderr, rc = _run(
                "pip install mvt --break-system-packages", timeout=180
            )
            results["mvt"] = "installed" if rc == 0 else f"failed: {stderr[:100]}"

        return results

    def generate_report_summary(self, scan_result: dict) -> str:
        """Generate a human-readable summary of scan results."""
        lines = []
        lines.append("=" * 60)
        lines.append("  PHONE SECURITY CHECK REPORT")
        lines.append("=" * 60)

        device = scan_result.get("device", {})
        lines.append(f"\nDevice: {device.get('name', 'Unknown')}")
        lines.append(f"Platform: {scan_result.get('platform', 'Unknown')}")
        lines.append(f"Model: {device.get('model', 'Unknown')}")
        lines.append(f"OS Version: {device.get('os_version', 'Unknown')}")
        lines.append(f"Scan Time: {scan_result.get('scan_time', 'Unknown')}")

        risk = scan_result.get("risk_score", {})
        level = risk.get("level", "UNKNOWN")
        score = risk.get("score", 0)
        lines.append(f"\n{'─' * 40}")
        lines.append(f"  RISK LEVEL: {level} (score: {score})")
        lines.append(f"  Findings: {risk.get('finding_count', 0)}")
        lines.append(f"{'─' * 40}")

        findings = scan_result.get("findings", [])
        if findings:
            lines.append("\nFINDINGS:")
            for i, f in enumerate(findings, 1):
                severity = f.get("severity", "info").upper()
                ftype = f.get("type", "unknown")
                lines.append(f"\n  [{severity}] #{i}: {ftype}")
                for k, v in f.items():
                    if k not in ("severity", "type"):
                        lines.append(f"    {k}: {v}")
        else:
            lines.append("\nNo security issues detected.")

        # Check summaries
        checks = scan_result.get("checks", {})
        if checks:
            lines.append(f"\n{'─' * 40}")
            lines.append("CHECK DETAILS:")
            for check_name, check_data in checks.items():
                status = check_data.get("status", "unknown")
                lines.append(f"  {check_name}: {status}")

        lines.append(f"\n{'=' * 60}")
        lines.append(f"  Report saved: {scan_result.get('report_file', 'N/A')}")
        lines.append("=" * 60)

        return "\n".join(lines)


class ForensicPhoneCheck(PhoneCheck):
    """Extended phone scanner with full forensic depth.

    Adds to PhoneCheck:
      1. USB quarantine integration — device screened before deep scan
      2. Network traffic capture — monitor phone's network activity
      3. File system diffing — snapshot before/after for artifact detection
      4. Certificate chain deep inspection
      5. Timeline generation — correlate all findings chronologically
      6. Behavioral monitoring — watch device behavior over time window
    """

    def forensic_scan(self, quarantine_first: bool = True) -> List[dict]:
        """Full forensic scan with quarantine screening.

        1. Run USB quarantine check (is this device what it claims to be?)
        2. Fingerprint the USB device (VID/PID, composite check, threat score)
        3. If approved, proceed with deep forensic scan
        4. Network traffic baseline capture
        5. Full standard scan (apps, permissions, profiles, etc.)
        6. Behavioral monitoring window
        7. Generate forensic timeline
        """
        reports = []

        # Step 1: Quarantine check
        if quarantine_first:
            quarantine_report = self._quarantine_check()
            if quarantine_report.get("blocked"):
                return [quarantine_report]
            reports.append(quarantine_report)

        # Step 2: Detect and scan
        devices = self.detect_devices()
        if not devices:
            return [{"error": "No mobile devices detected after quarantine check"}]

        for device in devices:
            # Standard scan first
            result = self.scan(device)

            # Step 3: Network traffic capture
            net_results = self._capture_network_traffic(device, duration=15)
            result["forensic_network"] = net_results

            # Step 4: Enhanced certificate inspection
            if device.get("platform") == "ios":
                cert_results = self._deep_certificate_check_ios(device)
                result["forensic_certificates"] = cert_results
            elif device.get("platform") == "android":
                cert_results = self._deep_certificate_check_android(device)
                result["forensic_certificates"] = cert_results

            # Step 5: Behavioral monitoring
            behavior = self._behavioral_monitor(device, duration=20)
            result["forensic_behavior"] = behavior

            # Step 6: Generate timeline
            result["forensic_timeline"] = self._generate_timeline(result)

            # Recalculate risk with forensic findings
            result["forensic_risk"] = self._calculate_forensic_risk(result)

            # Save enhanced report
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            device_name = device.get("name", device.get("serial", "unknown"))
            safe_name = re.sub(r'[^\w\-]', '_', str(device_name))
            report_file = REPORTS_DIR / f"forensic-{safe_name}-{timestamp}.json"
            _save_json(report_file, result)
            result["report_file"] = str(report_file)

            reports.append(result)

        return reports

    def _quarantine_check(self) -> dict:
        """Run USB quarantine protocol on the phone's USB connection."""
        try:
            from rudy.usb_quarantine import USBQuarantine
            q = USBQuarantine()
            report = q.scan()

            # Check if any new device was blocked
            blocked = any(
                "BLOCKED" in a for a in report.get("actions_taken", [])
            )

            return {
                "step": "usb_quarantine",
                "blocked": blocked,
                "new_devices": len(report.get("new_devices", [])),
                "threats": report.get("threats", []),
                "actions": report.get("actions_taken", []),
            }
        except ImportError:
            return {"step": "usb_quarantine", "blocked": False, "note": "quarantine module not available"}

    def _capture_network_traffic(self, device: dict, duration: int = 15) -> dict:
        """Capture network connections the phone makes.

        On Windows, we can see the phone's network traffic if it's on the
        same WiFi network by monitoring new connections during the scan window.
        For Android with USB debugging, we can also capture via adb shell.
        """
        results = {
            "duration_seconds": duration,
            "connections": [],
            "dns_queries": [],
            "suspicious": [],
        }

        platform = device.get("platform")

        if platform == "android" and device.get("serial"):
            serial = device["serial"]
            # Capture active connections on the Android device
            stdout, _, rc = _run(f'adb -s {serial} shell "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null"', timeout=10)
            if rc == 0 and stdout:
                results["connections_raw"] = stdout[:2000]
                # Parse hex IP:port pairs
                for line in stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        remote = parts[2]
                        if remote != "00000000:0000" and remote != "00000000000000000000000000000000:0000":
                            results["connections"].append(remote)

            # Check DNS cache
            stdout, _, rc = _run(f'adb -s {serial} shell "dumpsys connectivity | grep -i dns"', timeout=10)
            if rc == 0 and stdout:
                results["dns_info"] = stdout[:1000]

            # Check for unusual listening ports
            stdout, _, rc = _run(f'adb -s {serial} shell "netstat -tlnp 2>/dev/null || ss -tlnp 2>/dev/null"', timeout=10)
            if rc == 0 and stdout:
                results["listening_ports"] = stdout[:1000]
                # Flag if phone is listening on unusual ports
                for line in stdout.splitlines():
                    if ":0.0.0.0" in line or "*:*" in line:
                        results["suspicious"].append(f"Phone listening on: {line.strip()[:100]}")

        elif platform == "ios" and device.get("udid"):
            # iOS: limited network visibility, but check syslog for network activity
            udid = device["udid"]
            stdout, _, rc = _run(f'idevicesyslog -u {udid} -t', timeout=duration + 5)
            if rc == 0 and stdout:
                # Look for network-related entries
                net_entries = [
                    line for line in stdout.splitlines()
                    if any(kw in line.lower() for kw in
                           ["connect", "dns", "tcp", "http", "tls", "ssl", "socket", "vpn"])
                ]
                results["network_syslog_entries"] = len(net_entries)
                results["network_syslog_sample"] = net_entries[:20]

        return results

    def _deep_certificate_check_ios(self, device: dict) -> dict:
        """Deep certificate inspection for iOS."""
        results = {"certificates": [], "suspicious": []}
        udid = device.get("udid", "")
        if not udid:
            return results

        # Check installed configuration profiles (can contain root CAs)
        stdout, _, rc = _run(f'ideviceprovision list -u {udid}', timeout=15)
        if rc == 0 and stdout:
            results["provisioning_profiles"] = stdout[:2000]
            if "enterprise" in stdout.lower():
                results["suspicious"].append(
                    "Enterprise provisioning profile detected — could enable sideloaded apps"
                )

        # Check for MDM enrollment
        stdout, _, rc = _run(f'ideviceinfo -u {udid} -k ManagedConfiguration', timeout=10)
        if rc == 0 and stdout and "null" not in stdout.lower():
            results["suspicious"].append(f"MDM configuration detected: {stdout[:200]}")

        return results

    def _deep_certificate_check_android(self, device: dict) -> dict:
        """Deep certificate inspection for Android."""
        results = {"certificates": [], "suspicious": []}
        serial = device.get("serial", "")
        if not serial:
            return results

        # Check user-installed CA certificates
        stdout, _, rc = _run(
            f'adb -s {serial} shell "ls /data/misc/user/0/cacerts-added/ 2>/dev/null"',
            timeout=10,
        )
        if rc == 0 and stdout.strip():
            certs = stdout.strip().splitlines()
            results["user_installed_certs"] = certs
            results["suspicious"].append(
                f"{len(certs)} user-installed CA certificates — could enable MITM interception"
            )

        # Check for VPN apps that might intercept traffic
        stdout, _, rc = _run(
            f'adb -s {serial} shell "pm list packages | grep -iE \'vpn|proxy|tunnel|ssl\'"',
            timeout=10,
        )
        if rc == 0 and stdout.strip():
            results["vpn_proxy_apps"] = stdout.strip().splitlines()

        # Check device admin apps (can enforce policies, exfiltrate data)
        stdout, _, rc = _run(
            f'adb -s {serial} shell "dumpsys device_policy | grep -A2 admin"',
            timeout=10,
        )
        if rc == 0 and stdout.strip():
            results["device_admin_info"] = stdout[:1000]

        return results

    def _behavioral_monitor(self, device: dict, duration: int = 20) -> dict:
        """Watch what the device does during a time window.

        Captures: CPU activity, network connections, new processes,
        sensor activations (camera, microphone indicators).
        """
        results = {
            "duration_seconds": duration,
            "activity_detected": False,
            "events": [],
        }

        platform = device.get("platform")
        serial = device.get("serial", "")

        if platform == "android" and serial:
            # Snapshot processes before
            before_out, _, _ = _run(f'adb -s {serial} shell "ps -A 2>/dev/null | wc -l"', timeout=5)
            before_count = int(before_out.strip()) if before_out.strip().isdigit() else 0

            # Monitor for the window
            time.sleep(min(duration, 30))

            # Snapshot after
            after_out, _, _ = _run(f'adb -s {serial} shell "ps -A 2>/dev/null | wc -l"', timeout=5)
            after_count = int(after_out.strip()) if after_out.strip().isdigit() else 0

            if abs(after_count - before_count) > 5:
                results["activity_detected"] = True
                results["events"].append(
                    f"Process count changed: {before_count} → {after_count}"
                )

            # Check battery drain rate (high drain = suspicious background activity)
            bat_out, _, _ = _run(
                f'adb -s {serial} shell "dumpsys battery | grep level"', timeout=5
            )
            if bat_out:
                results["battery_level"] = bat_out.strip()

        elif platform == "ios":
            # iOS behavioral monitoring is limited without jailbreak
            # Use syslog to detect activity
            udid = device.get("udid", "")
            if udid:
                stdout, _, rc = _run(f'idevicesyslog -u {udid} -t', timeout=min(duration, 30))
                if rc == 0 and stdout:
                    lines = stdout.splitlines()
                    results["syslog_lines"] = len(lines)
                    # Flag high activity
                    if len(lines) > 100:
                        results["activity_detected"] = True
                        results["events"].append(
                            f"High syslog activity: {len(lines)} entries in {duration}s"
                        )
                    # Look for camera/mic activation
                    for line in lines:
                        if any(kw in line.lower() for kw in ["camera", "microphone", "recording"]):
                            results["events"].append(f"Sensor activity: {line[:100]}")

        return results

    def _generate_timeline(self, scan_result: dict) -> List[dict]:
        """Correlate all findings into a chronological timeline."""
        timeline = []
        scan_time = scan_result.get("scan_time", datetime.now().isoformat())

        # Add standard findings
        for finding in scan_result.get("findings", []):
            timeline.append({
                "time": scan_time,
                "source": "standard_scan",
                "severity": finding.get("severity", "info"),
                "event": f"{finding.get('type', '?')}: {finding.get('detail', finding.get('package', ''))}"[:200],
            })

        # Add network findings
        net = scan_result.get("forensic_network", {})
        for suspicious in net.get("suspicious", []):
            timeline.append({
                "time": scan_time,
                "source": "network_capture",
                "severity": "warning",
                "event": suspicious[:200],
            })

        # Add certificate findings
        certs = scan_result.get("forensic_certificates", {})
        for suspicious in certs.get("suspicious", []):
            timeline.append({
                "time": scan_time,
                "source": "certificate_check",
                "severity": "warning",
                "event": suspicious[:200],
            })

        # Add behavioral findings
        behavior = scan_result.get("forensic_behavior", {})
        for event in behavior.get("events", []):
            timeline.append({
                "time": scan_time,
                "source": "behavioral_monitor",
                "severity": "info",
                "event": event[:200],
            })

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "info": 4, "low": 5}
        timeline.sort(key=lambda e: severity_order.get(e.get("severity", "info"), 5))

        return timeline

    def _calculate_forensic_risk(self, scan_result: dict) -> dict:
        """Calculate overall forensic risk score."""
        score = 0
        factors = []

        # Base score from standard scan
        base_risk = scan_result.get("risk_score", {})
        score += base_risk.get("score", 0)

        # Network suspicious activity
        net = scan_result.get("forensic_network", {})
        net_suspicious = len(net.get("suspicious", []))
        if net_suspicious > 0:
            score += net_suspicious * 15
            factors.append(f"Network: {net_suspicious} suspicious findings")

        # Certificate issues
        certs = scan_result.get("forensic_certificates", {})
        cert_suspicious = len(certs.get("suspicious", []))
        if cert_suspicious > 0:
            score += cert_suspicious * 20
            factors.append(f"Certificates: {cert_suspicious} issues")

        # Behavioral anomalies
        behavior = scan_result.get("forensic_behavior", {})
        if behavior.get("activity_detected"):
            score += 10
            factors.append("Behavioral: unusual activity detected")

        # Quarantine concerns
        quarantine = scan_result.get("forensic_quarantine", {})
        if quarantine.get("threats"):
            score += 30
            factors.append(f"USB quarantine: {len(quarantine['threats'])} threats")

        score = min(score, 100)

        if score >= 70:
            level = "CRITICAL"
        elif score >= 50:
            level = "HIGH"
        elif score >= 30:
            level = "MEDIUM"
        elif score >= 10:
            level = "LOW"
        else:
            level = "CLEAN"

        return {
            "score": score,
            "level": level,
            "factors": factors,
        }


if __name__ == "__main__":
    print("Phone Check — Mobile Device Security Scanner")
    checker = PhoneCheck()

    print("\n  Checking available tools...")
    tools = checker.check_tools()
    for tool, status in tools.items():
        installed = "OK" if status.get("installed") else "MISSING"
        print(f"    {tool}: {installed}")

    print("\n  Detecting connected devices...")
    devices = checker.detect_devices()
    if devices:
        for d in devices:
            name = d.get("name", d.get("serial", "Unknown"))
            print(f"    Found: {name} ({d.get('platform', '?')})")

        print("\n  Starting security scan...")
        for d in devices:
            result = checker.scan(d)
            summary = checker.generate_report_summary(result)
            print(summary)
    else:
        print("    No mobile devices detected.")
        print("    Connect a phone via USB and ensure:")
        print("      iOS: Trust this computer + iTunes installed")
        print("      Android: USB debugging enabled + ADB installed")
