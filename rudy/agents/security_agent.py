"""
SecurityAgent — Defensive Intelligence & Threat Detection.
The Workhorse's immune system. Runs every 30 minutes via scheduled task.

Monitors:
  - Active network connections (psutil) — flags unknown destinations
  - Listening ports — detects new services
  - File integrity of critical configs — detects tampering
  - Windows Event Logs — failed logins, new accounts, service changes
  - Process anomalies — unexpected executables, high resource consumers
  - Known breach databases — family email exposure

Design principles:
  - Silent unless something is wrong
  - Never modifies what it monitors
  - Logs everything, alerts selectively
  - Maintains a baseline of "normal" to detect deviations
"""
import hashlib
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter
from . import AgentBase, DESKTOP, LOGS_DIR

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from rudy.network_defense import NetworkDefense
    from rudy.presence import PresenceMonitor
    HAS_PRESENCE = True
except ImportError:
    HAS_PRESENCE = False

try:
    from rudy.wellness import WellnessMonitor
    HAS_WELLNESS = True
except ImportError:
    HAS_WELLNESS = False


class SecurityAgent(AgentBase):
    name = "security_agent"
    version = "1.0"

    BASELINE_FILE = LOGS_DIR / "security-baseline.json"
    ALERTS_FILE = LOGS_DIR / "security-alerts.json"
    THREAT_LOG = LOGS_DIR / "security-threat.log"

    # Known safe processes — expand over time as we learn what's normal
    KNOWN_PROCESSES = {
        "python.exe", "pythonw.exe", "python3.exe",
        "rustdesk.exe", "rustdesk.service.exe",
        "tailscaled.exe",
        "explorer.exe", "svchost.exe", "csrss.exe", "lsass.exe",
        "services.exe", "smss.exe", "wininit.exe", "winlogon.exe",
        "dwm.exe", "taskhostw.exe", "sihost.exe", "fontdrvhost.exe",
        "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
        "textinputhost.exe", "widgetservice.exe",
        "msmpeng.exe", "nissrv.exe", "msedge.exe",
        "node.exe", "git.exe", "code.exe",
        "claude.exe", "conhost.exe", "cmd.exe", "powershell.exe",
        "system", "registry", "idle",
        "spoolsv.exe", "dllhost.exe", "msiexec.exe",
        "audiodg.exe", "ctfmon.exe", "securityhealthservice.exe",
        "sgrmbroker.exe", "systemsettingsbroker.exe",
        "wmiprvse.exe", "wudfhost.exe", "dashost.exe",
    }

    # Known safe listening ports
    KNOWN_PORTS = {
        21300,  # RustDesk
        41080, 41180,  # Tailscale
        135, 139, 445,  # Windows SMB/RPC
        5040,  # Windows
    }

    # Critical files to hash
    CRITICAL_FILES = [
        DESKTOP / "CLAUDE.md",
        DESKTOP / "rudy-command-runner.py",
        DESKTOP / "rudy-listener.py",
        DESKTOP / "workhorse-healthcheck.ps1",
        DESKTOP / "enforce-rustdesk-config.ps1",
        DESKTOP / "rudy" / "admin.py",
        DESKTOP / "rudy" / "agents" / "__init__.py",
    ]

    # Family emails to monitor for breaches
    MONITORED_EMAILS = [
        "ccimino2@gmail.com",
        "lrcimino@yahoo.com",
        "rudy.ciminoassist@gmail.com",
    ]

    def run(self, **kwargs):
        mode = kwargs.get("mode", "full")
        self.security_events = []

        baseline = self._load_baseline()

        if mode in ("full", "network"):
            self._scan_network_connections(baseline)
            self._scan_listening_ports(baseline)

        if mode in ("full", "processes"):
            self._scan_processes(baseline)

        if mode in ("full", "integrity"):
            self._check_file_integrity(baseline)

        if mode in ("full", "eventlog"):
            self._scan_event_logs()

        if mode in ("full", "breach"):
            self._check_breaches()

        if mode in ("full", "presence"):
            self._scan_wifi_presence()

        if mode in ("full", "wellness"):
            self._check_wellness()

        self._save_baseline(baseline)
        self._save_security_events()

        alerts = len(self.status["critical_alerts"])
        events = len(self.security_events)
        self.summarize(f"Security scan: {events} events, {alerts} alerts")

    def _load_baseline(self) -> dict:
        if self.BASELINE_FILE.exists():
            try:
                with open(self.BASELINE_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "first_run": datetime.now().isoformat(),
            "file_hashes": {},
            "known_listeners": [],
            "known_connections": {},
            "process_baseline": [],
            "scan_count": 0,
        }

    def _save_baseline(self, baseline):
        baseline["last_scan"] = datetime.now().isoformat()
        baseline["scan_count"] = baseline.get("scan_count", 0) + 1
        with open(self.BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2, default=str)

    def _security_event(self, severity: str, category: str, detail: str):
        """Log a security event. severity: info, warning, alert, critical"""
        event = {
            "time": datetime.now().isoformat(),
            "severity": severity,
            "category": category,
            "detail": detail,
        }
        self.security_events.append(event)

        # Write to threat log immediately
        try:
            with open(self.THREAT_LOG, "a", encoding="utf-8") as f:
                f.write(f"{event['time']} [{severity.upper()}] [{category}] {detail}\n")
        except Exception:
            pass

        if severity in ("alert", "critical"):
            self.alert(f"[{category}] {detail}")
        elif severity == "warning":
            self.warn(f"[{category}] {detail}")
        else:
            self.log.info(f"[{category}] {detail}")

    def _save_security_events(self):
        """Save recent security events."""
        all_events = []
        if self.ALERTS_FILE.exists():
            try:
                with open(self.ALERTS_FILE) as f:
                    all_events = json.load(f)
            except Exception:
                pass
        all_events.extend(self.security_events)
        all_events = all_events[-500:]  # Keep last 500 events
        with open(self.ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_events, f, indent=2, default=str)

    # === NETWORK SCANNING ===

    def _scan_network_connections(self, baseline):
        """Monitor active network connections for anomalies."""
        if not HAS_PSUTIL:
            return

        self.log.info("Scanning network connections...")
        connections = psutil.net_connections(kind='inet')

        # Track unique remote destinations
        remote_hosts = Counter()

        for conn in connections:
            if conn.status == 'ESTABLISHED' and conn.raddr:
                remote_ip = conn.raddr.ip
                remote_port = conn.raddr.port

                remote_hosts[remote_ip] += 1

                # Flag connections to unusual ports
                if remote_port not in (80, 443, 8080, 8443, 53, 993, 587, 465):
                    # Try to identify the process
                    proc_name = "unknown"
                    if conn.pid:
                        try:
                            proc = psutil.Process(conn.pid)
                            proc_name = proc.name()
                        except Exception:
                            pass

                    # Not necessarily bad, but worth logging on first sight
                    conn_key = f"{remote_ip}:{remote_port}"
                    if conn_key not in baseline.get("known_connections", {}):
                        self._security_event("info", "new_connection",
                            f"New destination: {remote_ip}:{remote_port} via {proc_name} (PID {conn.pid})")
                        baseline.setdefault("known_connections", {})[conn_key] = {
                            "first_seen": datetime.now().isoformat(),
                            "process": proc_name,
                        }

        # Check for unusually high connection counts to single host
        for ip, count in remote_hosts.most_common(5):
            if count > 20:
                self._security_event("warning", "high_conn_count",
                    f"{count} connections to {ip}")

        self.status["active_connections"] = len([c for c in connections if c.status == 'ESTABLISHED'])
        self.status["unique_remote_hosts"] = len(remote_hosts)

    def _scan_listening_ports(self, baseline):
        """Detect new listening services."""
        if not HAS_PSUTIL:
            return

        self.log.info("Scanning listening ports...")
        listeners = []
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'LISTEN' and conn.laddr:
                port = conn.laddr.port
                proc_name = "unknown"
                if conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        proc_name = proc.name()
                    except Exception:
                        pass
                listeners.append({"port": port, "process": proc_name, "pid": conn.pid})

        # Compare to known ports
        current_ports = {entry["port"] for entry in listeners}
        prev_ports = set(baseline.get("known_listeners", []))

        new_ports = current_ports - prev_ports - self.KNOWN_PORTS
        for port in new_ports:
            proc = next((entry for entry in listeners if entry["port"] == port), {})
            self._security_event("warning", "new_listener",
                f"New listening port: {port} ({proc.get('process', 'unknown')})")

        baseline["known_listeners"] = list(current_ports)
        self.status["listening_ports"] = len(current_ports)

    # === PROCESS MONITORING ===

    def _scan_processes(self, baseline):
        """Detect unexpected or anomalous processes."""
        if not HAS_PSUTIL:
            return

        self.log.info("Scanning processes...")
        current_procs = set()
        suspicious_procs = []

        for proc in psutil.process_iter(['pid', 'name', 'exe', 'cpu_percent', 'memory_info', 'create_time']):
            try:
                name = (proc.info['name'] or '').lower()
                current_procs.add(name)

                # Check for unknown processes
                if name and name not in self.KNOWN_PROCESSES:
                    exe = proc.info.get('exe', 'unknown')
                    mem_mb = round((proc.info['memory_info'].rss if proc.info['memory_info'] else 0) / 1024 / 1024, 1)

                    # Only flag on first appearance
                    prev_procs = set(baseline.get("process_baseline", []))
                    if name not in prev_procs:
                        self._security_event("info", "new_process",
                            f"Unfamiliar process: {name} (exe: {exe}, mem: {mem_mb}MB)")
                        suspicious_procs.append(name)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        baseline["process_baseline"] = list(current_procs)
        self.status["total_processes"] = len(current_procs)
        if suspicious_procs:
            self.status["new_processes"] = suspicious_procs

    # === FILE INTEGRITY ===

    def _check_file_integrity(self, baseline):
        """Hash critical files and detect changes."""
        self.log.info("Checking file integrity...")
        prev_hashes = baseline.get("file_hashes", {})
        current_hashes = {}

        for filepath in self.CRITICAL_FILES:
            if filepath.exists():
                try:
                    content = filepath.read_bytes()
                    file_hash = hashlib.sha256(content).hexdigest()
                    current_hashes[str(filepath)] = file_hash

                    prev = prev_hashes.get(str(filepath))
                    if prev and prev != file_hash:
                        self._security_event("warning", "file_modified",
                            f"Critical file changed: {filepath.name}")
                    elif prev is None:
                        self._security_event("info", "file_baselined",
                            f"Baselined: {filepath.name} ({file_hash[:12]})")
                except Exception as e:
                    self._security_event("warning", "file_read_error",
                        f"Cannot read {filepath.name}: {e}")

        baseline["file_hashes"] = current_hashes

    # === EVENT LOG ANALYSIS ===

    def _scan_event_logs(self):
        """Check Windows Event Logs for security-relevant events."""
        self.log.info("Scanning Windows Event Logs...")

        # Check for failed logins (Event ID 4625)
        try:
            r = subprocess.run(
                'powershell -Command "Get-WinEvent -FilterHashtable @{LogName=\'Security\';Id=4625} -MaxEvents 5 -EA SilentlyContinue | Select-Object TimeCreated, Message | Format-List"',
                shell=True, capture_output=True, text=True, timeout=15
            )
            if r.stdout.strip():
                count = r.stdout.count("TimeCreated")
                if count > 0:
                    self._security_event("warning", "failed_logins",
                        f"{count} failed login attempts in recent event log")
        except Exception:
            pass

        # Check for new user accounts created (Event ID 4720)
        try:
            r = subprocess.run(
                'powershell -Command "Get-WinEvent -FilterHashtable @{LogName=\'Security\';Id=4720} -MaxEvents 3 -EA SilentlyContinue | Select-Object TimeCreated, Message | Format-List"',
                shell=True, capture_output=True, text=True, timeout=15
            )
            if r.stdout.strip() and "TimeCreated" in r.stdout:
                self._security_event("alert", "new_account",
                    "New user account was created!")
        except Exception:
            pass

        # Check for service installations (Event ID 7045)
        try:
            r = subprocess.run(
                'powershell -Command "Get-WinEvent -FilterHashtable @{LogName=\'System\';Id=7045} -MaxEvents 5 -EA SilentlyContinue | Select-Object TimeCreated, Message | Format-List"',
                shell=True, capture_output=True, text=True, timeout=15
            )
            if r.stdout.strip():
                # Only alert on very recent ones (last hour)
                if "TimeCreated" in r.stdout:
                    self._security_event("info", "service_installed",
                        "Recent service installation detected (check details)")
        except Exception:
            pass

    # === WIFI PRESENCE ===

    def _scan_wifi_presence(self):
        """Scan local WiFi for device presence changes."""
        if not HAS_PRESENCE:
            self.log.info("Presence monitor not available")
            return

        self.log.info("Scanning WiFi presence...")
        try:
            monitor = PresenceMonitor()
            result = monitor.scan()

            self.status["devices_on_network"] = result["devices_found"]
            self.status["known_devices"] = result["known_present"]
            self.status["unknown_devices"] = result["unknown_present"]

            # Alert on unknown devices
            if result["unknown_present"] > 0:
                for event in result.get("events", []):
                    if event["type"] == "arrival" and not event["known"]:
                        self._security_event("warning", "unknown_device",
                            f"Unknown device joined network: {event['ip']} [{event['mac']}]")

            # Log arrivals/departures of known devices
            for event in result.get("events", []):
                if event["known"]:
                    self._security_event("info", f"device_{event['type']}",
                        f"{event['name']} {event['type']}: {event['ip']}")

        except Exception as e:
            self.log.info(f"  Presence scan error: {e}")

    # === WELLNESS MONITORING ===


    def _check_network_defense(self):
        """Run comprehensive network defense checks."""
        try:
            if NetworkDefense is None:
                return
            defense = NetworkDefense()
            result = defense.run_all_checks()

            status = result.get("overall_status", "unknown")
            alerts = result.get("alerts_generated", 0)

            if status in ("critical", "alert"):
                self.log.warning(f"Network defense: {status.upper()} — {alerts} alerts")
                # Add to security alerts
                for check_name, check_result in result.get("checks", {}).items():
                    if check_result.get("status") in ("critical", "alert"):
                        self._record_alert(
                            "network_defense",
                            check_result.get("status"),
                            f"Defense check '{check_name}': {check_result.get('status')}"
                        )
            else:
                self.log.info(f"Network defense: {status} — {alerts} new observations")
        except Exception as e:
            self.log.error(f"Network defense error: {e}")

    def _check_wellness(self):
        """Run family wellness checks based on device presence patterns."""
        if not HAS_WELLNESS:
            return

        self.log.info("Running wellness check...")
        try:
            monitor = WellnessMonitor()
            findings = monitor.check()

            self.status["wellness_persons_checked"] = findings["persons_checked"]

            for alert in findings.get("alerts_generated", []):
                severity = alert.get("severity", "low")
                if severity in ("high", "critical"):
                    self._security_event("alert", "wellness_alert", alert["message"])
                elif severity == "medium":
                    self._security_event("warning", "wellness_concern", alert["message"])
                else:
                    self._security_event("info", "wellness_note", alert["message"])

        except Exception as e:
            self.log.info(f"  Wellness check error: {e}")

    # === BREACH MONITORING ===

    def _check_breaches(self):
        """Check if monitored emails appear in known breaches.
        Uses the Have I Been Pwned API (free tier, rate-limited).
        Only runs once per day to respect rate limits.
        """
        self.log.info("Checking breach databases...")

        # Rate limit: only check once per day
        last_check_file = LOGS_DIR / "breach-last-check.json"
        if last_check_file.exists():
            try:
                with open(last_check_file) as f:
                    data = json.load(f)
                last = datetime.fromisoformat(data.get("last_check", "2000-01-01"))
                if (datetime.now() - last).total_seconds() < 86400:
                    self.log.info("  Breach check: skipping (checked within 24h)")
                    return
            except Exception:
                pass

        try:
            import httpx
        except ImportError:
            self.log.info("  httpx not available — skipping breach check")
            return

        breached = []
        for email in self.MONITORED_EMAILS:
            try:
                # HIBP API v3 — free endpoint for breach check
                r = httpx.get(
                    f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                    headers={
                        "User-Agent": "Rudy-Workhorse-Security-Agent",
                        "Accept": "application/json",
                    },
                    timeout=10,
                    follow_redirects=True,
                )
                if r.status_code == 200:
                    breach_data = r.json()
                    breach_names = [b.get("Name", "Unknown") for b in breach_data]
                    breached.append({"email": email, "breaches": breach_names})
                    self._security_event("alert", "breach_detected",
                                         f"{email} found in {len(breach_names)} breach(es): {', '.join(breach_names[:5])}")
                elif r.status_code == 404:
                    self.log.info(f"  {email}: No breaches found")
                else:
                    self.log.info(f"  {email}: API returned {r.status_code}")
            except Exception as e:
                self.log.info(f"  Breach check error for {email}: {e}")

        # Save last check timestamp
        try:
            with open(last_check_file, "w") as f:
                json.dump({"last_check": datetime.now().isoformat(), "results": breached}, f)
        except Exception:
            pass

        if breached:
            self.log.info(f"  ALERT: {len(breached)} email(s) found in breaches!")
        else:
            self.log.info("  All monitored emails clear")
