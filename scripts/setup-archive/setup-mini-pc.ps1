#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Mini PC "Always-On Claude Workhorse" Setup Script
.DESCRIPTION
    Configures a Windows 11 mini PC for 24/7 unattended operation as a
    central Claude Code / Cowork automation hub accessed via RustDesk.

    Run as Administrator in PowerShell 5.1+:
        Set-ExecutionPolicy Bypass -Scope Process -Force
        .\setup-mini-pc.ps1
.NOTES
    Author:  Claude (generated for Chris)
    Date:    2026-03-25
    License: MIT
#>

param(
    [switch]$DryRun  # Preview changes without applying
)

$ErrorActionPreference = "Stop"
$transcript = "$env:USERPROFILE\Desktop\setup-log-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
Start-Transcript -Path $transcript

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Set-RegistryValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Type,
        $Value
    )
    if (-not (Test-Path $Path)) {
        if ($DryRun) { Write-Host "  [DRY RUN] Would create key: $Path" -ForegroundColor Yellow; return }
        New-Item -Path $Path -Force | Out-Null
    }
    if ($DryRun) {
        Write-Host "  [DRY RUN] Would set $Path\$Name = $Value ($Type)" -ForegroundColor Yellow
        return
    }
    Set-ItemProperty -Path $Path -Name $Name -Value $Value -Type $Type
    Write-Host "  Set $Name = $Value" -ForegroundColor Green
}

# ─────────────────────────────────────────────
# 1. POWER: Never sleep, never hibernate
# ─────────────────────────────────────────────
Write-Step "Configuring power plan: Always On"

if (-not $DryRun) {
    # Set active plan to High Performance
    $highPerf = powercfg -list | Select-String "High performance" | ForEach-Object { ($_ -split '\s+')[3] }
    if ($highPerf) {
        powercfg -setactive $highPerf
        Write-Host "  Activated High Performance power plan" -ForegroundColor Green
    } else {
        # Duplicate current plan and name it
        $newGuid = (powercfg -duplicatescheme SCHEME_MIN) -replace '.*:\s*',''
        powercfg -changename $newGuid "Always On" "Never sleep, never hibernate"
        powercfg -setactive $newGuid
        Write-Host "  Created and activated 'Always On' power plan" -ForegroundColor Green
    }

    # AC: display off = never, sleep = never, hibernate = never
    powercfg -change -monitor-timeout-ac 0
    powercfg -change -standby-timeout-ac 0
    powercfg -change -hibernate-timeout-ac 0
    powercfg -hibernate off
    Write-Host "  Sleep, hibernate, and display timeout all set to Never" -ForegroundColor Green
} else {
    Write-Host "  [DRY RUN] Would set High Performance plan, all timeouts to 0, hibernate off" -ForegroundColor Yellow
}

# ─────────────────────────────────────────────
# 2. LOCK SCREEN: Disable it entirely
# ─────────────────────────────────────────────
Write-Step "Disabling lock screen"

Set-RegistryValue `
    -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization" `
    -Name "NoLockScreen" -Type DWord -Value 1

# Don't require sign-in after sleep
Set-RegistryValue `
    -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "DisableLockWorkstation" -Type DWord -Value 1

# ─────────────────────────────────────────────
# 3. AUTO-LOGIN (prompts for credentials)
# ─────────────────────────────────────────────
Write-Step "Setting up auto-login"

$autoLoginPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
if (-not $DryRun) {
    $currentUser = $env:USERNAME
    Write-Host "  Current user: $currentUser"
    $confirm = Read-Host "  Enable auto-login for '$currentUser'? (y/n)"
    if ($confirm -eq 'y') {
        $secPwd = Read-Host "  Enter password for $currentUser" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPwd)
        $plainPwd = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)

        Set-ItemProperty -Path $autoLoginPath -Name "AutoAdminLogon" -Value "1"
        Set-ItemProperty -Path $autoLoginPath -Name "DefaultUserName" -Value $currentUser
        Set-ItemProperty -Path $autoLoginPath -Name "DefaultPassword" -Value $plainPwd

        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        $plainPwd = $null
        Write-Host "  Auto-login enabled for $currentUser" -ForegroundColor Green
    } else {
        Write-Host "  Skipped auto-login" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [DRY RUN] Would prompt for auto-login credentials" -ForegroundColor Yellow
}

# ─────────────────────────────────────────────
# 4. WINDOWS UPDATE: No forced restarts
# ─────────────────────────────────────────────
Write-Step "Preventing forced Windows Update restarts"

Set-RegistryValue `
    -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" `
    -Name "NoAutoRebootWithLoggedOnUsers" -Type DWord -Value 1

# Set updates to notify but don't auto-install
Set-RegistryValue `
    -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" `
    -Name "AUOptions" -Type DWord -Value 2

# ─────────────────────────────────────────────
# 5. USB SELECTIVE SUSPEND: Disable
# ─────────────────────────────────────────────
Write-Step "Disabling USB selective suspend"

