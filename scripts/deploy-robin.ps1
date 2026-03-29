<# 
    Deploy Robin -- Oracle Setup Script
    
    Run this on Oracle (Workhorse PC) after merging PR #3.
    Registers Robin Sentinel as a scheduled task, validates environment,
    and performs first boot sequence.

    Usage (elevated PowerShell):
        .\deploy-robin.ps1
        .\deploy-robin.ps1 -SkipGitPull    # If you already pulled
        .\deploy-robin.ps1 -TestOnly       # Validate without registering
#>

param(
    [switch]$SkipGitPull,
    [switch]$TestOnly
)

$ErrorActionPreference = "Stop"
$RudyRoot = "$env:USERPROFILE\Desktop\rudy-workhorse"
$RudyData = "$env:USERPROFILE\Desktop\rudy-data"
$RudyLogs = "$env:USERPROFILE\Desktop\rudy-logs"

Write-Host "=== ROBIN DEPLOYMENT ===" -ForegroundColor Cyan
Write-Host "Oracle: $env:COMPUTERNAME" -ForegroundColor Gray
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: Pull latest from main
# ---------------------------------------------------------------------------
if (-not $SkipGitPull) {
    Write-Host "[1/6] Pulling latest from main..." -ForegroundColor Yellow
    Push-Location $RudyRoot
    try {
        git checkout main 2>&1 | Out-Null
        git pull origin main 2>&1
        Write-Host "  OK: pulled latest" -ForegroundColor Green
    } catch {
        Write-Host "  WARN: git pull failed -- $($_.Exception.Message)" -ForegroundColor Red
    }
    Pop-Location
} else {
    Write-Host "[1/6] Skipping git pull (--SkipGitPull)" -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# Step 2: Validate Robin files exist
# ---------------------------------------------------------------------------
Write-Host "[2/6] Validating Robin files..." -ForegroundColor Yellow

$requiredFiles = @(
    "$RudyRoot\rudy\agents\robin_sentinel.py",
    "$RudyRoot\rudy\agents\robin_bridge.py",
    "$RudyRoot\rudy\agents\robin_presence.py",
    "$RudyRoot\rudy\tools\notion_client.py",
    "$RudyRoot\rudy\config\known-good-state.json"
)

$missing = @()
foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "  OK: $(Split-Path $file -Leaf)" -ForegroundColor Green
    } else {
        Write-Host "  MISSING: $file" -ForegroundColor Red
        $missing += $file
    }
}

if ($missing.Count -gt 0) {
    Write-Host "`nERROR: Missing $($missing.Count) required files. Aborting." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Step 3: Ensure directories exist
# ---------------------------------------------------------------------------
Write-Host "[3/6] Ensuring data directories..." -ForegroundColor Yellow

foreach ($dir in @($RudyData, $RudyLogs, "$env:USERPROFILE\Desktop\rudy-commands")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  Created: $dir" -ForegroundColor Green
    } else {
        Write-Host "  Exists: $(Split-Path $dir -Leaf)" -ForegroundColor Green
    }
}

