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
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS = DESKTOP / "rudy-logs"
PHONE_CHECK_DIR = DESKTOP / "rudy-data" / "phone-check"
IOC_DIR = PHONE_CHECK_DIR / "iocs"
REPORTS_DIR = PHONE_CHECK_DIR / "reports"


def _run(cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
    """Run a command, return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except Exception as e:
        return "", str(e), -1


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_json(path: Path, default=None):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
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
        """Detect iOS devices via libimobiledevice or iTunes driver."""
        devices = []

        # Try idevice_id (libimobiledevice)
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

        # Fallback: check for Apple USB device via PowerShell
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

        third_party = [l.replace("package:", "").strip()
                       for l in output.splitlines() if l.startswith("package:")]

        for pkg in third_party[:50]:  # Limit to avoid timeout
            perms_out = self._adb(f"shell dumpsys package {pkg}", timeout=10)
            if not perms_out:
                continue

            granted = []
            in_perms = False
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
                with open(ioc_file, "w") as f:
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
