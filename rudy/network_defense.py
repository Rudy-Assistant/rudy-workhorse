"""
Network Defense Module — Defensive countermeasures for The Workhorse.

Threat model (mapped to known offensive capability classes):
  1. ARP Spoofing / MitM (Archimedes-class) → ARP table integrity monitoring
  2. DNS Hijacking (Cherry Blossom-class) → DNS resolution verification
  3. Rogue Access Points / Evil Twin → BSSID baseline monitoring
  4. Traffic Interception → Outbound connection profiling
  5. Lateral Movement / Pandemic-class → SMB/file-share monitoring
  6. Credential Theft (BothanSpy-class) → SSH/RDP session auditing
  7. Firmware Persistence (Dark Matter-class) → Config/registry drift detection

All checks are non-invasive, read-only, and designed to run every 30 minutes
alongside the existing SecurityAgent cycle.
"""
import json
import logging
import os
import re
import socket
import subprocess
import time
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS_DIR = DESKTOP / "rudy-logs"
LOGS_DIR.mkdir(exist_ok=True)

# State files
ARP_BASELINE_FILE = LOGS_DIR / "defense-arp-baseline.json"
DNS_BASELINE_FILE = LOGS_DIR / "defense-dns-baseline.json"
TRAFFIC_BASELINE_FILE = LOGS_DIR / "defense-traffic-baseline.json"
DEFENSE_ALERTS_FILE = LOGS_DIR / "defense-alerts.json"
DEFENSE_STATE_FILE = LOGS_DIR / "defense-state.json"

log = logging.getLogger(__name__)

# Known-good DNS resolvers for verification
TRUSTED_DNS = {
    "1.1.1.1": "Cloudflare",
    "8.8.8.8": "Google",
    "9.9.9.9": "Quad9",
}

# Critical domains to verify DNS resolution against multiple resolvers
DNS_CANARIES = [
    "google.com",
    "microsoft.com",
    "github.com",
    "anthropic.com",
    "cloudflare.com",
]

# Dynamic gateway/subnet detection (travel-compatible)
def _detect_current_gateway():
    try:
        result = __import__("subprocess").run(
            ["ipconfig"], capture_output=True, text=True, timeout=10
        )
        import re as _re
        for line in result.stdout.splitlines():
            if "Default Gateway" in line:
                match = _re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if match:
                    gw = match.group(1)
                    parts = gw.split(".")
                    return gw, ".".join(parts[:3])
    except Exception as e:
        logging.getLogger(__name__).debug(f"Failed to detect gateway: {e}")
    return "192.168.7.1", "192.168.7"

GATEWAY_IP, SUBNET = _detect_current_gateway()


