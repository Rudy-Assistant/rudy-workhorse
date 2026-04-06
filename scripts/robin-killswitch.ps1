# Robin Killswitch (S195 / P0-C)
# Reads canonical Robin PIDs from rudy-data\robin-status.json (NO HARDCODED PIDs).
# Sends graceful TERM (CTRL_BREAK_EVENT) first; force-kills after 10s.
# Tears down child processes. Logs to rudy-data\robin-killswitch-{ts}.log.
# Updates robin-status.json status to KILLED so Sentinel does not respawn.
#
# Flags:
#   -DryRun    list what would be killed, kill nothing
#   -Restart   after killing, relaunch via canonical launcher
#
# See docs\runbooks\robin-killswitch.md for runbook.

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $repo "rudy-data\robin-killswitch-$ts.log"
$statusPath = Join-Path $repo 'rudy-data\robin-status.json'

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format o), $msg
    Write-Host $line
    Add-Content -Path $logPath -Value $line
}

Log "Robin killswitch start (DryRun=$DryRun Restart=$Restart)"

if (-not (Test-Path $statusPath)) {
    Log "FATAL: $statusPath not found. Cannot resolve Robin PIDs without it."
    exit 2
}

try {
    $status = Get-Content $statusPath -Raw | ConvertFrom-Json
} catch {
    Log "FATAL: failed to parse robin-status.json: $_"
    exit 2
}

$pids = @()
foreach ($key in 'robin_main_pid','sentinel_pid','main_pid','pid') {
    if ($status.PSObject.Properties.Name -contains $key -and $status.$key) {
        $pids += [int]$status.$key
    }
}
if ($status.PSObject.Properties.Name -contains 'pids') { $pids += $status.pids }
$pids = $pids | Sort-Object -Unique

if (-not $pids -or $pids.Count -eq 0) {
    Log "No PIDs found in robin-status.json (keys searched: robin_main_pid, sentinel_pid, main_pid, pid, pids). Nothing to kill."
    if ($Restart) { Log "--restart requested but no PIDs to kill; proceeding to relaunch." }
    else { exit 0 }
}

# Resolve children up front so we don't lose them after parent exits.
$targets = @()
foreach ($p in $pids) {
    try {
        $proc = Get-Process -Id $p -ErrorAction Stop
        $targets += $proc
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$p" -ErrorAction SilentlyContinue
        foreach ($c in $children) {
            try { $targets += Get-Process -Id $c.ProcessId -ErrorAction Stop } catch {}
        }
    } catch {
        Log "PID $p not running (already dead)."
    }
}
$targets = $targets | Sort-Object Id -Unique

Log ("Targets: " + (($targets | ForEach-Object { "$($_.Id)/$($_.ProcessName)" }) -join ', '))

if ($DryRun) {
    Log "DRY RUN: no processes terminated. Exiting."
    exit 0
}

# Phase 1: graceful close (10s grace)
foreach ($t in $targets) {
    try {
        Log "TERM PID=$($t.Id) name=$($t.ProcessName)"
        $t.CloseMainWindow() | Out-Null
    } catch { Log "  CloseMainWindow failed: $_" }
}
Start-Sleep -Seconds 10

# Phase 2: force kill survivors
foreach ($t in $targets) {
    try {
        $still = Get-Process -Id $t.Id -ErrorAction Stop
        Log "KILL PID=$($still.Id) name=$($still.ProcessName)"
        Stop-Process -Id $still.Id -Force -ErrorAction Stop
    } catch {
        Log "PID=$($t.Id) already gone."
    }
}

# Phase 3: mark status KILLED
try {
    $status | Add-Member -NotePropertyName 'status' -NotePropertyValue 'KILLED' -Force
    $status | Add-Member -NotePropertyName 'killed_at' -NotePropertyValue (Get-Date -Format o) -Force
    $status | Add-Member -NotePropertyName 'killed_by' -NotePropertyValue 'robin-killswitch' -Force
    $status | ConvertTo-Json -Depth 8 | Set-Content -Path $statusPath -Encoding UTF8
    Log "robin-status.json updated to KILLED."
} catch {
    Log "WARN: failed to update robin-status.json: $_"
}

if ($Restart) {
    $launcher = Join-Path $repo 'scripts\start-launcher-loop.bat'
    if (Test-Path $launcher) {
        Log "Restart requested -> launching $launcher"
        Start-Process -FilePath $launcher -WorkingDirectory $repo -WindowStyle Hidden
    } else {
        Log "Restart requested but canonical launcher not found at $launcher"
    }
}

Log "Killswitch complete."
exit 0
