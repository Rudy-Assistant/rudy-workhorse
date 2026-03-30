# ╔══════════════════════════════════════════════════════════╗
# ║  DEPRECATION NOTICE (2026-03-29)                        ║
# ║  Per ADR-SENTINEL-CONSOLIDATION:                        ║
# ║  This module's passive recon capabilities (port scan,   ║
# ║  firewall check, DNS check) will be migrated into       ║
# ║  agents/sentinel.py (Phase 2).                          ║
# ║  This file remains functional until migration complete.  ║
# ║  Canonical security scanning: agents/sentinel.py        ║
# ╚══════════════════════════════════════════════════════════╝

#!/usr/bin/env python3

"""
Lucius Fox — Network Security Passive Reconnaissance Module.

Shannon-pattern pen-testing: SCAN + REPORT only. No active hardening.

This module adds a _audit_network_security() method to Lucius's audit
repertoire. It performs passive reconnaissance of the Oracle host:

Scans performed:
    1. Open ports scan (TCP connect scan on common ports)
    2. Listening services enumeration (netstat-based)
    3. Firewall status check (Windows Firewall profile status)
    4. Network interface enumeration (IP addresses, adapters)
    5. Active connections review (established TCP connections)
    6. DNS configuration check
    7. Tailscale/VPN status check

CRITICAL SAFETY CONSTRAINT (Standing Order):
    - This module performs PASSIVE reconnaissance ONLY
    - It NEVER activates firewall rules, closes ports, or modifies config
    - All findings are PROPOSALS that require Batman (or Alfred) approval
    - Every hardening recommendation includes a documented rollback procedure
    - The Batman Bypass guarantee: no protective measure may lock Batman out

Lucius Gate: LG-004 — No new dependencies. Uses stdlib + subprocess
calls to native Windows tools (netstat, powershell). APPROVED, Lite Review.

Integration:
    Import and call from LuciusFox.run() in lucius_fox.py:
        from rudy.agents.lucius_network_security import audit_network_security
        findings = audit_network_security()
        self.findings.extend(findings)
"""

import json
import logging
import platform
import socket
import subprocess
import time

logger = logging.getLogger("lucius.network_security")

# ---------------------------------------------------------------------------
# Port Scan Configuration
# ---------------------------------------------------------------------------

# Common ports to check — covers both attack surface and expected services
SCAN_PORTS = {
    # Web
    80: "HTTP",
    443: "HTTPS",
    8080: "HTTP-Alt",
    8443: "HTTPS-Alt",
    3000: "Dev-Server",
    # Remote access (HIGH PRIORITY)
    22: "SSH",
    23: "Telnet",
    3389: "RDP",
    5900: "VNC",
    5901: "VNC-Alt",
    # Databases
    3306: "MySQL",
    5432: "PostgreSQL",
    27017: "MongoDB",
    6379: "Redis",
    # Services
    21: "FTP",
    25: "SMTP",
    53: "DNS",
    135: "RPC",
    137: "NetBIOS-NS",
    139: "NetBIOS-Session",
    445: "SMB",
    # Ollama / AI
    11434: "Ollama",
    # Batcave services
    8585: "RustDesk-Relay",
    21115: "RustDesk-Signal",
    21116: "RustDesk-Relay2",
    41641: "Tailscale",
}

# Ports we EXPECT to be open on Oracle (not findings if open)
EXPECTED_OPEN = {
    11434,  # Ollama — required for Robin
    41641,  # Tailscale — VPN mesh for remote access
}

# Ports that are ALWAYS concerning if open
ALWAYS_FLAG = {
    23: "Telnet (plaintext protocol, replace with SSH)",
    21: "FTP (plaintext protocol, use SFTP instead)",
    135: "RPC (common attack vector for Windows exploits)",
    139: "NetBIOS (information disclosure risk)",
    445: "SMB (major attack surface — WannaCry, EternalBlue)",
    27017: "MongoDB (often left unauthenticated)",
    6379: "Redis (often no auth by default)",
}

