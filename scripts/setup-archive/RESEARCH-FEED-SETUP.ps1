# Workhorse Research Feed - Setup & Scheduler Configuration
# Run this as Administrator in PowerShell to configure automated daily runs

param(
    [switch]$Quick,      # Use quick mode (5 feeds, 5 items)
    [switch]$NoSchedule, # Skip scheduler setup
    [switch]$TestRun     # Run immediately after setup
)

$ErrorActionPreference = "Stop"
$ScriptDir = "C:\Users\C\Desktop"
$ScriptName = "workhorse-research-feed.py"
$LogDir = "$ScriptDir\rudy-logs"
$Schedule = if ($Quick) { "--quick" } else { "" }

Write-Host "=" * 80
Write-Host "Workhorse Research Feed - Setup Utility"
Write-Host "=" * 80
Write-Host ""

# Verify Python installation
Write-Host "Checking Python installation..." -ForegroundColor Cyan
try {
    $pythonVer = python --version 2>&1
    Write-Host "✓ Found: $pythonVer" -ForegroundColor Green
} catch {
    Write-Host "✗ Python not found. Install from https://www.python.org/" -ForegroundColor Red
    exit 1
}

# Verify required packages
Write-Host ""
Write-Host "Checking Python dependencies..." -ForegroundColor Cyan
$packages = @("requests", "beautifulsoup4", "feedparser")
foreach ($pkg in $packages) {
    try {
        python -c "import $pkg" 2>$null
        Write-Host "✓ $pkg installed" -ForegroundColor Green
    } catch {
        Write-Host "✗ $pkg missing. Installing..." -ForegroundColor Yellow
        pip install $pkg | Out-Null
        Write-Host "✓ $pkg installed" -ForegroundColor Green
    }
}

# Create log directory
Write-Host ""
Write-Host "Setting up directories..." -ForegroundColor Cyan
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Host "✓ Created $LogDir" -ForegroundColor Green
} else {
    Write-Host "✓ Directory exists: $LogDir" -ForegroundColor Green
}

# Test script
Write-Host ""
Write-Host "Testing script execution..." -ForegroundColor Cyan
Push-Location $ScriptDir
try {
    $output = python $ScriptName --quick 2>&1 | Select-Object -First 20
    if ($output) {
        Write-Host "✓ Script executes successfully" -ForegroundColor Green
        Write-Host ""
        Write-Host "First 5 lines of output:" -ForegroundColor Gray
        $output | Select-Object -First 5 | Write-Host
    }
} catch {
    Write-Host "✗ Script execution failed: $_" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# Setup scheduled task
if (-not $NoSchedule) {
    Write-Host ""
    Write-Host "Setting up Windows Task Scheduler..." -ForegroundColor Cyan
    Write-Host ""

    $taskName = "WorkhorseResearchFeed"
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

    if ($existingTask) {
        Write-Host "! Task '$taskName' already exists" -ForegroundColor Yellow
        $response = Read-Host "Replace existing task? (y/N)"
        if ($response -ne "y") {
            Write-Host "Skipped task setup" -ForegroundColor Gray
            goto SkipScheduler
        }
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }

    # Create trigger (daily at 6:00 AM)
    $trigger = New-ScheduledTaskTrigger -Daily -At "06:00AM"

    # Create action
    $action = New-ScheduledTaskAction `
        -Execute "python.exe" `
        -Argument """$ScriptDir\$ScriptName"" $Schedule" `
        -WorkingDirectory $ScriptDir

    # Create settings
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable

    # Create principal (run with highest privileges)
    $principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -RunLevel Highest

    # Register task
    Register-ScheduledTask `
        -TaskName $taskName `
        -Trigger $trigger `
        -Action $action `
        -Settings $settings `
        -Principal $principal `
        -Description "Automated research feed for AI/ML/legal tech/privacy topics" | Out-Null

    Write-Host "✓ Created scheduled task: $taskName" -ForegroundColor Green
    Write-Host "  Runs daily at 6:00 AM" -ForegroundColor Gray
    Write-Host "  Reports: $LogDir\research-feed-[date].json" -ForegroundColor Gray
    Write-Host "  Digest:  $LogDir\research-digest-[date].md" -ForegroundColor Gray

    # Optional: Additional run times
    Write-Host ""
    Write-Host "Would you like to add additional run times? (e.g., lunch, evening)" -ForegroundColor Cyan
    $addMore = Read-Host "Add 12:00 PM and 6:00 PM runs? (y/N)"
    if ($addMore -eq "y") {
        $times = @("12:00PM", "6:00PM")
        foreach ($time in $times) {
            $trigger2 = New-ScheduledTaskTrigger -Daily -At $time
            Set-ScheduledTask -TaskName $taskName -Trigger @($trigger, $trigger2) | Out-Null
            Write-Host "✓ Added $time run" -ForegroundColor Green
        }
    }
}

:SkipScheduler

# Test run option
Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host ""

if ($TestRun) {
    Write-Host "Running test execution now..." -ForegroundColor Cyan
    Write-Host ""
    Push-Location $ScriptDir
    python $ScriptName $Schedule
    Pop-Location
} else {
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Review: $ScriptDir\$ScriptName"
    Write-Host "  2. Test run: python $ScriptName --quick"
    Write-Host "  3. Full run: python $ScriptName"
    Write-Host "  4. Manage feeds: python workhorse-subscribe.py list"
    Write-Host ""
    Write-Host "Scheduled runs:" -ForegroundColor Cyan
    Write-Host "  Daily at 6:00 AM → $LogDir\research-feed-[date].json"
    Write-Host ""
}

Write-Host "=" * 80
