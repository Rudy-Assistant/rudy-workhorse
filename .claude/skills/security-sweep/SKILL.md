---
name: security-sweep
version: 1.0.0
description: Security scan of Oracle system and network
task_type: security_scan
agent: robin
triggers:
  - security scan
  - security sweep
  - check ports
  - vulnerability check
---

# Security Sweep

Security assessment of the Oracle workhorse system.

## Capabilities
- Open port scan (localhost common ports)
- Windows Defender status and last scan
- Firewall rule audit
- Failed login attempts (Security event log)
- Suspicious process detection
- Auto-start program audit
- Tailscale status check

## Execution Steps
1. Scan common ports: 22 (SSH), 80, 443, 3389 (RDP), 7777 (Robin GUI),
   7899 (peers broker), 11434 (Ollama), 5900 (VNC)
2. `Get-MpComputerStatus` for Defender status
3. `Get-NetFirewallRule -Enabled True` for firewall audit
4. `Get-WinEvent -LogName Security -MaxEvents 50` for failed logins (4625)
5. Check running processes against known-good baseline
6. `Get-CimInstance Win32_StartupCommand` for auto-start programs
7. `tailscale status` for VPN mesh

## Output Format
```json
{
  "timestamp": "ISO-8601",
  "open_ports": [{"port": 22, "service": "SSH", "expected": true}],
  "defender": {"enabled": true, "last_scan": "", "definitions_age_days": 0},
  "firewall": {"enabled": true, "unexpected_rules": []},
  "failed_logins": {"count_24h": 0, "sources": []},
  "suspicious_processes": [],
  "autostart": {"count": 0, "unexpected": []},
  "tailscale": {"connected": true, "peers": 0},
  "risk_level": "low|medium|high|critical"
}
```

## Escalation Triggers
- Unknown open port → escalate to Alfred
- Defender disabled → escalate immediately
- Failed login spike (>10 in 1hr) → escalate to Alfred + notify Batman
- Unknown autostart entry → escalate to Alfred