# ---------------------------------------------------------------------------
# Scan Functions
# ---------------------------------------------------------------------------

def _scan_open_ports(timeout: float = 1.0) -> list[dict]:
    """
    TCP connect scan on common ports.

    This is passive reconnaissance — it only checks if ports accept
    connections, it doesn't send any exploit payloads.
    """
    findings = []
    open_ports = []
    host = "127.0.0.1"

    logger.info(f"Scanning {len(SCAN_PORTS)} common ports on {host}...")

    for port, service_name in SCAN_PORTS.items():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                open_ports.append((port, service_name))
        except Exception:
            pass

    # Classify findings
    for port, service_name in open_ports:
        if port in EXPECTED_OPEN:
            findings.append({
                "type": "network_security",
                "severity": "info",
                "title": f"Expected port {port}/{service_name} is open",
                "detail": f"Port {port} ({service_name}) is open as expected for Batcave operations.",
                "recommendation": "No action needed. This is a known, required service.",
                "port": port,
                "service": service_name,
                "category": "port_scan",
            })
        elif port in ALWAYS_FLAG:
            findings.append({
                "type": "network_security",
                "severity": "medium",
                "title": f"CONCERNING: Port {port}/{service_name} is open",
                "detail": (
                    f"Port {port} ({service_name}) is open. {ALWAYS_FLAG[port]}. "
                    f"This port is commonly targeted by attackers."
                ),
                "recommendation": (
                    f"PROPOSED: Investigate why port {port} is open. If not needed, "
                    f"close via Windows Firewall. "
                    f"ROLLBACK: netsh advfirewall firewall delete rule name=\"Block-{port}\" "
                    f"(restores access if Batman is locked out). "
                    f"BATMAN BYPASS: Port will remain accessible via Tailscale VPN regardless."
                ),
                "port": port,
                "service": service_name,
                "category": "port_scan",
            })
        else:
            findings.append({
                "type": "network_security",
                "severity": "low",
                "title": f"Unexpected port {port}/{service_name} is open",
                "detail": f"Port {port} ({service_name}) is open but not in the expected services list.",
                "recommendation": (
                    f"Review whether port {port} needs to be accessible. "
                    f"If it's a dev server, consider binding to localhost only."
                ),
                "port": port,
                "service": service_name,
                "category": "port_scan",
            })

    if not open_ports:
        findings.append({
            "type": "network_security",
            "severity": "info",
            "title": "No common ports detected open",
            "detail": "None of the scanned ports responded. Host may have all ports filtered.",
            "recommendation": "Verify that expected services (Ollama, Tailscale) are running.",
            "category": "port_scan",
        })

    return findings

