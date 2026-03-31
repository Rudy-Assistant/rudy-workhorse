---
name: app-launcher
version: 1.0.0
description: Launch and manage Windows applications as Bruce
task_type: shell
agent: robin
capabilities:
  - Windows-MCP Shell
  - human_simulation.SessionManager
triggers:
  - open app
  - launch program
  - start application
  - run program
---

# App Launcher

Launch Windows applications with human-like timing and manage their lifecycle.

## Common Applications
| App | Command | Notes |
|-----|---------|-------|
| Chrome | `start chrome` | Use FingerprintManager for stealth |
| File Explorer | `explorer.exe {path}` | |
| Notepad | `notepad.exe {file}` | |
| VS Code | `code {path}` | If installed |
| PowerShell | `powershell.exe` | |
| Task Manager | `taskmgr.exe` | |
| Settings | `ms-settings:` | URI protocol |
| Obsidian | `start obsidian://` | Vault access |

## Execution Steps
1. Check if app is already running (`Get-Process`)
2. Launch with human-like delay (SessionManager warmup)
3. Wait for window to appear (Snapshot polling)
4. Verify app is responsive
5. Return window handle / process info

## Output Format
```json
{
  "app": "name",
  "pid": 0,
  "window_title": "",
  "status": "launched|already_running|error",
  "launch_time_ms": 0
}
```
