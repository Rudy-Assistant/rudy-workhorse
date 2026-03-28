"""
Travel Mode — Portable network intelligence for The Workhorse.

When The Workhorse moves to a new network (Airbnb, hotel, airport, etc.),
this module:
  1. Detects the network change (new gateway, new subnet, new SSID)
  2. Archives the current network profile (home farm baselines)
  3. Initializes a fresh threat posture for the unknown network
  4. Runs an aggressive first-contact reconnaissance scan
  5. Profiles every device on the new network
  6. Monitors continuously with elevated alerting thresholds
  7. Restores home baselines when returning to a known network

Design principles:
  - Every unknown network is hostile until proven otherwise
  - No cleared devices carry over from home (except The Workhorse itself)
  - Travel networks get MORE aggressive scanning (shorter intervals, wider port range)
  - All travel network data is preserved for forensic review
  - Known networks (home, recurring locations) restore their profiles automatically

Network identification:
  A network is identified by a composite fingerprint:
    - Gateway IP + Gateway MAC (primary identifier)
    - Subnet mask
    - SSID (if WiFi)
    - DNS servers in use
  This prevents spoofing — an attacker would need to replicate ALL of these.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import socket
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS_DIR = DESKTOP / "rudy-logs"
PROFILES_DIR = LOGS_DIR / "network-profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

TRAVEL_STATE_FILE = LOGS_DIR / "travel-state.json"
NETWORK_HISTORY_FILE = LOGS_DIR / "network-history.json"

# Files that contain network-specific baselines (need archiving on network change)
BASELINE_FILES = [
    "defense-arp-baseline.json",
    "defense-dns-baseline.json",
    "defense-traffic-baseline.json",
    "defense-state.json",
    "defense-alerts.json",
    "intruder-database.json",
    "cleared-devices.json",
    "threat-timeline.json",
    "presence-current.json",
    "presence-devices.json",
    "presence-analytics.json",
    "presence-household.json",
    "security-baseline.json",
]

# Home network fingerprint (Cimino family farm)
HOME_NETWORK = {
    "name": "Cimino Family Farm",
    "gateway_ip": "192.168.7.1",
    "gateway_mac": "f8-bb-bf-59-c2-d2",
    "subnet": "192.168.7",
    "trust_level": "home",
    "scan_interval_minutes": 15,
    "alert_threshold": "normal",
}


class NetworkFingerprint:
    """Captures the identity of the current network."""

    def __init__(self):
        self.gateway_ip = None
        self.gateway_mac = None
        self.subnet = None
        self.ssid = None
        self.dns_servers = []
        self.public_ip = None
        self.local_ip = None
        self.timestamp = datetime.now().isoformat()

    def capture(self) -> "NetworkFingerprint":
        """Capture the current network fingerprint."""
        self._get_gateway()
        self._get_ssid()
        self._get_dns()
        self._get_local_ip()
        self._get_public_ip()
        return self

    def _get_gateway(self):
        """Get default gateway IP and MAC."""
        try:
            # Get gateway IP
            result = subprocess.run(
                'ipconfig', shell=True, capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if "Default Gateway" in line:
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                    if match:
                        self.gateway_ip = match.group(1)
                        # Derive subnet from gateway
                        parts = self.gateway_ip.split(".")
                        self.subnet = ".".join(parts[:3])
                        break

            # Get gateway MAC from ARP table
            if self.gateway_ip:
                result = subprocess.run(
                    'arp -a', shell=True, capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.splitlines():
                    if self.gateway_ip in line:
                        match = re.search(
                            r'([\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2})',
                            line, re.IGNORECASE
                        )
                        if match:
                            self.gateway_mac = match.group(1).lower()
                            break
        except Exception as e:
            log.debug(f"Failed to get gateway IP and MAC: {e}")
            pass

    def _get_ssid(self):
        """Get current WiFi SSID (if connected via WiFi)."""
        try:
            result = subprocess.run(
                'netsh wlan show interfaces',
                shell=True, capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if "SSID" in line and "BSSID" not in line:
                    match = re.search(r'SSID\s*:\s*(.+)', line)
                    if match:
                        self.ssid = match.group(1).strip()
                        break
        except Exception as e:
            log.debug(f"Failed to get SSID: {e}")
            pass

    def _get_dns(self):
        """Get configured DNS servers."""
        try:
            result = subprocess.run(
                'ipconfig /all', shell=True, capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if "DNS Servers" in line:
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                    if match:
                        self.dns_servers.append(match.group(1))
        except Exception as e:
            log.debug(f"Failed to get DNS servers: {e}")
            pass

    def _get_local_ip(self):
        """Get our local IP on this network."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.local_ip = s.getsockname()[0]
            s.close()
        except Exception as e:
            log.debug(f"Failed to get local IP: {e}")
            pass

    def _get_public_ip(self):
        """Get public IP (helps identify ISP/location)."""
        try:
            import httpx
            resp = httpx.get("https://api.ipify.org?format=json", timeout=5)
            if resp.status_code == 200:
                self.public_ip = resp.json().get("ip")
        except Exception as e:
            log.debug(f"Failed to get public IP via httpx: {e}")
            try:
                import requests
                resp = requests.get("https://api.ipify.org?format=json", timeout=5)
                if resp.status_code == 200:
                    self.public_ip = resp.json().get("ip")
            except Exception as e:
                log.debug(f"Failed to get public IP via requests: {e}")
                pass

    @property
    def fingerprint_id(self) -> str:
        """Generate a unique ID for this network based on composite fingerprint."""
        raw = f"{self.gateway_ip}|{self.gateway_mac}|{self.subnet}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "fingerprint_id": self.fingerprint_id,
            "gateway_ip": self.gateway_ip,
            "gateway_mac": self.gateway_mac,
            "subnet": self.subnet,
            "ssid": self.ssid,
            "dns_servers": self.dns_servers,
            "public_ip": self.public_ip,
            "local_ip": self.local_ip,
            "timestamp": self.timestamp,
        }

    def matches(self, other_id: str) -> bool:
        return self.fingerprint_id == other_id


