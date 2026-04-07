# reap-stale-mcp.ps1 -- kill leaked windows-mcp.exe python processes from prior Cowork sessions.
#
# Background: every Cowork session start spawns a pair of windows-mcp.exe processes
# (a python.exe parent + python.exe child) under
# %APPDATA%\Claude\Claude Extensions\ant.dir.cursortouch.windows-mcp*\.venv\Scripts\.
# Cowork does NOT reap them at session end, so they accumulate. By S211 we had
# 8 leaked procs from 4 prior sessions consuming RAM for nothing.
#
# Strategy: find all python.exe procs whose CommandLine references windows-mcp,
# group by CreationDate (each session pair shares a timestamp), and kill any
# group whose CreationDate is older than the current Cowork session start.
# The "current session" is identified as the NEWEST pair -- we never touch it.
#
# Safe to run any time. Idempotent. No admin required.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\reap-stale-mcp.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\reap-stale-mcp.ps1 -DryRun
#
# Author: Alfred S211 (post-Batman directive to prevent MCP leak recurrence).

param([switch]$DryRun)

$logPath = "C:\Users\ccimi\rudy-data\logs\reap-stale-mcp.log"
$logDir  = Split-Path $logPath -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    $line | Out-File -Append -FilePath $logPath -Encoding utf8
    Write-Host $line
}

Log "reap-stale-mcp start (DryRun=$DryRun)"

$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*windows-mcp*' }

if (-not $procs) {
    Log "No windows-mcp python procs found. Nothing to do."
    exit 0
}

Log "Found $($procs.Count) windows-mcp python procs total"

# Group by CreationDate string (pair-level granularity).
$groups = $procs | Group-Object { $_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss') } | Sort-Object Name

if ($groups.Count -le 1) {
    Log "Only $($groups.Count) session group present -- nothing stale to reap."
    exit 0
}

# Newest group = current Cowork session. Never touch it.
$newest = $groups[-1]
Log "Newest (active) session: $($newest.Name) -- $($newest.Group.Count) procs -- PROTECTED"

$reaped = 0
foreach ($g in $groups[0..($groups.Count - 2)]) {
    Log "Stale session: $($g.Name) -- $($g.Group.Count) procs"
    foreach ($p in $g.Group) {
        Log "  -> killing PID $($p.ProcessId)"
        if (-not $DryRun) {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                $reaped++
            } catch {
                Log "     FAILED: $($_.Exception.Message)"
            }
        }
    }
}

Log "reap-stale-mcp done -- reaped $reaped procs"
