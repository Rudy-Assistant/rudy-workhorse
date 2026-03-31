# Session 33 Handoff — Executable Robin Task Loop

**From**: Alfred (Session 32, continuation)
**Date**: 2026-03-31
**Repo**: `Rudy-Assistant/rudy-workhorse` (cloned at `C:\Users\ccimi\rudy-workhorse`)
**RUDY_DATA**: `C:\Users\ccimi\rudy-data` (NOT under repo root)

---

## HARD RULE: Read `CLAUDE.md` first. Then read this document.

---

## LIVE DELEGATION PROOF (Session 32 Continuation)

Two delegations were sent through the broker and processed by Robin live:

```
02:48:58 Processing delegation del-batman-demo: [health_check] Live demo for Batman
02:49:00 Result sent to o3py4q20 (success=True, 0.2s)

02:49:37 Processing delegation del-batman-shell: [shell] Git status check
02:49:40 Result sent to o3py4q20 (success=False, 0.9s)
```

The health_check path is proven. Shell tasks need command quoting fixes for Windows paths.

---

## ROBIN EXECUTABLE TASK LOOP

Robin: execute these tasks IN ORDER using the broker delegation path. Each task
is a `send-message` to Robin via `http://localhost:7899/send-message`. Alfred
(or the next session) sends; Robin's bridge_runner picks up and executes.

### Task 1: Delete robin_inbox_executor.py (Build-vs-Buy violation)

```powershell
# Robin or Alfred executes directly — this is a filesystem delete
Remove-Item "C:\Users\ccimi\rudy-workhorse\rudy\robin_inbox_executor.py" -ErrorAction SilentlyContinue
# Verify
Test-Path "C:\Users\ccimi\rudy-workhorse\rudy\robin_inbox_executor.py"  # Should be False
```

**Why**: Finding LG-S32-002. This file duplicates existing bridge infrastructure.

### Task 2: Fix n8n PATH for cmd.exe

```powershell
# Requires elevated terminal
$nodePath = "C:\Program Files\nodejs"
$currentPath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
if ($currentPath -notlike "*$nodePath*") {
    [System.Environment]::SetEnvironmentVariable("PATH", "$currentPath;$nodePath", "Machine")
    Write-Output "Added nodejs to SYSTEM PATH"
} else {
    Write-Output "nodejs already in SYSTEM PATH"
}
```

Then:
```powershell
npm install -g n8n
n8n start  # http://localhost:5678 — complete setup wizard
# Settings > API > Create API Key
[System.Environment]::SetEnvironmentVariable('N8N_API_KEY', '<key>', 'User')
```

### Task 3: Registry Audit (delegate via broker)

Alfred sends to Robin:
```json
{
  "type": "delegate",
  "id": "del-registry-audit",
  "sender": "alfred",
  "task": {
    "type": "shell",
    "title": "Audit registry.json — verify 116 modules active",
    "command": "C:\\Python312\\python.exe -c \"import json; r=json.load(open(r'C:\\Users\\ccimi\\rudy-workhorse\\registry.json')); print(f'Total: {len(r.get(chr(109)+chr(111)+chr(100)+chr(117)+chr(108)+chr(101)+chr(115),[]))} modules'); [print(f'  {m[chr(110)+chr(97)+chr(109)+chr(101)]}') for m in r.get(chr(109)+chr(111)+chr(100)+chr(117)+chr(108)+chr(101)+chr(115),[])]\"",
    "priority": 30,
    "status": "pending"
  }
}
```

### Task 4: Agnix Validation (delegate via broker)

```json
{
  "type": "delegate",
  "id": "del-agnix-validate",
  "sender": "alfred",
  "task": {
    "type": "shell",
    "title": "Run agnix on CLAUDE.md and skill files",
    "command": "cd C:\\Users\\ccimi\\rudy-workhorse && npx agnix .",
    "priority": 40,
    "status": "pending"
  }
}
```

### Task 5: Security Scan (delegate via broker)

