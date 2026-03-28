#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Rudy n8n Setup - Install and configure n8n as the Rudy orchestration engine.

.DESCRIPTION
    This script installs Node.js, n8n, and NSSM, then configures n8n as a
    Windows service with auto-start. It also imports seed workflow templates
    if they exist on the USB drive.

    Run this AFTER UNROLL.cmd and workhorse-bootstrap.ps1 have completed.

.NOTES
    Requires: Internet connectivity, Administrator privileges
    Time: ~5-10 minutes depending on download speeds
#>

param(
    [string]$N8nPassword = "",
    [switch]$SkipNodeInstall,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# ============================================================================
# CONFIGURATION
# ============================================================================

$Config = @{
    N8nUser         = "rudy"
    N8nPort         = 5678
    LogsDir         = "$env:USERPROFILE\Desktop\rudy-logs"
    BackupsDir      = "$env:USERPROFILE\Desktop\rudy-backups"
    NssmDir         = "C:\tools"
    NssmUrl         = "https://nssm.cc/release/nssm-2.24.zip"
    ServiceName     = "n8n"
}

$LogFile = Join-Path $Config.LogsDir "n8n-setup.log"

# ============================================================================
# HELPERS
# ============================================================================

function Write-Step {
    param([string]$Message, [string]$Status = "INFO")
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] [$Status] $Message"
    Write-Host $line -ForegroundColor $(
        switch ($Status) {
            "OK"    { "Green" }
            "WARN"  { "Yellow" }
            "ERROR" { "Red" }
            "SKIP"  { "DarkGray" }
            default { "White" }
        }
    )
    if (Test-Path (Split-Path $LogFile)) {
        $line | Out-File -Append -FilePath $LogFile -Encoding UTF8
    }
}

# ============================================================================
# STEP 0: Pre-flight
# ============================================================================

Write-Step "=========================================="
Write-Step "  Rudy n8n Setup"
Write-Step "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Step "=========================================="

# Create directories
foreach ($dir in @($Config.LogsDir, $Config.BackupsDir, "$($Config.BackupsDir)\workflows", "$($Config.BackupsDir)\database", $Config.NssmDir)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Write-Step "Created: $dir" "OK"
    }
}

# ============================================================================
# STEP 1: Install Node.js
# ============================================================================

Write-Step "--- STEP 1: Node.js ---"

if ($SkipNodeInstall) {
    Write-Step "Skipping Node.js install (flag set)" "SKIP"
} else {
    $nodeVer = & node --version 2>&1
    if ($LASTEXITCODE -eq 0 -and $nodeVer -match "^v(1[89]|2[0-9])") {
        Write-Step "Node.js already installed: $nodeVer" "SKIP"
    } else {
        Write-Step "Installing Node.js 20 LTS via winget..."
        if ($DryRun) {
            Write-Step "[DRY RUN] Would run: winget install OpenJS.NodeJS.LTS" "SKIP"
        } else {
            $wingetResult = & winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements 2>&1 | Out-String
            if ($LASTEXITCODE -eq 0) {
                Write-Step "Node.js installed" "OK"
                # Refresh PATH
                $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
            } else {
                Write-Step "winget install failed. Trying npm from existing Node..." "WARN"
                Write-Step "Output: $wingetResult" "WARN"
            }
        }
    }
}

# Verify Node.js
$nodeVer = & node --version 2>&1
$npmVer = & npm --version 2>&1
Write-Step "Node: $nodeVer | npm: $npmVer"

# ============================================================================
# STEP 2: Install n8n
# ============================================================================

Write-Step "--- STEP 2: n8n ---"

$n8nVer = & n8n --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Step "n8n already installed: $n8nVer" "SKIP"
} else {
    Write-Step "Installing n8n globally via npm..."
    if ($DryRun) {
        Write-Step "[DRY RUN] Would run: npm install -g n8n" "SKIP"
    } else {
        & npm install -g n8n 2>&1 | Out-Null
        $n8nVer = & n8n --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Step "n8n installed: $n8nVer" "OK"
        } else {
            Write-Step "n8n installation FAILED" "ERROR"
            exit 1
        }
    }
}

# ============================================================================
# STEP 3: Set environment variables
# ============================================================================

Write-Step "--- STEP 3: Environment Variables ---"

