# Rudy Phase 1 Quick Deploy
# Run this from an admin PowerShell on the host to:
# 1. Kill any hung bridge processes
# 2. Update bridge to v2
# 3. Clone rudy-workhorse repo
# 4. Stage files to USB (if connected)
# 5. Create rudy-data directory

$ErrorActionPreference = "Continue"

Write-Host "=== RUDY PHASE 1 QUICK DEPLOY ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Clean up hung bridge processes
Write-Host "[1/6] Cleaning up hung processes..." -ForegroundColor Yellow
$staleFiles = Get-ChildItem -Path (Join-Path $env:USERPROFILE "claude-commands") -Filter "_running_*" -ErrorAction SilentlyContinue
foreach ($stale in $staleFiles) {
    Remove-Item $stale.FullName -Force -ErrorAction SilentlyContinue
    Write-Host "  Removed stale: $($stale.Name)" -ForegroundColor DarkGray
}

# Step 2: Update bridge runner to v2
Write-Host "[2/6] Updating bridge runner to v2..." -ForegroundColor Yellow
$v2Source = Join-Path $env:USERPROFILE "Downloads\Claude Stuff\claude-command-runner-v2.ps1"
$v2Dest = Join-Path $env:USERPROFILE "claude-command-runner.ps1"
if (Test-Path $v2Source) {
    Copy-Item $v2Source $v2Dest -Force
    Write-Host "  Bridge v2 deployed to $v2Dest" -ForegroundColor Green

    # Update scheduled task
    $taskExists = Get-ScheduledTask -TaskName "ClaudeCommandBridge" -ErrorAction SilentlyContinue
    if ($taskExists) {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$v2Dest`""
        Set-ScheduledTask -TaskName "ClaudeCommandBridge" -Action $action | Out-Null
        Write-Host "  Scheduled task updated to v2" -ForegroundColor Green
    } else {
        Write-Host "  No ClaudeCommandBridge task found - will need manual setup" -ForegroundColor Yellow
    }
} else {
    Write-Host "  v2 source not found at $v2Source" -ForegroundColor Red
}

# Step 3: Create rudy-data directory
Write-Host "[3/6] Creating rudy-data directory..." -ForegroundColor Yellow
$rudyData = Join-Path $env:USERPROFILE "Desktop\rudy-data"
if (-not (Test-Path $rudyData)) {
    New-Item -ItemType Directory -Force -Path $rudyData | Out-Null
    Write-Host "  Created $rudyData" -ForegroundColor Green
} else {
    Write-Host "  Already exists" -ForegroundColor DarkGray
}

# Step 4: Clone rudy-workhorse repo
Write-Host "[4/6] Cloning rudy-workhorse repo..." -ForegroundColor Yellow
$repoDir = Join-Path $env:USERPROFILE "Desktop\rudy-workhorse"
if (Test-Path $repoDir) {
    Write-Host "  Repo already exists, pulling latest..." -ForegroundColor DarkGray
    Push-Location $repoDir
    git pull 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Pop-Location
} else {
    git clone "https://github.com/Rudy-Assistant/rudy-workhorse.git" $repoDir 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    if (Test-Path $repoDir) {
        Write-Host "  Clone successful" -ForegroundColor Green
    } else {
        Write-Host "  Clone failed - check git credentials" -ForegroundColor Red
    }
}

# Step 5: Stage to USB
Write-Host "[5/6] Staging files to USB..." -ForegroundColor Yellow
$usbAvailable = Test-Path "D:\"
if ($usbAvailable) {
    $claudeStuff = Join-Path $env:USERPROFILE "Downloads\Claude Stuff"

    # Stage n8n setup script
    $src = Join-Path $claudeStuff "rudy-n8n-setup.ps1"
    if (Test-Path $src) {
        Copy-Item $src "D:\rudy-n8n-setup.ps1" -Force
        Write-Host "  Staged: rudy-n8n-setup.ps1" -ForegroundColor Green
    }

    # Stage bridge v2
    $src2 = Join-Path $claudeStuff "claude-command-runner-v2.ps1"
    if (Test-Path $src2) {
        Copy-Item $src2 "D:\claude-command-runner-v2.ps1" -Force
        Write-Host "  Staged: claude-command-runner-v2.ps1" -ForegroundColor Green
    }

    # Stage n8n workflows
    $wfSrc = Join-Path $claudeStuff "n8n-workflows"
    $wfDst = "D:\n8n-workflows"
    if (Test-Path $wfSrc) {
        if (-not (Test-Path $wfDst)) { New-Item -ItemType Directory -Force -Path $wfDst | Out-Null }
        Get-ChildItem -Path $wfSrc -Filter "*.json" | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $wfDst $_.Name) -Force
            Write-Host "  Staged: n8n-workflows\$($_.Name)" -ForegroundColor Green
        }
    }
} else {
    Write-Host "  USB (D:\) not connected - skipping" -ForegroundColor Yellow
}

# Step 6: Summary
Write-Host ""
Write-Host "[6/6] Summary" -ForegroundColor Yellow
Write-Host "  Bridge v2: $(if (Test-Path $v2Dest) { 'DEPLOYED' } else { 'MISSING' })" -ForegroundColor $(if (Test-Path $v2Dest) { 'Green' } else { 'Red' })
Write-Host "  rudy-data: $(if (Test-Path $rudyData) { 'READY' } else { 'MISSING' })" -ForegroundColor $(if (Test-Path $rudyData) { 'Green' } else { 'Red' })
Write-Host "  Repo: $(if (Test-Path $repoDir) { 'CLONED' } else { 'MISSING' })" -ForegroundColor $(if (Test-Path $repoDir) { 'Green' } else { 'Red' })
Write-Host "  USB: $(if ($usbAvailable) { 'STAGED' } else { 'NOT CONNECTED' })" -ForegroundColor $(if ($usbAvailable) { 'Green' } else { 'Yellow' })
Write-Host ""
Write-Host "NEXT: Run rudy-n8n-setup.ps1 as admin to install n8n" -ForegroundColor Cyan
Write-Host ""