# Copy known-good-state.json to rudy-data if not present
$kgsTarget = "$RudyData\known-good-state.json"
$kgsSource = "$RudyRoot\rudy\config\known-good-state.json"
if (-not (Test-Path $kgsTarget)) {
    Copy-Item $kgsSource $kgsTarget
    Write-Host "  Copied known-good-state.json to rudy-data" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 4: Python environment check
# ---------------------------------------------------------------------------
Write-Host "[4/6] Checking Python environment..." -ForegroundColor Yellow

try {
    $pyVersion = python --version 2>&1
    Write-Host "  $pyVersion" -ForegroundColor Green
    
    # Syntax-check Robin modules
    python -c "import py_compile; py_compile.compile('$($RudyRoot.Replace('\','/'))/rudy/agents/robin_sentinel.py', doraise=True)" 2>&1
    Write-Host "  Syntax OK: robin_sentinel.py" -ForegroundColor Green
    
    python -c "import py_compile; py_compile.compile('$($RudyRoot.Replace('\','/'))/rudy/agents/robin_bridge.py', doraise=True)" 2>&1
    Write-Host "  Syntax OK: robin_bridge.py" -ForegroundColor Green
    
    python -c "import py_compile; py_compile.compile('$($RudyRoot.Replace('\','/'))/rudy/agents/robin_presence.py', doraise=True)" 2>&1
    Write-Host "  Syntax OK: robin_presence.py" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Python check failed -- $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Step 5: Register Scheduled Tasks
# ---------------------------------------------------------------------------
Write-Host "[5/6] Registering scheduled tasks..." -ForegroundColor Yellow

if ($TestOnly) {
    Write-Host "  SKIP (--TestOnly mode)" -ForegroundColor Gray
} else {
    # Robin Sentinel -- runs at startup + continuous mode
    $sentinelAction = New-ScheduledTaskAction `
        -Execute "python" `
        -Argument "-m rudy.agents.robin_sentinel --continuous" `
        -WorkingDirectory $RudyRoot
    
    $sentinelTrigger = New-ScheduledTaskTrigger -AtStartup
    $sentinelSettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 5) `
        -ExecutionTimeLimit (New-TimeSpan -Days 365)
    
    try {
        Unregister-ScheduledTask -TaskName "RobinSentinel" -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask `
            -TaskName "RobinSentinel" `
            -Action $sentinelAction `
            -Trigger $sentinelTrigger `
            -Settings $sentinelSettings `
            -Description "Robin Sentinel -- boot health cascade + continuous monitoring" `
            -RunLevel Highest | Out-Null
        Write-Host "  Registered: RobinSentinel (at startup, continuous)" -ForegroundColor Green
    } catch {
        Write-Host "  ERROR registering RobinSentinel: $($_.Exception.Message)" -ForegroundColor Red
    }
    
    # Robin Presence -- runs at logon for HID monitoring
    $presenceAction = New-ScheduledTaskAction `
        -Execute "python" `
        -Argument "-m rudy.agents.robin_presence" `
        -WorkingDirectory $RudyRoot
    
    $presenceTrigger = New-ScheduledTaskTrigger -AtLogon
    $presenceSettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 5) `
        -ExecutionTimeLimit (New-TimeSpan -Days 365)
    
    try {
        Unregister-ScheduledTask -TaskName "RobinPresence" -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask `
            -TaskName "RobinPresence" `
            -Action $presenceAction `
            -Trigger $presenceTrigger `
            -Settings $presenceSettings `
            -Description "Robin Presence Monitor -- HID tracking + handoff management" `
            -RunLevel Highest | Out-Null
        Write-Host "  Registered: RobinPresence (at logon)" -ForegroundColor Green
    } catch {
        Write-Host "  ERROR registering RobinPresence: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# ---------------------------------------------------------------------------
# Step 6: First boot test
# ---------------------------------------------------------------------------
Write-Host "[6/6] Running first boot sequence..." -ForegroundColor Yellow

Push-Location $RudyRoot
try {
    $result = python -m rudy.agents.robin_sentinel --phase 0 2>&1
    Write-Host "  Phase 0 (self-check):" -ForegroundColor Cyan
    Write-Host "  $result" -ForegroundColor Gray
    
    Write-Host ""
    Write-Host "=== DEPLOYMENT COMPLETE ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Robin is ready. Next steps:" -ForegroundColor White
    Write-Host "  1. Start Sentinel:  python -m rudy.agents.robin_sentinel" -ForegroundColor Gray
    Write-Host "  2. Start Presence:  python -m rudy.agents.robin_presence" -ForegroundColor Gray
    Write-Host "  3. Check status:    python -m rudy.agents.robin_sentinel --status" -ForegroundColor Gray
    Write-Host "  4. Test handoff:    python -m rudy.agents.robin_presence --handoff 0.5" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Scheduled tasks will auto-start on next boot/logon." -ForegroundColor Yellow
} catch {
    Write-Host "  First boot error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  This may be expected if running outside Oracle environment." -ForegroundColor Gray
}
Pop-Location