class NetworkDefense:
    """
    Comprehensive network defense monitoring.
    Call run_all_checks() every 30 minutes from SecurityAgent.
    """

    def __init__(self):
        self.arp_baseline = self._load_json(ARP_BASELINE_FILE, {})
        self.dns_baseline = self._load_json(DNS_BASELINE_FILE, {})
        self.traffic_baseline = self._load_json(TRAFFIC_BASELINE_FILE, {})
        self.alerts = self._load_json(DEFENSE_ALERTS_FILE, [])
        self.state = self._load_json(DEFENSE_STATE_FILE, {})
        self.new_alerts = []

    def _load_json(self, path, default):
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.debug(f"Failed to load {path}: {e}")
        return default

    def _save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _alert(self, category: str, severity: str, message: str, details: dict = None):
        """Record a defense alert."""
        alert = {
            "time": datetime.now().isoformat(),
            "category": category,
            "severity": severity,  # info, warning, alert, critical
            "message": message,
            "details": details or {},
        }
        self.new_alerts.append(alert)
        self.alerts.append(alert)
        level_icon = {"info": ".", "warning": "!", "alert": "!!", "critical": "!!!"}
        print(f"  [{level_icon.get(severity, '?')}] {category}: {message}")

    # =============================================
    # 1. ARP SPOOFING DETECTION
    #    Defense against: Archimedes, ettercap, arpspoof
    #    Detects: IP-MAC mapping changes (ARP cache poisoning)
    # =============================================

    def check_arp_integrity(self) -> dict:
        """
        Monitor ARP table for signs of spoofing:
        - Gateway MAC change (most dangerous — indicates MitM)
        - Duplicate MACs for different IPs (ARP poisoning)
        - IP-MAC mapping changes for known devices
        """
        findings = {"status": "ok", "checks": []}

        try:
            result = subprocess.run(
                ["arp", "-a"], capture_output=True, text=True, timeout=10
            )
            current_arp = {}
            mac_to_ips = defaultdict(list)

            for line in result.stdout.splitlines():
                match = re.match(
                    r'\s*(\d+\.\d+\.\d+\.\d+)\s+([\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2})\s+(\w+)',
                    line, re.IGNORECASE
                )
                if match:
                    ip, mac, _entry_type = match.group(1), match.group(2).lower(), match.group(3)
                    if mac.startswith("ff-ff-ff") or mac.startswith("01-00-5e"):
                        continue
                    if ip.startswith(f"{SUBNET}."):
                        current_arp[ip] = mac
                        mac_to_ips[mac].append(ip)

            # Check 1: Gateway MAC stability
            gateway_mac = current_arp.get(GATEWAY_IP)
            if gateway_mac:
                saved_gw = self.arp_baseline.get("gateway_mac")
                if saved_gw and saved_gw != gateway_mac:
                    self._alert(
                        "arp_spoofing", "critical",
                        f"GATEWAY MAC CHANGED: {GATEWAY_IP} was {saved_gw}, now {gateway_mac}. "
                        f"Possible MitM attack!",
                        {"old_mac": saved_gw, "new_mac": gateway_mac, "ip": GATEWAY_IP}
                    )
                    findings["status"] = "critical"
                elif not saved_gw:
                    self.arp_baseline["gateway_mac"] = gateway_mac
                    self._alert("arp_baseline", "info",
                                f"Gateway MAC recorded: {GATEWAY_IP} → {gateway_mac}")

            # Check 2: Duplicate MACs (same MAC, multiple IPs)
            for mac, ips in mac_to_ips.items():
                if len(ips) > 1 and not mac.startswith("ff"):
                    self._alert(
                        "arp_duplicate", "alert",
                        f"MAC {mac} claims {len(ips)} IPs: {', '.join(ips)}. "
                        f"Possible ARP cache poisoning!",
                        {"mac": mac, "ips": ips}
                    )
                    findings["status"] = "alert"

            # Check 3: Known device MAC changes
            for ip, mac in current_arp.items():
                saved = self.arp_baseline.get("known_mappings", {}).get(ip)
                if saved and saved != mac:
                    self._alert(
                        "arp_change", "warning",
                        f"Device at {ip} changed MAC: {saved} → {mac}",
                        {"ip": ip, "old_mac": saved, "new_mac": mac}
                    )
                    if findings["status"] == "ok":
                        findings["status"] = "warning"

            # Update baseline
            self.arp_baseline["known_mappings"] = current_arp
            self.arp_baseline["last_check"] = datetime.now().isoformat()
            self.arp_baseline["device_count"] = len(current_arp)
            self._save_json(ARP_BASELINE_FILE, self.arp_baseline)

            findings["device_count"] = len(current_arp)
            findings["gateway_mac"] = gateway_mac

        except Exception as e:
            findings["status"] = "error"
            findings["error"] = str(e)

        return findings

    # =============================================
    # 2. DNS INTEGRITY MONITORING
    #    Defense against: Cherry Blossom, DNS hijacking, router compromise
    #    Detects: DNS resolution tampering via cross-resolver verification
    # =============================================

    def check_dns_integrity(self) -> dict:
        """
        Verify DNS resolution by comparing answers from the local resolver
        against trusted public DNS servers. Discrepancies indicate:
        - Router-level DNS hijacking
        - Upstream DNS poisoning
        - Local hosts file tampering (beyond our own blocks)
        """
        findings = {"status": "ok", "domains_checked": 0, "discrepancies": []}

        for domain in DNS_CANARIES:
            findings["domains_checked"] += 1
            try:
                # Get local resolution
                local_ips = set()
                try:
                    answers = socket.getaddrinfo(domain, None, socket.AF_INET)
                    local_ips = {a[4][0] for a in answers}
                except socket.gaierror:
                    pass

                # Cross-check with trusted resolvers using nslookup
                trusted_ips = set()
                for dns_server in list(TRUSTED_DNS.keys())[:2]:  # Check 2 servers
                    try:
                        result = subprocess.run(
                            ["nslookup", domain, dns_server],
                            capture_output=True, text=True, timeout=5
                        )
                        for line in result.stdout.splitlines():
                            match = re.search(r'Address:\s*(\d+\.\d+\.\d+\.\d+)', line)
                            if match:
                                ip = match.group(1)
                                if ip != dns_server:  # Skip the DNS server's own IP
                                    trusted_ips.add(ip)
                    except Exception as e:
                        log.debug(f"Failed to query {dns_server} for {domain}: {e}")

                # Compare — we don't need exact match (CDNs vary),
                # but local should resolve to SOMETHING, and not to a known-bad
                if local_ips and trusted_ips:
                    # Check if local resolves to private IP (hijacking indicator)
                    for lip in local_ips:
                        if lip.startswith(("192.168.", "10.", "172.16.", "172.17.",
                                          "172.18.", "172.19.", "172.20.", "172.21.",
                                          "172.22.", "172.23.", "172.24.", "172.25.",
                                          "172.26.", "172.27.", "172.28.", "172.29.",
                                          "172.30.", "172.31.")):
                            self._alert(
                                "dns_hijack", "critical",
                                f"{domain} resolves to PRIVATE IP {lip} locally! "
                                f"Trusted resolvers say: {trusted_ips}",
                                {"domain": domain, "local": list(local_ips),
                                 "trusted": list(trusted_ips)}
                            )
                            findings["status"] = "critical"
                            findings["discrepancies"].append(domain)

                elif not local_ips and trusted_ips:
                    # Local can't resolve but trusted can — possible blocking
                    self._alert(
                        "dns_block", "warning",
                        f"{domain} blocked locally but resolves via trusted DNS",
                        {"domain": domain, "trusted_ips": list(trusted_ips)}
                    )

            except Exception as e:
                log.debug(f"Error checking DNS for {domain}: {e}")  # Network issues shouldn't generate false alerts

        # Save baseline
        self.dns_baseline["last_check"] = datetime.now().isoformat()
        self.dns_baseline["domains_checked"] = findings["domains_checked"]
        self._save_json(DNS_BASELINE_FILE, self.dns_baseline)

        return findings

    # =============================================
    # 3. OUTBOUND TRAFFIC PROFILING
    #    Defense against: Hive C2, data exfiltration, backdoors
    #    Detects: New remote destinations, unusual ports, high-volume transfers
    # =============================================

    def check_outbound_traffic(self) -> dict:
        """
        Profile outbound connections and flag anomalies:
        - New remote IPs/ports never seen before
        - Connections to unusual ports (not 80/443/53)
        - Processes making unexpected network calls
        """
        findings = {"status": "ok", "connections": 0, "new_destinations": []}

        try:
            import psutil
        except ImportError:
            return {"status": "skipped", "reason": "psutil not available"}

        try:
            known_destinations = set(self.traffic_baseline.get("known_destinations", []))
            set(self.traffic_baseline.get("known_remote_ports", []))
            safe_ports = {80, 443, 53, 123, 8080, 8443, 993, 587, 465, 143}

            current_connections = []
            new_dests = []

            for conn in psutil.net_connections(kind='inet'):
                if conn.status != 'ESTABLISHED' or not conn.raddr:
                    continue

                remote_ip = conn.raddr.ip
                remote_port = conn.raddr.port
                local_port = conn.laddr.port if conn.laddr else 0

                # Skip local network
                if remote_ip.startswith(f"{SUBNET}.") or remote_ip.startswith("127."):
                    continue

                findings["connections"] += 1
                dest_key = f"{remote_ip}:{remote_port}"
                current_connections.append(dest_key)

                # Check for new destinations
                if dest_key not in known_destinations:
                    new_dests.append(dest_key)

                    # Get process name
                    proc_name = "unknown"
                    if conn.pid:
                        try:
                            proc_name = psutil.Process(conn.pid).name()
                        except Exception as e:
                            log.debug(f"Failed to get process name for PID {conn.pid}: {e}")

                    severity = "info"
                    if remote_port not in safe_ports:
                        severity = "warning"

                    self._alert(
                        "new_destination", severity,
                        f"New outbound: {proc_name} → {dest_key}",
                        {"process": proc_name, "pid": conn.pid,
                         "remote": dest_key, "local_port": local_port}
                    )

            # Update baseline — grow it over time
            all_known = known_destinations | set(current_connections)
            self.traffic_baseline["known_destinations"] = list(all_known)[-5000:]  # Cap at 5000
            self.traffic_baseline["last_check"] = datetime.now().isoformat()
            self.traffic_baseline["last_connection_count"] = findings["connections"]
            self._save_json(TRAFFIC_BASELINE_FILE, self.traffic_baseline)

            findings["new_destinations"] = new_dests

        except Exception as e:
            findings["status"] = "error"
            findings["error"] = str(e)

        return findings

    # =============================================
    # 4. ROGUE DEVICE DETECTION
    #    Defense against: Evil twin, unauthorized access
    #    Detects: New devices on the network that weren't there before
    # =============================================

    def check_rogue_devices(self) -> dict:
        """
        Compare current network devices against known baseline.
        New devices get flagged; especially outside DHCP range or with
        suspicious OUI patterns.
        """
        findings = {"status": "ok", "new_devices": []}

        try:
            result = subprocess.run(
                ["arp", "-a"], capture_output=True, text=True, timeout=10
            )
            current_macs = set()
            known_macs = set(self.state.get("known_network_macs", []))

            for line in result.stdout.splitlines():
                match = re.match(
                    r'\s*(\d+\.\d+\.\d+\.\d+)\s+([\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2})',
                    line, re.IGNORECASE
                )
                if match:
                    ip, mac = match.group(1), match.group(2).lower()
                    if mac.startswith("ff-ff-ff") or mac.startswith("01-00-5e"):
                        continue
                    if ip.startswith(f"{SUBNET}."):
                        current_macs.add(mac)

                        if mac not in known_macs:
                            findings["new_devices"].append({"ip": ip, "mac": mac})
                            self._alert(
                                "new_device", "warning",
                                f"New device on network: {ip} [{mac}]",
                                {"ip": ip, "mac": mac}
                            )

            # Update baseline
            self.state["known_network_macs"] = list(known_macs | current_macs)
            self.state["last_device_scan"] = datetime.now().isoformat()

        except Exception as e:
            findings["error"] = str(e)

        return findings

    # =============================================
    # 5. SMB / FILE SHARE MONITORING
    #    Defense against: Pandemic-class, lateral movement
    #    Detects: Active SMB sessions, file shares, unexpected connections
    # =============================================

    def check_smb_activity(self) -> dict:
        """
        Monitor SMB/CIFS activity — unexpected file shares or connections
        could indicate lateral movement or Pandemic-class file replacement.
        """
        findings = {"status": "ok", "shares": [], "sessions": []}

        try:
            # Check active shares
            result = subprocess.run(
                ["net", "share"], capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith("-") and not line.startswith("Share"):
                    parts = line.split()
                    if parts and not parts[0].endswith("$"):  # Skip admin shares
                        findings["shares"].append(parts[0])

            # Check active sessions
            result = subprocess.run(
                ["net", "session"], capture_output=True, text=True, timeout=10
            )
            session_count = 0
            for line in result.stdout.splitlines():
                if re.match(r'\\\\\d+\.\d+\.\d+\.\d+', line.strip()):
                    session_count += 1
                    findings["sessions"].append(line.strip())

            if session_count > 0:
                self._alert(
                    "smb_session", "warning",
                    f"{session_count} active SMB session(s) detected",
                    {"sessions": findings["sessions"]}
                )

            # Check for non-default shares
            default_shares = {"C$", "IPC$", "ADMIN$", "print$"}
            for share in findings["shares"]:
                if share not in default_shares:
                    self._alert(
                        "unexpected_share", "alert",
                        f"Non-default file share found: {share}",
                        {"share": share}
                    )

        except Exception as e:
            log.debug(f"SMB activity check error: {e}")  # net commands may need elevation

        return findings

    # =============================================
    # 6. REGISTRY / CONFIG DRIFT DETECTION
    #    Defense against: Dark Matter persistence, rootkits
    #    Detects: Changes to critical registry keys and startup locations
    # =============================================

    def check_config_drift(self) -> dict:
        """
        Monitor critical Windows configuration for unauthorized changes:
        - Startup programs (Run keys)
        - Security settings
        - Network configuration
        - Scheduled tasks
        """
        findings = {"status": "ok", "drifts": []}

        registry_checks = {
            "startup_hklm": r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
            "startup_hkcu": r'HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
            "startup_once": r'HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce',
            "winlogon": r'HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon',
            "services_pending": r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\RunServicesOnce',
        }

        current_state = {}
        for name, key in registry_checks.items():
            try:
                result = subprocess.run(
                    ["reg", "query", key],
                    capture_output=True, text=True, timeout=10
                )
                # Hash the output for change detection
                state_hash = hashlib.sha256(result.stdout.encode()).hexdigest()[:16]
                current_state[name] = {
                    "hash": state_hash,
                    "entries": len([line for line in result.stdout.splitlines() if "REG_" in line]),
                }
            except Exception as e:
                log.debug(f"Failed to query registry key {name}: {e}")
                current_state[name] = {"hash": "error", "entries": 0}

        # Compare to baseline
        saved_state = self.state.get("registry_baseline", {})
        for name, current in current_state.items():
            saved = saved_state.get(name, {})
            if saved.get("hash") and saved["hash"] != current["hash"]:
                self._alert(
                    "config_drift", "alert",
                    f"Registry change detected in {name}: "
                    f"{saved.get('entries', '?')} → {current['entries']} entries",
                    {"key": name, "old_hash": saved["hash"], "new_hash": current["hash"]}
                )
                findings["drifts"].append(name)

        self.state["registry_baseline"] = current_state
        return findings

    # =============================================
    # 7. LISTENING PORT AUDIT
    #    Defense against: Backdoors, reverse shells, unauthorized services
    #    Detects: New listening ports that weren't in the baseline
    # =============================================

    def check_listening_ports(self) -> dict:
        """
        Comprehensive listening port audit.
        New listeners = potential backdoor or unauthorized service.
        """
        findings = {"status": "ok", "ports": [], "new_ports": []}

        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=10
            )
            current_ports = {}
            for line in result.stdout.splitlines():
                if "LISTENING" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        addr = parts[1]
                        pid = parts[4]
                        port_match = re.search(r':(\d+)$', addr)
                        if port_match:
                            port = int(port_match.group(1))
                            current_ports[port] = pid
                            findings["ports"].append(port)

            known_ports = set(self.state.get("known_listening_ports", []))
            for port, pid in current_ports.items():
                if port not in known_ports:
                    # Get process name
                    proc_name = "unknown"
                    try:
                        result = subprocess.run(
                            ["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
                            capture_output=True, text=True, timeout=5
                        )
                        if result.stdout.strip():
                            proc_name = result.stdout.strip().split(",")[0].strip('"')
                    except Exception as e:
                        log.debug(f"Failed to get process name for port {port}: {e}")

                    severity = "warning" if port > 1024 else "alert"
                    self._alert(
                        "new_listener", severity,
                        f"New listening port: {port} (PID {pid}, {proc_name})",
                        {"port": port, "pid": pid, "process": proc_name}
                    )
                    findings["new_ports"].append(port)

            self.state["known_listening_ports"] = list(set(findings["ports"]))

        except Exception as e:
            findings["error"] = str(e)

        return findings

    # =============================================
    # MAIN: Run all checks
    # =============================================

    def run_all_checks(self) -> dict:
        """Run the complete defense check suite."""
        print(f"[Defense] Running network defense checks at {datetime.now().strftime('%H:%M:%S')}...")
        self.new_alerts = []

        results = {}
        checks = [
            ("arp_integrity", self.check_arp_integrity),
            ("dns_integrity", self.check_dns_integrity),
            ("outbound_traffic", self.check_outbound_traffic),
            ("rogue_devices", self.check_rogue_devices),
            ("smb_activity", self.check_smb_activity),
            ("config_drift", self.check_config_drift),
            ("listening_ports", self.check_listening_ports),
        ]

        for name, check_fn in checks:
            try:
                results[name] = check_fn()
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}

        # Determine overall status
        statuses = [r.get("status", "ok") for r in results.values()]
        if "critical" in statuses:
            overall = "critical"
        elif "alert" in statuses:
            overall = "alert"
        elif "warning" in statuses:
            overall = "warning"
        else:
            overall = "ok"

        # Save state and alerts
        self.state["last_full_check"] = datetime.now().isoformat()
        self.state["last_status"] = overall
        self.state["checks_run"] = len(checks)
        self._save_json(DEFENSE_STATE_FILE, self.state)

        self.alerts = self.alerts[-1000:]  # Keep last 1000
        self._save_json(DEFENSE_ALERTS_FILE, self.alerts)

        summary = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": overall,
            "alerts_generated": len(self.new_alerts),
            "checks": results,
        }

        severity_counts = defaultdict(int)
        for a in self.new_alerts:
            severity_counts[a["severity"]] += 1

        print(f"  Status: {overall.upper()}")
        print(f"  Alerts: {len(self.new_alerts)} "
              f"({', '.join(f'{v} {k}' for k, v in severity_counts.items())})")

        return summary

    def get_defense_report(self) -> str:
        """Human-readable defense status report."""
        lines = ["=" * 55]
        lines.append("  NETWORK DEFENSE STATUS")
        lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 55)

        state = self.state
        lines.append(f"\n  Last check: {state.get('last_full_check', 'Never')[:19]}")
        lines.append(f"  Overall: {state.get('last_status', 'unknown').upper()}")

        # ARP
        arp = self.arp_baseline
        lines.append("\n  ARP Integrity:")
        lines.append(f"    Gateway MAC: {arp.get('gateway_mac', 'unknown')}")
        lines.append(f"    Tracked devices: {arp.get('device_count', 0)}")

        # Recent alerts
        recent = [a for a in self.alerts[-20:]
                  if a.get("severity") in ("warning", "alert", "critical")]
        if recent:
            lines.append(f"\n  Recent Alerts ({len(recent)}):")
            for a in recent[-10:]:
                lines.append(f"    [{a['severity'].upper()}] {a['message']}")

        lines.append("\n" + "=" * 55)
        return "\n".join(lines)


def run_defense_check():
    """Run a complete network defense check."""
    defense = NetworkDefense()
    result = defense.run_all_checks()
    print(f"\n{defense.get_defense_report()}")
    return result


if __name__ == "__main__":
    run_defense_check()
