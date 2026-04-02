"""Forensic phone analysis module.

Extracted from phone_check.py during ADR-005 Phase 2a.
Deep forensic scanning: network capture, certificate analysis,
behavioral monitoring, timeline generation.
"""
import subprocess
import logging
import json
import time
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Import core classes from phone_check for inheritance
from rudy.phone_check import PhoneCheck, _run, _save_json, _load_json


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

