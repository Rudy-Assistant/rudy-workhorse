# Workhorse Health Check — runs every 5 minutes via Task Scheduler (SYSTEM)
# Monitors all critical services, auto-restarts failures, emails on persistent issues

$ErrorActionPreference = "Continue"
$logFile = "C:\Users\C\Desktop\rudy-logs\healthcheck.log"
$stateFile = "C:\Users\C\Desktop\rudy-logs\healthcheck-state.json"
$alertFile = "C:\Users\C\Desktop\rudy-logs\ALERT-ACTIVE.txt"
$python = "C:\Users\C\AppData\Local\Programs\Python\Python312\python.exe"
$desktop = "C:\Users\C\Desktop"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Out-File -Append $logFile -Encoding UTF8
}

# Load state (tracks consecutive failures per service)
$state = @{}
if (Test-Path $stateFile) {
    try {
        $raw = Get-Content $stateFile -Raw
        $parsed = $raw | ConvertFrom-Json
        $parsed.PSObject.Properties | ForEach-Object { $state[$_.Name] = [int]$_.Value }
    } catch {
        $state = @{}
    }
}

function Check-And-Restart($name, $checkScript, $restartScript) {
    $ok = $false
    try {
        $result = & ([scriptblock]::Create($checkScript))
        $ok = [bool]$result
    } catch {
        $ok = $false
    }

    if (-not $state.ContainsKey($name)) { $state[$name] = 0 }

    if ($ok) {
        if ($state[$name] -gt 0) {
            Log "[RECOVERED] $name is back up (was down $($state[$name]) checks)"
        }
        $state[$name] = 0
        return $true
    }

    $state[$name]++
    Log "[DOWN] $name - failure #$($state[$name]), attempting restart..."

    try {
        & ([scriptblock]::Create($restartScript))
        Start-Sleep 5

        $recheck = & ([scriptblock]::Create($checkScript))
        if ([bool]$recheck) {
            Log "[RESTARTED] $name recovered"
            $state[$name] = 0
            return $true
        }
    } catch {
        Log "[ERROR] Failed to restart ${name}: $_"
    }

    Log "[STILL DOWN] $name - $($state[$name]) consecutive failures"
    return $false
}

Log "--- Health check started ---"

$failures = @()

# 1. RustDesk Service
$rdCheck = '(Get-Service RustDesk -EA SilentlyContinue).Status -eq "Running"'
$rdRestart = 'Start-Service RustDesk -EA SilentlyContinue'
if (-not (Check-And-Restart "RustDesk" $rdCheck $rdRestart)) {
    $failures += "RustDesk"
}

# 2. Tailscale
$tsCheck = '(Get-Service Tailscale -EA SilentlyContinue).Status -eq "Running"'
$tsRestart = 'Start-Service Tailscale -EA SilentlyContinue'
if (-not (Check-And-Restart "Tailscale" $tsCheck $tsRestart)) {
    # Try alternate service name
    $tsCheck2 = '(tailscale status 2>&1) -notmatch "failed|stopped"'
    Check-And-Restart "Tailscale" $tsCheck2 $tsRestart | Out-Null
}