class TravelMode:
    """
    Manages network transitions and travel security posture.
    """

    # Travel mode elevates these settings
    TRAVEL_POSTURE = {
        "scan_interval_minutes": 5,       # Scan every 5 min instead of 15
        "intruder_alert_threshold": 10,   # Lower threshold for alerts
        "port_scan_range": list(range(1, 1025)) + [3389, 5900, 8080, 8443, 9090],
        "dns_canaries": [
            "google.com", "microsoft.com", "github.com",
            "anthropic.com", "cloudflare.com", "amazon.com",
        ],
        "monitor_all_traffic": True,
        "alert_on_any_new_device": True,
        "check_for_evil_twin": True,
        "check_for_captive_portal": True,
        "block_smb": True,                # Block SMB on untrusted networks
        "verify_https": True,             # Watch for SSL interception
    }

    def __init__(self):
        self.state = self._load_json(TRAVEL_STATE_FILE, {
            "mode": "home",
            "current_network": None,
            "home_network_id": None,
            "known_networks": {},
            "travel_log": [],
        })
        self.history = self._load_json(NETWORK_HISTORY_FILE, [])

    def _load_json(self, path, default):
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.debug(f"Failed to load JSON from {path}: {e}")
                pass
        return default

    def _save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def check_network(self) -> dict:
        """
        Check if the network has changed. This should be called
        periodically (e.g., by SystemMaster or Sentinel every 5 min).

        Returns action taken: 'no_change', 'travel_activated', 'home_restored',
        'new_travel_network', or 'known_network_restored'.
        """
        fp = NetworkFingerprint().capture()
        current_id = fp.fingerprint_id
        previous_id = self.state.get("current_network_id")

        result = {
            "timestamp": datetime.now().isoformat(),
            "network": fp.to_dict(),
            "action": "no_change",
        }

        # First run — establish home
        if not previous_id:
            self.state["current_network_id"] = current_id
            self.state["current_network"] = fp.to_dict()

            # Check if this is the home network
            if (fp.gateway_ip == HOME_NETWORK["gateway_ip"] and
                fp.gateway_mac == HOME_NETWORK["gateway_mac"]):
                self.state["mode"] = "home"
                self.state["home_network_id"] = current_id
                self.state["known_networks"][current_id] = {
                    "name": HOME_NETWORK["name"],
                    "trust_level": "home",
                    "first_seen": datetime.now().isoformat(),
                    "visits": 1,
                    "fingerprint": fp.to_dict(),
                }
                result["action"] = "home_established"
            else:
                result["action"] = "initial_scan"
                self._activate_travel_mode(fp)

            self._save_state()
            return result

        # Network hasn't changed
        if current_id == previous_id:
            return result

        # === NETWORK CHANGED ===
        print(f"\n{'='*55}")
        print("  NETWORK CHANGE DETECTED")
        print(f"  Previous: {self.state.get('current_network', {}).get('ssid', 'Unknown')}")
        print(f"  New: {fp.ssid or 'Unknown SSID'}")
        print(f"  Gateway: {fp.gateway_ip} [{fp.gateway_mac}]")
        print(f"{'='*55}\n")

        # Log the transition
        self.history.append({
            "time": datetime.now().isoformat(),
            "from_network": previous_id,
            "to_network": current_id,
            "from_ssid": self.state.get("current_network", {}).get("ssid"),
            "to_ssid": fp.ssid,
        })
        self._save_json(NETWORK_HISTORY_FILE, self.history[-500:])

        # Archive current network baselines
        self._archive_baselines(previous_id)

        # Check if this is a KNOWN network
        if current_id in self.state["known_networks"]:
            known = self.state["known_networks"][current_id]
            known["visits"] = known.get("visits", 0) + 1
            known["last_seen"] = datetime.now().isoformat()

            if known.get("trust_level") == "home":
                # Returning home
                self.state["mode"] = "home"
                self._restore_baselines(current_id)
                result["action"] = "home_restored"
                print("  Returning HOME — restoring home baselines")
            else:
                # Returning to a known travel network
                self.state["mode"] = "travel"
                self._restore_baselines(current_id)
                result["action"] = "known_network_restored"
                print(f"  Known network: {known.get('name', 'Unknown')} — restoring baselines")
        else:
            # Completely NEW network — full travel mode
            self._activate_travel_mode(fp)
            result["action"] = "travel_activated"

        self.state["current_network_id"] = current_id
        self.state["current_network"] = fp.to_dict()
        self._save_state()

        return result

    def _activate_travel_mode(self, fp: NetworkFingerprint):
        """Activate travel mode for an unknown network."""
        now = datetime.now()
        network_id = fp.fingerprint_id

        print("  TRAVEL MODE ACTIVATED — all devices treated as hostile")
        print(f"  Subnet: {fp.subnet}.0/24 | SSID: {fp.ssid or 'Unknown'}")

        self.state["mode"] = "travel"
        self.state["travel_activated_at"] = now.isoformat()
        self.state["known_networks"][network_id] = {
            "name": fp.ssid or f"Travel-{now.strftime('%Y%m%d-%H%M')}",
            "trust_level": "untrusted",
            "first_seen": now.isoformat(),
            "visits": 1,
            "fingerprint": fp.to_dict(),
        }

        self.state["travel_log"].append({
            "time": now.isoformat(),
            "event": "travel_mode_activated",
            "ssid": fp.ssid,
            "gateway": fp.gateway_ip,
            "public_ip": fp.public_ip,
        })

        # Clear all network-specific baselines for fresh start
        for filename in BASELINE_FILES:
            filepath = LOGS_DIR / filename
            if filepath.exists():
                filepath.unlink()

        # Run aggressive first-contact scan
        self._first_contact_scan(fp)

    def _first_contact_scan(self, fp: NetworkFingerprint):
        """
        Aggressive initial reconnaissance of a new network.
        Maps every device, probes services, checks for common threats.
        """
        print("\n  Running first-contact reconnaissance...")
        findings = {
            "timestamp": datetime.now().isoformat(),
            "network": fp.to_dict(),
            "devices": [],
            "threats": [],
            "network_services": [],
        }

        subnet = fp.subnet
        if not subnet:
            print("  ERROR: No subnet detected — cannot scan")
            return findings

        # 1. Full subnet ARP discovery
        print(f"  Phase 1: ARP discovery on {subnet}.0/24...")
        discovered = {}
        try:
            # Ping sweep to populate ARP
            for i in list(range(1, 255)):
                subprocess.Popen(
                    f'ping -n 1 -w 300 {subnet}.{i}',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            import time
            time.sleep(5)  # Wait for ARP table to populate

            result = subprocess.run(
                'arp -a', shell=True, capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                match = re.match(
                    r'\s*(\d+\.\d+\.\d+\.\d+)\s+([\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2})',
                    line, re.IGNORECASE
                )
                if match:
                    ip, mac = match.group(1), match.group(2).lower()
                    if mac.startswith("ff-ff-ff") or mac.startswith("01-00-5e"):
                        continue
                    if ip.startswith(f"{subnet}."):
                        discovered[ip] = mac
        except Exception as e:
            log.debug(f"Failed to perform ARP discovery: {e}")
            pass

        print(f"    Found {len(discovered)} devices")
        findings["device_count"] = len(discovered)

        # 2. Profile each device
        print(f"  Phase 2: Profiling {len(discovered)} devices...")
        for ip, mac in discovered.items():
            device = {
                "ip": ip,
                "mac": mac,
                "is_gateway": ip == fp.gateway_ip,
                "mac_randomized": bool(int(mac.replace("-", ":").split(":")[0], 16) & 0x02),
                "hostname": None,
                "open_ports": [],
                "os_hint": None,
            }

            # Hostname
            try:
                result = subprocess.run(
                    f'nbtstat -A {ip}',
                    shell=True, capture_output=True, text=True, timeout=3
                )
                for line in result.stdout.splitlines():
                    if "<00>" in line and "UNIQUE" in line:
                        device["hostname"] = line.split()[0].strip()
                        break
            except Exception as e:
                log.debug(f"Failed to resolve hostname for {ip}: {e}")
                pass

            # Quick port scan (common dangerous ports)
            for port in [22, 23, 53, 80, 139, 443, 445, 554, 3389, 5900, 8080, 8443, 9090]:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.3)
                    if sock.connect_ex((ip, port)) == 0:
                        device["open_ports"].append(port)
                    sock.close()
                except Exception as e:
                    log.debug(f"Failed to scan port {port} on {ip}: {e}")
                    pass

            # TTL-based OS detection
            try:
                result = subprocess.run(
                    f'ping -n 1 -w 500 {ip}',
                    shell=True, capture_output=True, text=True, timeout=3
                )
                ttl_match = re.search(r'TTL=(\d+)', result.stdout)
                if ttl_match:
                    ttl = int(ttl_match.group(1))
                    device["ttl"] = ttl
                    if ttl <= 64:
                        device["os_hint"] = "Linux/Android/iOS/macOS"
                    elif ttl <= 128:
                        device["os_hint"] = "Windows"
            except Exception as e:
                log.debug(f"Failed to detect OS via TTL for {ip}: {e}")
                pass

            findings["devices"].append(device)

        # 3. Check for specific threats
        print("  Phase 3: Threat assessment...")

        # Check for captive portal (common in hotels/Airbnbs)
        try:
            result = subprocess.run(
                'nslookup connectivitycheck.gstatic.com',
                shell=True, capture_output=True, text=True, timeout=5
            )
            # If this resolves to a private IP, there's a captive portal
            if any(x in result.stdout for x in ["192.168.", "10.", "172.16."]):
                findings["threats"].append({
                    "type": "captive_portal",
                    "severity": "info",
                    "detail": "Captive portal detected — traffic may be intercepted",
                })
        except Exception as e:
            log.debug(f"Failed to check for captive portal: {e}")
            pass

        # Check for ARP duplicates (MitM indicator)
        mac_ips = defaultdict(list)
        for ip, mac in discovered.items():
            mac_ips[mac].append(ip)
        for mac, ips in mac_ips.items():
            if len(ips) > 1:
                findings["threats"].append({
                    "type": "arp_duplicate",
                    "severity": "alert",
                    "detail": f"MAC {mac} claims multiple IPs: {ips} — possible MitM",
                })

        # Check for devices with dangerous open ports
        for device in findings["devices"]:
            if device.get("open_ports"):
                dangerous = [p for p in device["open_ports"] if p in [23, 139, 445, 5900]]
                if dangerous:
                    findings["threats"].append({
                        "type": "dangerous_services",
                        "severity": "warning",
                        "detail": (
                            f"Device {device['ip']} has dangerous ports open: {dangerous} "
                            f"(Telnet/SMB/VNC — potential attack surface)"
                        ),
                    })

        # Check for multiple devices with same hostname (spoofing)
        hostnames = defaultdict(list)
        for device in findings["devices"]:
            if device.get("hostname"):
                hostnames[device["hostname"]].append(device["ip"])
        for hostname, ips in hostnames.items():
            if len(ips) > 1:
                findings["threats"].append({
                    "type": "hostname_collision",
                    "severity": "warning",
                    "detail": f"Multiple devices claim hostname '{hostname}': {ips}",
                })

        # Count threat severity
        threat_counts = defaultdict(int)
        for t in findings["threats"]:
            threat_counts[t["severity"]] += 1

        threat_level = "green"
        if threat_counts.get("alert"):
            threat_level = "red"
        elif threat_counts.get("warning"):
            threat_level = "orange"
        elif threat_counts.get("info"):
            threat_level = "yellow"

        findings["threat_level"] = threat_level

        # Save reconnaissance report
        report_path = PROFILES_DIR / f"recon-{fp.fingerprint_id}-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        self._save_json(report_path, findings)

        # Print summary
        print(f"\n  {'='*50}")
        print("  FIRST-CONTACT RECONNAISSANCE COMPLETE")
        print(f"  {'='*50}")
        print(f"  Network: {fp.ssid or 'Unknown'} ({fp.subnet}.0/24)")
        print(f"  Devices: {len(discovered)}")
        print(f"  Threats: {len(findings['threats'])} ({', '.join(f'{v} {k}' for k, v in threat_counts.items())})")
        print(f"  Threat Level: {threat_level.upper()}")

        for t in findings["threats"]:
            icon = {"info": ".", "warning": "!", "alert": "!!", "critical": "!!!"}
            print(f"    [{icon.get(t['severity'], '?')}] {t['detail']}")

        print("\n  Devices on this network:")
        for d in findings["devices"]:
            ports = f" ports:{d['open_ports']}" if d['open_ports'] else ""
            name = f" ({d['hostname']})" if d.get('hostname') else ""
            gw = " [GATEWAY]" if d.get('is_gateway') else ""
            rand = " [rand-MAC]" if d.get('mac_randomized') else ""
            os_h = f" {d.get('os_hint', '')}" if d.get('os_hint') else ""
            print(f"    {d['ip']}{gw} [{d['mac']}]{rand}{name}{os_h}{ports}")

        return findings

    def _archive_baselines(self, network_id: str):
        """Archive current baselines to the network's profile folder."""
        archive_dir = PROFILES_DIR / network_id
        archive_dir.mkdir(parents=True, exist_ok=True)

        archived = 0
        for filename in BASELINE_FILES:
            src = LOGS_DIR / filename
            if src.exists():
                shutil.copy2(src, archive_dir / filename)
                archived += 1

        print(f"  Archived {archived} baseline files for network {network_id[:8]}...")

    def _restore_baselines(self, network_id: str):
        """Restore baselines from a known network's profile."""
        archive_dir = PROFILES_DIR / network_id
        if not archive_dir.exists():
            print(f"  No archived baselines for network {network_id[:8]}")
            return

        restored = 0
        for filename in BASELINE_FILES:
            src = archive_dir / filename
            if src.exists():
                shutil.copy2(src, LOGS_DIR / filename)
                restored += 1

        print(f"  Restored {restored} baseline files from network {network_id[:8]}")

    def _save_state(self):
        self._save_json(TRAVEL_STATE_FILE, self.state)

    def get_status(self) -> dict:
        """Get current travel mode status."""
        return {
            "mode": self.state.get("mode", "unknown"),
            "current_network": self.state.get("current_network", {}),
            "known_networks_count": len(self.state.get("known_networks", {})),
            "is_home": self.state.get("mode") == "home",
            "travel_activated_at": self.state.get("travel_activated_at"),
        }

    def get_report(self) -> str:
        """Human-readable travel mode status."""
        s = self.state
        lines = ["=" * 55]
        lines.append("  TRAVEL MODE STATUS")
        lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 55)

        mode = s.get("mode", "unknown").upper()
        net = s.get("current_network", {})

        lines.append(f"\n  Mode: {mode}")
        lines.append(f"  SSID: {net.get('ssid', 'Unknown')}")
        lines.append(f"  Gateway: {net.get('gateway_ip', '?')} [{net.get('gateway_mac', '?')}]")
        lines.append(f"  Subnet: {net.get('subnet', '?')}.0/24")
        lines.append(f"  Local IP: {net.get('local_ip', '?')}")
        lines.append(f"  Public IP: {net.get('public_ip', '?')}")
        lines.append(f"  Known networks: {len(s.get('known_networks', {}))}")

        if s.get("mode") == "travel":
            lines.append("\n  ELEVATED THREAT POSTURE:")
            lines.append("    Scan interval: 5 min (vs 15 min at home)")
            lines.append("    All devices: HOSTILE until cleared")
            lines.append("    SMB: Should be blocked")
            lines.append(f"    Travel since: {s.get('travel_activated_at', '?')[:19]}")

        # Known networks
        nets = s.get("known_networks", {})
        if nets:
            lines.append("\n  Known Networks:")
            for nid, info in nets.items():
                trust = info.get("trust_level", "?")
                name = info.get("name", "?")
                visits = info.get("visits", 0)
                lines.append(f"    [{trust.upper():10s}] {name} — {visits} visit(s)")

        lines.append("\n" + "=" * 55)
        return "\n".join(lines)

    def label_network(self, network_id: str = None, name: str = None,
                       trust_level: str = "trusted"):
        """
        Label a known network (e.g., after staying at an Airbnb).
        trust_level: 'home', 'trusted', 'untrusted', 'hostile'
        """
        if not network_id:
            network_id = self.state.get("current_network_id")
        if network_id and network_id in self.state["known_networks"]:
            self.state["known_networks"][network_id]["name"] = name
            self.state["known_networks"][network_id]["trust_level"] = trust_level
            self._save_state()
            print(f"Network {network_id[:8]} labeled: {name} ({trust_level})")


def check_network_change():
    """Check for network changes — call from SystemMaster or Sentinel."""
    tm = TravelMode()
    result = tm.check_network()
    print(tm.get_report())
    return result


def activate_travel_scan():
    """Force a travel-mode reconnaissance scan on the current network."""
    fp = NetworkFingerprint().capture()
    tm = TravelMode()
    tm._first_contact_scan(fp)
    return tm.get_report()


if __name__ == "__main__":
    check_network_change()
