---
name: service-monitor
version: 1.0.0
description: Monitor and manage Windows services and scheduled tasks
task_type: health_check
agent: robin
capabilities:
  - Windows-MCP Shell (PowerShell)
  - robin_sentinel.SentinelObserver
triggers:
  - check service
  - service status
  - restart service
  - monitor services
  - scheduled task status
---

# Service Monitor

Monitor, check, and manage Windows services and scheduled tasks on Oracle.

## Critical Services
| Service | Display Name | Port | Recovery |
|---------|-------------|------|----------|
| sshd | OpenSSH SSH Server | 22 | Auto-restart |
| OllamaService | Ollama | 11434 | Auto-restart |
| Schedule | Task Scheduler | — | Critical |
| WinRM | Windows Remote Management | 5985 | Auto-restart |

## Execution Steps
1. Query service status: `Get-Service -Name {name}`
2. Check port availability: `Test-NetConnection localhost -Port {port}`
3. If service down + auto-restart authorized:
   `Restart-Service -Name {name} -Force`
4. Verify recovery: re-check status + port
5. Log to sentinel immune memory

## Scheduled Task Monitoring
- `Get-ScheduledTask | Where-Object {$_.State -ne 'Disabled'}`
- Check last run result: `(Get-ScheduledTaskInfo -TaskName {name}).LastTaskResult`
- 0 = success, anything else = investigate

## Auto-Recovery Rules
- OpenSSH down → restart immediately (critical for remote access)
- Ollama down → restart (Robin's LLM depends on it)
- Task Scheduler down → ESCALATE (too critical for auto-fix)
- Unknown service down → log finding, do NOT restart

## Output Format
```json
{
  "services": [{"name": "", "status": "", "port_open": true, "action": "none|restarted|escalated"}],
  "tasks": [{"name": "", "state": "", "last_result": 0, "last_run": ""}],
  "actions_taken": [],
  "status": "all_healthy|recovered|degraded|critical"
}
```
