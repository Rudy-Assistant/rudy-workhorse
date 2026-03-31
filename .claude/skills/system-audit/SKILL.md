---
name: system-audit
version: 1.0.0
description: Comprehensive system audit for Oracle workhorse
task_type: audit
agent: robin
triggers:
  - system audit
  - disk space
  - check services
  - process list
---

# System Audit

Perform a comprehensive audit of the Oracle workhorse system state.

## Capabilities
- Disk space usage across all drives
- Running services status (critical: OpenSSH, Ollama, Task Scheduler)
- Top processes by CPU and memory
- Windows Update status
- Scheduled task health
- Network adapter status

## Execution Steps
1. Run `Get-PSDrive -PSProvider FileSystem` for disk usage
2. Run `Get-Service | Where-Object {$_.Status -eq 'Running'}` for services
3. Run `Get-Process | Sort-Object CPU -Descending | Select-Object -First 20` for top processes
4. Check `Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 5` for recent updates
5. Run `Get-ScheduledTask | Where-Object {$_.State -ne 'Disabled'}` for active tasks
6. Compile findings into structured JSON report

## Output Format
```json
{
  "timestamp": "ISO-8601",
  "disk": [{"drive": "C:", "used_gb": 0, "free_gb": 0, "pct_used": 0}],
  "services": {"running": 0, "stopped_critical": []},
  "top_processes": [{"name": "", "cpu": 0, "mem_mb": 0}],
  "updates": {"last_installed": "", "pending": 0},
  "tasks": {"active": 0, "failed_recent": []},
  "status": "healthy|degraded|critical"
}
```

## Failure Modes
- WMI query timeout → retry with `-TimeoutSec 30`
- Access denied → run as current user, skip admin-only checks
- Service not found → log as finding, not error
