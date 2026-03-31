---
name: powershell-execute
version: 1.0.0
description: Execute PowerShell commands and scripts on Oracle
task_type: shell
agent: robin
triggers:
  - run powershell
  - execute command
  - shell command
  - run script
---

# PowerShell Execute

Execute PowerShell commands or scripts on the Oracle workhorse.

## Capabilities
- Single command execution
- Script file execution (.ps1)
- Output capture (stdout + stderr)
- Exit code validation
- Timeout enforcement

## Execution Steps
1. Validate command against blocklist
2. Set execution timeout (default: 60s, max: 300s)
3. Execute via Windows-MCP Shell or Start-Process
4. Capture stdout, stderr, exit code
5. Return structured result

## Security Rules
- BLOCKED commands: `Remove-Item -Recurse C:\`, `Format-Volume`, `Stop-Computer`,
  `Restart-Computer`, `Set-ExecutionPolicy Unrestricted`, any registry deletion
- Commands modifying system files require escalation to Alfred
- Network commands (Invoke-WebRequest to external) require authorization
- No credential handling — escalate to Batman

## Output Format
```json
{
  "command": "the-command-run",
  "exit_code": 0,
  "stdout": "",
  "stderr": "",
  "duration_ms": 0,
  "status": "success|error|timeout|blocked"
}
```