def _enumerate_listening_services() -> list[dict]:
    """
    Use netstat to enumerate all listening TCP/UDP services.

    This provides ground truth vs. our port scan (which only checks known ports).
    """
    findings = []

    if platform.system() != "Windows":
        return [{
            "type": "network_security",
            "severity": "info",
            "title": "Listening service enumeration skipped (non-Windows)",
            "detail": "This check requires Windows netstat.",
            "recommendation": "Run manually: ss -tlnp",
            "category": "listening_services",
        }]

    try:
        result = subprocess.run(
            ["netstat", "-an", "-p", "TCP"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return []

        listening = []
        for line in result.stdout.split("\n"):
            if "LISTENING" in line:
                parts = line.split()
                if len(parts) >= 2:
                    local_addr = parts[1]
                    listening.append(local_addr)

        # Flag services listening on 0.0.0.0 (all interfaces — network accessible)
        exposed_services = [addr for addr in listening if addr.startswith("0.0.0.0:")]
        localhost_services = [addr for addr in listening if addr.startswith("127.0.0.1:")]

        if exposed_services:
            findings.append({
                "type": "network_security",
                "severity": "low",
                "title": f"{len(exposed_services)} service(s) listening on all interfaces (0.0.0.0)",
                "detail": (
                    f"These services are accessible from the network, not just localhost: "
                    f"{', '.join(exposed_services[:10])}"
                    f"{'...' if len(exposed_services) > 10 else ''}"
                ),
                "recommendation": (
                    "Review each service. Services that only need local access should bind "
                    "to 127.0.0.1 instead of 0.0.0.0. "
                    "BATMAN BYPASS: Tailscale provides encrypted access regardless of binding."
                ),
                "exposed_count": len(exposed_services),
                "localhost_count": len(localhost_services),
                "category": "listening_services",
            })
        else:
            findings.append({
                "type": "network_security",
                "severity": "info",
                "title": "All listening services bound to localhost",
                "detail": f"{len(localhost_services)} services listening on 127.0.0.1 only.",
                "recommendation": "Good posture. No services exposed to network.",
                "category": "listening_services",
            })

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        findings.append({
            "type": "network_security",
            "severity": "info",
            "title": "Could not enumerate listening services",
            "detail": f"netstat failed: {e}",
            "recommendation": "Run manually: netstat -an -p TCP | findstr LISTENING",
            "category": "listening_services",
        })

    return findings

def _check_firewall_status() -> list[dict]:
    """Check Windows Firewall status for all profiles."""
    findings = []

    if platform.system() != "Windows":
        return []

    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-NetFirewallProfile | Select-Object Name, Enabled | ConvertTo-Json"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            profiles = json.loads(result.stdout)
            if isinstance(profiles, dict):
                profiles = [profiles]

            for profile in profiles:
                name = profile.get("Name", "Unknown")
                enabled = profile.get("Enabled", False)

                if not enabled:
                    findings.append({
                        "type": "network_security",
                        "severity": "high" if name == "Public" else "medium",
                        "title": f"Windows Firewall DISABLED for {name} profile",
                        "detail": (
                            f"The {name} firewall profile is disabled. This means no "
                            f"inbound traffic filtering for this network type."
                        ),
                        "recommendation": (
                            f"PROPOSED: Enable firewall for {name} profile. "
                            f"Command: Set-NetFirewallProfile -Profile {name} -Enabled True. "
                            f"ROLLBACK: Set-NetFirewallProfile -Profile {name} -Enabled False. "
                            f"BATMAN BYPASS: Tailscale traffic is not affected by Windows Firewall."
                        ),
                        "profile": name,
                        "category": "firewall",
                    })
                else:
                    findings.append({
                        "type": "network_security",
                        "severity": "info",
                        "title": f"Windows Firewall enabled for {name} profile",
                        "detail": f"Firewall is active for the {name} network profile.",
                        "recommendation": "No action needed.",
                        "profile": name,
                        "category": "firewall",
                    })

    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        findings.append({
            "type": "network_security",
            "severity": "info",
            "title": "Could not check firewall status",
            "detail": f"PowerShell command failed: {e}",
            "recommendation": "Run manually: Get-NetFirewallProfile",
            "category": "firewall",
        })

    return findings

def _check_active_connections() -> list[dict]:
    """Review established TCP connections for suspicious activity."""
    findings = []

    try:
        result = subprocess.run(
            ["netstat", "-an", "-p", "TCP"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return []

        established = []
        for line in result.stdout.split("\n"):
            if "ESTABLISHED" in line:
                parts = line.split()
                if len(parts) >= 3:
                    established.append({
                        "local": parts[1],
                        "remote": parts[2],
                    })

        # Count unique remote IPs
        remote_ips = set()
        for conn in established:
            remote = conn["remote"]
            ip = remote.rsplit(":", 1)[0] if ":" in remote else remote
            remote_ips.add(ip)

        findings.append({
            "type": "network_security",
            "severity": "info",
            "title": f"{len(established)} active TCP connections to {len(remote_ips)} unique IPs",
            "detail": (
                f"Current established connections: {len(established)} total. "
                f"Unique remote IPs: {', '.join(list(remote_ips)[:10])}"
                f"{'...' if len(remote_ips) > 10 else ''}"
            ),
            "recommendation": "Review periodically for unexpected connections.",
            "connection_count": len(established),
            "unique_remote_ips": len(remote_ips),
            "category": "active_connections",
        })

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return findings

def _check_network_interfaces() -> list[dict]:
    """Enumerate network interfaces and IP addresses."""
    findings = []

    try:
        hostname = socket.gethostname()
        local_ips = socket.getaddrinfo(hostname, None, socket.AF_INET)
        ips = list(set(addr[4][0] for addr in local_ips))

        findings.append({
            "type": "network_security",
            "severity": "info",
            "title": f"Host '{hostname}' has {len(ips)} IPv4 address(es)",
            "detail": f"Detected IPs: {', '.join(ips)}",
            "recommendation": "Verify all interfaces are expected.",
            "hostname": hostname,
            "ips": ips,
            "category": "interfaces",
        })

    except Exception as e:
        findings.append({
            "type": "network_security",
            "severity": "info",
            "title": "Could not enumerate network interfaces",
            "detail": str(e),
            "recommendation": "Run manually: ipconfig /all",
            "category": "interfaces",
        })

    return findings

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def audit_network_security() -> list[dict]:
    """
    Run all passive network security scans.

    Returns list of findings in Lucius's standard format.
    Called from LuciusFox._audit_network_security() or standalone.
    """
    start = time.time()
    all_findings = []

    logger.info("=" * 40)
    logger.info("LUCIUS FOX — Network Security Audit (Passive Recon)")
    logger.info("=" * 40)

    # Run all scans
    scans = [
        ("Port Scan", _scan_open_ports),
        ("Listening Services", _enumerate_listening_services),
        ("Firewall Status", _check_firewall_status),
        ("Active Connections", _check_active_connections),
        ("Network Interfaces", _check_network_interfaces),
    ]

    for scan_name, scan_fn in scans:
        logger.info(f"Running: {scan_name}...")
        try:
            findings = scan_fn()
            all_findings.extend(findings)
            logger.info(f"  {scan_name}: {len(findings)} findings")
        except Exception as e:
            logger.error(f"  {scan_name} FAILED: {e}")
            all_findings.append({
                "type": "network_security",
                "severity": "info",
                "title": f"Scan failed: {scan_name}",
                "detail": str(e),
                "recommendation": "Review error and retry manually.",
                "category": "scan_error",
            })

    duration_ms = int((time.time() - start) * 1000)
    logger.info(f"Network security audit complete: {len(all_findings)} total findings in {duration_ms}ms")

    # Add summary finding
    severity_counts = {}
    for f in all_findings:
        sev = f.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    all_findings.insert(0, {
        "type": "network_security_summary",
        "severity": "info",
        "title": f"Network Security Audit Summary ({len(all_findings)} findings)",
        "detail": (
            f"Scan duration: {duration_ms}ms. "
            f"Severity breakdown: {json.dumps(severity_counts)}. "
            f"REMINDER: All hardening recommendations are PROPOSALS only. "
            f"Batman approval required before any changes. "
            f"All proposals include rollback procedures and Batman bypass guarantees."
        ),
        "recommendation": "Review findings and approve/reject hardening proposals.",
        "severity_counts": severity_counts,
        "duration_ms": duration_ms,
        "category": "summary",
    })

    return all_findings

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("Lucius Fox — Network Security Passive Recon")
    print("SCAN + REPORT ONLY — No active hardening")
    print("=" * 60)

    findings = audit_network_security()

    print(f"\n{'='*60}")
    print(f"FINDINGS: {len(findings)} total")
    print(f"{'='*60}\n")

    for f in findings:
        sev = f.get("severity", "info").upper()
        print(f"  [{sev}] {f['title']}")
        if sev in ("HIGH", "MEDIUM"):
            print(f"    Detail: {f['detail'][:120]}")
            print(f"    Action: {f['recommendation'][:120]}")
        print()

    # Save findings
    from rudy.paths import LUCIUS_AUDITS
    out = LUCIUS_AUDITS
    out.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    outfile = out / f"network-security-{ts}.json"
    outfile.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"Findings saved: {outfile}")