# Generate encryption key if not already set
$existingKey = [Environment]::GetEnvironmentVariable("N8N_ENCRYPTION_KEY", "Machine")
if ($existingKey) {
    Write-Step "N8N_ENCRYPTION_KEY already set" "SKIP"
} else {
    $chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    $key = -join (1..32 | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })
    [Environment]::SetEnvironmentVariable("N8N_ENCRYPTION_KEY", $key, "Machine")
    Write-Step "Generated and set N8N_ENCRYPTION_KEY" "OK"
    # Save key to a secure location for backup
    $key | Out-File -FilePath "$($Config.BackupsDir)\n8n-encryption-key.txt" -Encoding UTF8
    Write-Step "Key backed up to rudy-backups\n8n-encryption-key.txt" "WARN"
}

# Set basic auth
if (-not $N8nPassword) {
    $N8nPassword = -join (1..16 | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })
    Write-Step "Generated random n8n password (saved to log)" "WARN"
}

$envVars = @{
    "N8N_BASIC_AUTH_ACTIVE"  = "true"
    "N8N_BASIC_AUTH_USER"    = $Config.N8nUser
    "N8N_BASIC_AUTH_PASSWORD" = $N8nPassword
    "N8N_DEFAULT_BINARY_DATA_MODE" = "filesystem"
    "N8N_LISTEN_ADDRESS"    = "0.0.0.0"
    "N8N_PORT"              = $Config.N8nPort.ToString()
    "N8N_LOG_LEVEL"         = "info"
    "N8N_LOG_OUTPUT"        = "console,file"
    "N8N_LOG_FILE_LOCATION" = "$($Config.LogsDir)\n8n.log"
}

foreach ($kv in $envVars.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($kv.Key, $kv.Value, "Machine")
    $env:($kv.Key) = $kv.Value
}
Write-Step "Environment variables set" "OK"
Write-Step "n8n UI: http://localhost:$($Config.N8nPort)" "OK"
Write-Step "n8n User: $($Config.N8nUser)" "OK"
Write-Step "n8n Password: $N8nPassword" "OK"

# ============================================================================
# STEP 4: Install NSSM and create service
# ============================================================================

Write-Step "--- STEP 4: NSSM Service ---"

$nssmExe = Join-Path $Config.NssmDir "nssm.exe"

# Check if NSSM exists
if (-not (Test-Path $nssmExe)) {
    $nssmInPath = Get-Command nssm -ErrorAction SilentlyContinue
    if ($nssmInPath) {
        $nssmExe = $nssmInPath.Source
        Write-Step "NSSM found in PATH: $nssmExe" "OK"
    } else {
        Write-Step "Downloading NSSM..."
        if ($DryRun) {
            Write-Step "[DRY RUN] Would download NSSM" "SKIP"
        } else {
            try {
                $nssmZip = "$env:TEMP\nssm.zip"
                Invoke-WebRequest -Uri $Config.NssmUrl -OutFile $nssmZip -UseBasicParsing
                Expand-Archive -Path $nssmZip -DestinationPath "$env:TEMP\nssm" -Force
                # Find the 64-bit exe
                $nssmSrc = Get-ChildItem -Path "$env:TEMP\nssm" -Filter "nssm.exe" -Recurse |
                    Where-Object { $_.DirectoryName -match "win64" } | Select-Object -First 1
                if ($nssmSrc) {
                    if (-not (Test-Path $Config.NssmDir)) { New-Item -ItemType Directory -Force -Path $Config.NssmDir | Out-Null }
                    Copy-Item $nssmSrc.FullName $nssmExe -Force
                    Write-Step "NSSM installed to $nssmExe" "OK"
                } else {
                    Write-Step "Could not find nssm.exe in download" "ERROR"
                }
            } catch {
                Write-Step "NSSM download failed: $_" "ERROR"
                Write-Step "Please download NSSM manually from nssm.cc" "WARN"
            }
        }
    }
}

# Get n8n executable path
$n8nExe = (Get-Command n8n -ErrorAction SilentlyContinue).Source
if (-not $n8nExe) {
    # Try common npm global paths
    $n8nExe = "$env:APPDATA\npm\n8n.cmd"
    if (-not (Test-Path $n8nExe)) {
        Write-Step "Cannot find n8n executable" "ERROR"
        exit 1
    }
}
Write-Step "n8n executable: $n8nExe"