# 3. Command Runner
$crCheck = @"
    `$procs = Get-CimInstance Win32_Process -Filter "name='python.exe'" -EA SilentlyContinue |
        Where-Object { `$_.CommandLine -match 'rudy-command-runner' }
    `$procs.Count -gt 0
"@
$crRestart = @"
    # Kill any existing instances first
    Get-CimInstance Win32_Process -Filter "name='python.exe'" -EA SilentlyContinue |
        Where-Object { `$_.CommandLine -match 'rudy-command-runner' } |
        ForEach-Object { Stop-Process -Id `$_.ProcessId -Force -EA SilentlyContinue }
    Start-Sleep 2
    # Remove stale lock file
    Remove-Item '$desktop\rudy-commands\_runner.lock' -Force -EA SilentlyContinue
    # Start fresh
    Start-Process '$python' -ArgumentList '$desktop\rudy-command-runner.py' -WorkingDirectory '$desktop' -WindowStyle Hidden
"@
if (-not (Check-And-Restart "CommandRunner" $crCheck $crRestart)) {
    $failures += "CommandRunner"
}

# 4. Listener
$lsCheck = @"
    `$procs = Get-CimInstance Win32_Process -Filter "name='python.exe'" -EA SilentlyContinue |
        Where-Object { `$_.CommandLine -match 'rudy-listener' }
    `$procs.Count -gt 0
"@
$lsRestart = @"
    Get-CimInstance Win32_Process -Filter "name='python.exe'" -EA SilentlyContinue |
        Where-Object { `$_.CommandLine -match 'rudy-listener' } |
        ForEach-Object { Stop-Process -Id `$_.ProcessId -Force -EA SilentlyContinue }
    Start-Sleep 2
    Start-Process '$python' -ArgumentList '$desktop\rudy-listener.py' -WorkingDirectory '$desktop' -WindowStyle Hidden
"@
if (-not (Check-And-Restart "Listener" $lsCheck $lsRestart)) {
    $failures += "Listener"
}

# 5. Internet
$netCheck = 'Test-Connection 8.8.8.8 -Count 1 -Quiet'
$netRestart = 'ipconfig /release | Out-Null; Start-Sleep 3; ipconfig /renew | Out-Null'
if (-not (Check-And-Restart "Internet" $netCheck $netRestart)) {
    $failures += "Internet"
}

# === ONE-TIME RUNNER UPGRADE ===
# If a flag file exists, force-restart the command runner to pick up new code
$upgradeFlag = "$desktop\rudy-commands\_upgrade_runner.flag"
if (Test-Path $upgradeFlag) {
    Log "[UPGRADE] Force-restarting command runner for code update..."
    Get-CimInstance Win32_Process -Filter "name='python.exe'" -EA SilentlyContinue |
        Where-Object { $_.CommandLine -match 'rudy-command-runner' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
    Start-Sleep 3
    Remove-Item "$desktop\rudy-commands\_runner.lock" -Force -EA SilentlyContinue
    Start-Process $python -ArgumentList "$desktop\rudy-command-runner.py" -WorkingDirectory $desktop -WindowStyle Hidden
    Remove-Item $upgradeFlag -Force
    Log "[UPGRADE] Runner restarted with new code"
}

# Save state
$state | ConvertTo-Json | Set-Content $stateFile

# === ALERTING ===
$critical = $state.GetEnumerator() | Where-Object { $_.Value -ge 3 }
if ($critical) {
    $lastAlertFile = "$desktop\rudy-logs\last-alert.txt"
    $lastAlert = if (Test-Path $lastAlertFile) { Get-Content $lastAlertFile } else { "" }
    $now = Get-Date -Format "yyyy-MM-dd HH"

    if ($lastAlert -ne $now) {
        $body = "Workhorse Alert: " + (($critical | ForEach-Object { "$($_.Key) down ($($_.Value) checks)" }) -join ", ")
        Log "[ALERT] $body"
        $body | Set-Content $alertFile

        # Try email via Rudy SMTP
        try {
            $emailPy = @"
import smtplib
from email.mime.text import MIMEText
try:
    msg = MIMEText('$body\n\nCheck rudy-logs/healthcheck.log for details.')
    msg['Subject'] = 'Workhorse Alert: Service Down'
    msg['From'] = 'rudy.ciminoassist@gmail.com'
    msg['To'] = 'ccimino2@gmail.com'
    with smtplib.SMTP('smtp.gmail.com', 587) as s:
        s.starttls()
        s.login('rudy.ciminoassist@gmail.com', os.environ.get('RUDY_GMAIL_APP_PASSWORD', ''))
        s.send_message(msg)
    print('Alert email sent')
except Exception as e:
    print(f'Email failed: {e}')
"@
            $emailPy | & $python - 2>&1 | ForEach-Object { Log "  $_" }
        } catch {
            Log "[WARN] Email alert failed: $_"
        }
        $now | Set-Content $lastAlertFile
    }
} else {
    if (Test-Path $alertFile) { Remove-Item $alertFile -Force }
}

# Trim log to last 500 lines
if (Test-Path $logFile) {
    $lines = Get-Content $logFile -Tail 500 -EA SilentlyContinue
    if ($lines) { $lines | Set-Content $logFile }
}

Log "--- Health check complete ---"
