<#
    Robin Go -- One-command bootstrap for Oracle.

    Run this ONCE on Oracle to pull code, set up secrets, and start Robin.

    Usage:
        irm https://raw.githubusercontent.com/Rudy-Assistant/rudy-workhorse/main/scripts/robin-go.ps1 | iex
    Or locally:
        .\scripts\robin-go.ps1
#>

$ErrorActionPreference = "Stop"

# Dynamic path resolution: repo root is parent of scripts/ directory
$RudyRoot = if ($PSScriptRoot) { (Resolve-Path "$PSScriptRoot\..").Path } else { "$env:USERPROFILE\Desktop\rudy-workhorse" }
$RudyData = (Split-Path $RudyRoot -Parent) + "\rudy-data"
$RudyLogs = (Split-Path $RudyRoot -Parent) + "\rudy-logs"
$SecretsFile = "$RudyData\robin-secrets.json"

Write-Host "`n=== ROBIN GO ===" -ForegroundColor Cyan
Write-Host "Oracle: $env:COMPUTERNAME | $(Get-Date -Format 'yyyy-MM-dd HH:mm')" -ForegroundColor Gray

# --- Step 1: Ensure directories ---
$RudyCommands = (Split-Path $RudyRoot -Parent) + "\rudy-commands"
foreach ($dir in @($RudyData, $RudyLogs, $RudyCommands)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}

# --- Step 2: Pull latest code ---
Write-Host "`n[1] Pulling latest code..." -ForegroundColor Yellow
if (Test-Path $RudyRoot) {
    Push-Location $RudyRoot
    git checkout main 2>&1 | Out-Null
    git pull origin main 2>&1
    Pop-Location
    Write-Host "  OK" -ForegroundColor Green
} else {
    Write-Host "  Cloning rudy-workhorse..." -ForegroundColor Yellow
    $cloneParent = Split-Path $RudyRoot -Parent
    Push-Location $cloneParent
    git clone https://github.com/Rudy-Assistant/rudy-workhorse.git 2>&1
    Pop-Location
    Write-Host "  OK" -ForegroundColor Green
}

# --- Step 3: Secrets setup ---
Write-Host "`n[2] Checking secrets..." -ForegroundColor Yellow
if (-not (Test-Path $SecretsFile)) {
    Write-Host "  Creating secrets template..." -ForegroundColor Yellow
    $template = @{
        github_pat = "PASTE_YOUR_GITHUB_PAT_HERE"
        notion_token = "PASTE_YOUR_NOTION_TOKEN_HERE"
        ollama_host = "http://localhost:11434"
        zoho_imap_password = ""
        _instructions = "Fill in the values. This file stays on Oracle. Never push to git."
    } | ConvertTo-Json -Depth 5
    $template | Set-Content $SecretsFile
    Write-Host "  CREATED: $SecretsFile" -ForegroundColor Red
    Write-Host "  >>> EDIT THIS FILE and paste your GitHub PAT before continuing <<<" -ForegroundColor Red
    Write-Host "  Opening in notepad..." -ForegroundColor Yellow
    notepad $SecretsFile
    Read-Host "  Press Enter after saving secrets"
} else {
    $secrets = Get-Content $SecretsFile | ConvertFrom-Json
    if ($secrets.github_pat -eq "PASTE_YOUR_GITHUB_PAT_HERE") {
        Write-Host "  Secrets file exists but PAT not configured!" -ForegroundColor Red
        notepad $SecretsFile
        Read-Host "  Press Enter after saving secrets"
    } else {
        Write-Host "  OK (secrets configured)" -ForegroundColor Green
    }
}

# --- Step 4: Python check ---
Write-Host "`n[3] Checking Python..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    Write-Host "  $pyVer" -ForegroundColor Green
} catch {
    Write-Host "  Python not found!" -ForegroundColor Red
    exit 1
}

# --- Step 5: Syntax check Robin modules ---
Write-Host "`n[4] Validating Robin modules..." -ForegroundColor Yellow
$modules = @(
    "rudy/robin_main.py",
    "rudy/agents/robin_sentinel.py",
    "rudy/agents/robin_bridge.py",
    "rudy/agents/robin_presence.py",
    "rudy/tools/notion_client.py"
)
$allOk = $true
foreach ($mod in $modules) {
    $path = "$RudyRoot/$mod".Replace('\','/')
    if (Test-Path $path) {
        try {
            python -c "import py_compile; py_compile.compile('$path', doraise=True)" 2>&1 | Out-Null
            Write-Host "  OK: $(Split-Path $mod -Leaf)" -ForegroundColor Green
        } catch {
            Write-Host "  SYNTAX ERROR: $mod" -ForegroundColor Red
            $allOk = $false
        }
    } else {
        Write-Host "  MISSING: $mod" -ForegroundColor Red
        $allOk = $false
    }
}
if (-not $allOk) {
    Write-Host "`nFix errors above before continuing." -ForegroundColor Red
    exit 1
}

# --- Step 6: Register scheduled task ---
Write-Host "`n[5] Registering Robin as scheduled task..." -ForegroundColor Yellow
try {
    Unregister-ScheduledTask -TaskName "RobinMain" -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction `
        -Execute "python" `
        -Argument "-m rudy.robin_main" `
        -WorkingDirectory $RudyRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 5) `
        -ExecutionTimeLimit (New-TimeSpan -Days 365)
    Register-ScheduledTask `
        -TaskName "RobinMain" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Robin -- Batcave autonomous agent" `
        -RunLevel Highest | Out-Null
    Write-Host "  Registered: RobinMain (at startup)" -ForegroundColor Green
} catch {
    Write-Host "  Task registration failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  You can start Robin manually: python -m rudy.robin_main" -ForegroundColor Gray
}

# --- Step 7: Start Robin NOW ---
Write-Host "`n[6] Starting Robin..." -ForegroundColor Yellow
Push-Location $RudyRoot
Start-Process python -ArgumentList "-m rudy.robin_main" -WorkingDirectory $RudyRoot -WindowStyle Minimized
Pop-Location

Write-Host "`n=== ROBIN IS LIVE ===" -ForegroundColor Green
Write-Host "  Status:     python -m rudy.robin_main --status" -ForegroundColor Gray
Write-Host "  Chat:       python -m rudy.robin_main --chat `"hello`"" -ForegroundColor Gray
Write-Host "  Night shift: python -m rudy.robin_main --night-shift" -ForegroundColor Gray
Write-Host "  Handoff:    python -m rudy.agents.robin_presence --handoff 3" -ForegroundColor Gray
Write-Host ""