# Create Windows service
if (Test-Path $nssmExe) {
    $existingService = Get-Service -Name $Config.ServiceName -ErrorAction SilentlyContinue
    if ($existingService) {
        Write-Step "n8n service already exists (status: $($existingService.Status))" "SKIP"
    } else {
        Write-Step "Creating n8n Windows service..."
        if ($DryRun) {
            Write-Step "[DRY RUN] Would create service" "SKIP"
        } else {
            & $nssmExe install $Config.ServiceName $n8nExe
            & $nssmExe set $Config.ServiceName AppParameters "start"
            & $nssmExe set $Config.ServiceName AppDirectory $env:USERPROFILE
            & $nssmExe set $Config.ServiceName Start SERVICE_AUTO_START
            & $nssmExe set $Config.ServiceName AppStdout "$($Config.LogsDir)\n8n-stdout.log"
            & $nssmExe set $Config.ServiceName AppStderr "$($Config.LogsDir)\n8n-stderr.log"
            & $nssmExe set $Config.ServiceName AppRotateFiles 1
            & $nssmExe set $Config.ServiceName AppRotateBytes 10485760
            & $nssmExe set $Config.ServiceName AppEnvironmentExtra "+N8N_ENCRYPTION_KEY=$existingKey"
            Write-Step "n8n service created" "OK"
        }
    }

    # Start the service
    Write-Step "Starting n8n service..."
    & $nssmExe start $Config.ServiceName 2>&1 | Out-Null
    Start-Sleep -Seconds 5

    # Verify
    $svc = Get-Service -Name $Config.ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq "Running") {
        Write-Step "n8n service is RUNNING" "OK"
    } else {
        Write-Step "n8n service failed to start. Check logs." "ERROR"
    }
} else {
    Write-Step "NSSM not available - n8n will need manual service setup" "WARN"
}

# ============================================================================
# STEP 5: Firewall rule
# ============================================================================

Write-Step "--- STEP 5: Firewall ---"

$fwRule = Get-NetFirewallRule -DisplayName "n8n Web UI" -ErrorAction SilentlyContinue
if ($fwRule) {
    Write-Step "Firewall rule already exists" "SKIP"
} else {
    New-NetFirewallRule -DisplayName "n8n Web UI" -Direction Inbound -LocalPort $Config.N8nPort -Protocol TCP -Action Allow -Profile Domain,Private | Out-Null
    Write-Step "Firewall rule added (port $($Config.N8nPort), private/domain only)" "OK"
}

# ============================================================================
# STEP 6: Import seed workflows (if available)
# ============================================================================

Write-Step "--- STEP 6: Seed Workflows ---"

$usbRoot = Split-Path $PSScriptRoot -Parent
$seedDir = Join-Path $usbRoot "n8n-workflows"

if (Test-Path $seedDir) {
    Write-Step "Found seed workflows directory: $seedDir"
    $workflows = Get-ChildItem -Path $seedDir -Filter "*.json" -ErrorAction SilentlyContinue
    foreach ($wf in $workflows) {
        Write-Step "Importing: $($wf.Name)..."
        & n8n import:workflow --input=$($wf.FullName) 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Step "  Imported: $($wf.Name)" "OK"
        } else {
            Write-Step "  Failed to import: $($wf.Name)" "WARN"
        }
    }
} else {
    Write-Step "No seed workflows directory found on USB" "SKIP"
    Write-Step "Workflows will need to be created manually in the n8n UI" "WARN"
}

# ============================================================================
# SUMMARY
# ============================================================================

Write-Step ""
Write-Step "=========================================="
Write-Step "  n8n SETUP COMPLETE"
Write-Step "=========================================="
Write-Step ""
Write-Step "n8n Web UI: http://localhost:$($Config.N8nPort)"
Write-Step "Username:   $($Config.N8nUser)"
Write-Step "Password:   $N8nPassword"
Write-Step ""
Write-Step "NEXT STEPS:"
Write-Step "  1. Open http://localhost:$($Config.N8nPort) in Chrome"
Write-Step "  2. Complete n8n owner account setup"
Write-Step "  3. Add credentials: Gmail OAuth2, Claude API key"
Write-Step "  4. Create or import seed workflows"
Write-Step "  5. Activate workflows"
Write-Step ""
Write-Step "Access via Tailscale: http://rudy:$($Config.N8nPort)"
Write-Step ""
Write-Step "Log: $LogFile"

# Open browser to n8n UI
Start-Process "http://localhost:$($Config.N8nPort)"