```json
{
  "type": "delegate",
  "id": "del-security-sweep",
  "sender": "alfred",
  "task": {
    "type": "security_scan",
    "title": "Trail of Bits security sweep on rudy/ package",
    "description": "Use installed Trail of Bits skills to audit rudy/ for vulnerabilities",
    "priority": 30,
    "status": "pending"
  }
}
```

### Task 6: Verify RobinContinuous Scheduled Task

```powershell
Get-ScheduledTask -TaskPath "\Batcave\" | Format-Table TaskName, State, LastRunTime, LastTaskResult
# Verify RobinContinuous shows LastTaskResult = 0 and correct WorkingDirectory
(Get-ScheduledTask -TaskPath "\Batcave\" -TaskName "RobinContinuous").Actions | Format-List
```

---

## DELEGATION PROTOCOL REFERENCE

### How to send a task to Robin from PowerShell:

```powershell
# 1. Register Alfred (once per session)
$regBody = '{"pid":99999,"cwd":"C:\\Users\\ccimi\\rudy-workhorse","git_root":"C:\\Users\\ccimi\\rudy-workhorse","summary":"Alfred Session 33"}'
$reg = Invoke-RestMethod -Uri 'http://localhost:7899/register' -Method Post -ContentType 'application/json' -Body $regBody
$alfredId = $reg.id

# 2. Get Robin's peer ID from heartbeat
$hb = Get-Content "C:\Users\ccimi\rudy-data\bridge-heartbeat.json" -Raw | ConvertFrom-Json
$robinId = $hb.robin_id

# 3. Send delegation
$msg = '{"type":"delegate","id":"del-xxx","sender":"alfred","task":{"type":"health_check","title":"Test","priority":50,"status":"pending"}}'
$sendBody = @{from_id=$alfredId; to_id=$robinId; text=$msg} | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://localhost:7899/send-message' -Method Post -ContentType 'application/json' -Body $sendBody

# 4. Check results in bridge log
Get-Content "C:\Users\ccimi\rudy-data\logs\bridge-runner.log" -Tail 10
```

### How to send via Python (preferred for complex tasks):

```python
import sys; sys.path.insert(0, r'C:\Users\ccimi\rudy-workhorse')
from rudy.alfred_delegate import delegate_and_wait, delegate_fire_and_forget

# Fire and forget
del_id = delegate_fire_and_forget("health_check", "Quick health check")

# Or wait for result (blocks up to 60s)
result = delegate_and_wait("health_check", "Health check with result")
print(result)  # {"success": True, "output": "...", ...}

# Shell command
result = delegate_and_wait("shell", "Run git status", command="git status")
```

---

## CRITICAL PATHS

| Item | Path |
|------|------|
| RUDY_DATA | `C:\Users\ccimi\rudy-data` |
| Repo | `C:\Users\ccimi\rudy-workhorse` |
| Bridge log | `C:\Users\ccimi\rudy-data\logs\bridge-runner.log` |
| Heartbeat | `C:\Users\ccimi\rudy-data\bridge-heartbeat.json` |
| Robin taskqueue | `C:\Users\ccimi\rudy-data\robin-taskqueue\active.json` |
| Git | `C:\Program Files\Git\cmd\git.exe` |
| Python | `C:\Python312\python.exe` |
| Node | `C:\Program Files\nodejs\node.exe` |
| Broker | `http://localhost:7899` |
| Ollama | `http://localhost:11434` |

## FINDINGS (Open)

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| LG-S32-001 | MEDIUM | Alfred ran local I/O instead of delegating to Robin | Fixed — Hard Rule #6 |
| LG-S32-002 | HIGH | Built robin_inbox_executor.py (Build-vs-Buy violation) | **OPEN — delete file** |
| LG-S32-003 | HIGH | Lucius gate bypassed — pre_commit_check not enforced | OPEN |
| LG-S32-004 | CRITICAL | RUDY_DATA path mismatch caused inbox failures | Fixed — documented |

## DEFERRED (Lower Priority)

- claude-mem evaluation (persistent memory plugin)
- Codex adversarial review setup (cross-model code review)
- Lucius pre-commit hook enforcement
- Vault backfill verification (Sessions 27-32 written, need verification)