Set-RegistryValue `
    -Path "HKLM:\SYSTEM\CurrentControlSet\Services\USB\DisableSelectiveSuspend" `
    -Name "DisableSelectiveSuspend" -Type DWord -Value 1

# Also via powercfg (USB setting GUID)
if (-not $DryRun) {
    powercfg -setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
    powercfg -setactive SCHEME_CURRENT
    Write-Host "  USB selective suspend disabled" -ForegroundColor Green
}

# ─────────────────────────────────────────────
# 6. DISABLE NOTIFICATIONS CLUTTER
# ─────────────────────────────────────────────
Write-Step "Reducing notification noise"

Set-RegistryValue `
    -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager" `
    -Name "SubscribedContent-338389Enabled" -Type DWord -Value 0

Set-RegistryValue `
    -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager" `
    -Name "SubscribedContent-310093Enabled" -Type DWord -Value 0

Set-RegistryValue `
    -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager" `
    -Name "SoftLandingEnabled" -Type DWord -Value 0

# ─────────────────────────────────────────────
# 7. ENABLE REMOTE DESKTOP (backup for RustDesk)
# ─────────────────────────────────────────────
Write-Step "Enabling Remote Desktop as backup"

Set-RegistryValue `
    -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" `
    -Name "fDenyTSConnections" -Type DWord -Value 0

if (-not $DryRun) {
    Enable-NetFirewallRule -DisplayGroup "Remote Desktop" -ErrorAction SilentlyContinue
    Write-Host "  RDP firewall rules enabled" -ForegroundColor Green
}

# ─────────────────────────────────────────────
# 8. RUSTDESK: Ensure startup entry
# ─────────────────────────────────────────────
Write-Step "Checking RustDesk startup registration"

$rustdeskPaths = @(
    "$env:ProgramFiles\RustDesk\rustdesk.exe",
    "${env:ProgramFiles(x86)}\RustDesk\rustdesk.exe",
    "$env:LOCALAPPDATA\RustDesk\rustdesk.exe"
)

$rustdeskExe = $rustdeskPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($rustdeskExe) {
    $startupKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $existing = Get-ItemProperty -Path $startupKey -Name "RustDesk" -ErrorAction SilentlyContinue
    if (-not $existing) {
        if (-not $DryRun) {
            Set-ItemProperty -Path $startupKey -Name "RustDesk" -Value "`"$rustdeskExe`" --tray"
            Write-Host "  Added RustDesk to startup" -ForegroundColor Green
        } else {
            Write-Host "  [DRY RUN] Would add RustDesk ($rustdeskExe) to startup" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  RustDesk already in startup" -ForegroundColor Green
    }
} else {
    Write-Host "  RustDesk not found at expected paths - verify installation" -ForegroundColor Yellow
}

# ─────────────────────────────────────────────
# 9. SCHEDULED TASK: Health-check ping
# ─────────────────────────────────────────────
Write-Step "Creating daily health-check scheduled task"

if (-not $DryRun) {
    $taskName = "ClaudeWorkhorse-HealthCheck"
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument @"
-NoProfile -WindowStyle Hidden -Command "& {
    `$log = '$env:USERPROFILE\Desktop\health-check.log'
    `$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    `$uptime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    `$disk = Get-CimInstance Win32_LogicalDisk -Filter 'DeviceID=''C:''' | Select-Object @{N='FreeGB';E={[math]::Round(`$_.FreeSpace/1GB,1)}}
    `$mem = Get-CimInstance Win32_OperatingSystem | Select-Object @{N='FreeGB';E={[math]::Round(`$_.FreePhysicalMemory/1MB,1)}}
    Add-Content `$log `"`$ts | Boot: `$uptime | Disk Free: `$(`$disk.FreeGB)GB | RAM Free: `$(`$mem.FreeGB)GB`"
}"
"@
        $trigger = New-ScheduledTaskTrigger -Daily -At "06:00AM"
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Daily health check for Claude workhorse" | Out-Null
        Write-Host "  Created health-check task (runs daily at 6 AM)" -ForegroundColor Green
    } else {
        Write-Host "  Health-check task already exists" -ForegroundColor Green
    }
}

# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────
Write-Host "`n" -NoNewline
Write-Host "============================================" -ForegroundColor Magenta
Write-Host "  SETUP COMPLETE" -ForegroundColor Magenta
Write-Host "============================================" -ForegroundColor Magenta
Write-Host @"

  Next manual steps:
  1. BIOS: Set 'AC Power Recovery' -> 'Power On'
  2. RustDesk: Set a permanent unattended password
  3. Router: Reserve a static LAN IP for this machine
  4. Consider an HDMI dummy plug if remote resolution is wrong
  5. Install recommended Claude Code toolkits (see companion guide)

  Log saved to: $transcript
"@ -ForegroundColor White

Stop-Transcript
