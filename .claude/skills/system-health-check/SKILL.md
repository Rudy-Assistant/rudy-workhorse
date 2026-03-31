---
name: system-health-check
version: 1.0.0
description: Quick health check of Oracle system vitals
task_type: health_check
agent: robin
triggers:
  - health check
  - system health
  - is oracle alive
  - heartbeat
---

# System Health Check

Quick vitals check of the Oracle workhorse — designed for frequent polling.

## Capabilities
- CPU usage (current + 5-min average)
- RAM usage (used/total)
- Disk free space (all drives)
- Critical service status (OpenSSH, Ollama, Task Scheduler)
- Uptime
- Network connectivity (localhost + internet)

## Execution Steps
1. `Get-Counter '\Processor(_Total)\% Processor Time'` for CPU
2. `Get-CimInstance Win32_OperatingSystem` for RAM
3. `Get-PSDrive -PSProvider FileSystem` for disk
4. Check critical services: sshd, ollama, Schedule
5. `(Get-CimInstance Win32_OperatingSystem).LastBootUpTime` for uptime
6. Test-NetConnection localhost -Port 22 (SSH), 11434 (Ollama)

## Output Format
```json
{
  "timestamp": "ISO-8601",
  "cpu_pct": 0,
  "ram_used_gb": 0,
  "ram_total_gb": 0,
  "disk_free_gb": {"C": 0},
  "services": {"sshd": "running", "ollama": "running"},
  "uptime_hours": 0,
  "connectivity": {"ssh": true, "ollama": true, "internet": true},
  "status": "healthy|degraded|critical"
}
```

## Thresholds
- CPU > 90% sustained → degraded
- RAM > 90% → degraded
- Disk < 5GB free → critical
- Any critical service down → critical
- Uptime < 1hr after unexpected reboot → degraded
