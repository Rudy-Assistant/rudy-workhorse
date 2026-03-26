@echo off
:: ============================================================
:: WORKHORSE RESILIENCE SYSTEM SETUP
:: Creates layered recovery for all critical services
:: Right-click → Run as Administrator (or just double-click)
:: ============================================================

:: Self-elevate to admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo   WORKHORSE RESILIENCE SYSTEM SETUP
echo ============================================================
echo.

set DESKTOP=C:\Users\C\Desktop
set LOGDIR=%DESKTOP%\rudy-logs
set PYTHON=C:\Users\C\AppData\Local\Programs\Python\Python312\python.exe

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

:: ============================================================
:: STEP 1: Write the master health-check PowerShell script
:: ============================================================
echo [1/4] Writing health-check script...

powershell -ExecutionPolicy Bypass -Command ^
 "Set-Content '%DESKTOP%\workhorse-healthcheck.ps1' @'`n" ^
 "# Workhorse Health Check — runs every 5 minutes via Task Scheduler`n" ^
 "# Checks all critical services, restarts failures, emails on persistent issues`n" ^
 "`n" ^
 "$logFile = '%LOGDIR%\healthcheck.log'`n" ^
 "$stateFile = '%LOGDIR%\healthcheck-state.json'`n" ^
 "$python = '%PYTHON%'`n" ^
 "$desktop = '%DESKTOP%'`n" ^
 "`n" ^
 "function Log($msg) {`n" ^
 "    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'`n" ^
 "    \"$ts  $msg\" | Out-File -Append $logFile -Encoding UTF8`n" ^
 "}`n" ^
 "`n" ^
 "# Load state (tracks consecutive failures per service)`n" ^
 "$state = @{}`n" ^
 "if (Test-Path $stateFile) {`n" ^
 "    try { $state = Get-Content $stateFile -Raw | ConvertFrom-Json -AsHashtable } catch { $state = @{} }`n" ^
 "}`n" ^
 "`n" ^
 "function Check-Service($name, $startCmd, $checkCmd) {`n" ^
 "    $ok = $false`n" ^
 "    try {`n" ^
 "        $result = Invoke-Expression $checkCmd 2>&1`n" ^
 "        $ok = ($LASTEXITCODE -eq 0 -or $result -match 'RUNNING|rustdesk|python')`n" ^
 "    } catch { $ok = $false }`n" ^
 "`n" ^
 "    if (-not $state.ContainsKey($name)) { $state[$name] = 0 }`n" ^
 "`n" ^
 "    if ($ok) {`n" ^
 "        if ($state[$name] -gt 0) { Log \"[RECOVERED] $name is back up (was down $($state[$name]) checks)\" }`n" ^
 "        $state[$name] = 0`n" ^
 "        return $true`n" ^
 "    }`n" ^
 "`n" ^
 "    $state[$name]++`n" ^
 "    Log \"[DOWN] $name — failure #$($state[$name]), attempting restart...\"    `n" ^
 "    try {`n" ^
 "        Invoke-Expression $startCmd 2>&1 | Out-Null`n" ^
 "        Start-Sleep 3`n" ^
 "        $recheck = Invoke-Expression $checkCmd 2>&1`n" ^
 "        $recovered = ($LASTEXITCODE -eq 0 -or $recheck -match 'RUNNING|rustdesk|python')`n" ^
 "        if ($recovered) {`n" ^
 "            Log \"[RESTARTED] $name recovered after restart\"`n" ^
 "            $state[$name] = 0`n" ^
 "            return $true`n" ^
 "        }`n" ^
 "    } catch { Log \"[ERROR] Failed to restart $name : $_\" }`n" ^
 "`n" ^
 "    Log \"[STILL DOWN] $name — $($state[$name]) consecutive failures\"`n" ^
 "    return $false`n" ^
 "}`n" ^
 "`n" ^
 "# === CHECK ALL SERVICES ===`n" ^
 "$failures = @()`n" ^
 "`n" ^
 "# 1. RustDesk Service`n" ^
 "if (-not (Check-Service 'RustDesk' 'Start-Service RustDesk' 'sc query RustDesk')) {`n" ^
 "    $failures += 'RustDesk'`n" ^
 "}`n" ^
 "`n" ^
 "# 2. Tailscale`n" ^
 "if (-not (Check-Service 'Tailscale' 'Start-Service Tailscale' 'sc query Tailscale')) {`n" ^
 "    # Try alternate name`n" ^
 "    Check-Service 'Tailscale' 'Start-Service \"Tailscale\"' 'tailscale status' | Out-Null`n" ^
 "}`n" ^
 "`n" ^
 "# 3. Command Runner`n" ^
 "$cmdRunnerCheck = 'Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match \"rudy-command-runner\" }'`n" ^
 "$cmdRunnerStart = \"Start-Process '$python' -ArgumentList '$desktop\\rudy-command-runner.py' -WorkingDirectory '$desktop' -WindowStyle Hidden\"`n" ^
 "if (-not (Check-Service 'CommandRunner' $cmdRunnerStart $cmdRunnerCheck)) {`n" ^
 "    $failures += 'CommandRunner'`n" ^
 "}`n" ^
 "`n" ^
 "# 4. Listener`n" ^
 "$listenerCheck = 'Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match \"rudy-listener\" }'`n" ^
 "$listenerStart = \"Start-Process '$python' -ArgumentList '$desktop\\rudy-listener.py' -WorkingDirectory '$desktop' -WindowStyle Hidden\"`n" ^
 "if (-not (Check-Service 'Listener' $listenerStart $listenerCheck)) {`n" ^
 "    $failures += 'Listener'`n" ^
 "}`n" ^
 "`n" ^
 "# 5. Internet connectivity`n" ^
 "$netCheck = 'Test-Connection 8.8.8.8 -Count 1 -Quiet'`n" ^
 "$netStart = 'ipconfig /release; Start-Sleep 2; ipconfig /renew'`n" ^
 "if (-not (Check-Service 'Internet' $netStart $netCheck)) {`n" ^
 "    $failures += 'Internet'`n" ^
 "}`n" ^
 "`n" ^
 "# Save state`n" ^
 "$state | ConvertTo-Json | Set-Content $stateFile`n" ^
 "`n" ^
 "# === ALERTING ===`n" ^
 "# Email Chris if any service has 3+ consecutive failures`n" ^
 "$critical = $state.GetEnumerator() | Where-Object { $_.Value -ge 3 }`n" ^
 "if ($critical) {`n" ^
 "    $alertFile = '%LOGDIR%\last-alert.txt'`n" ^
 "    $lastAlert = if (Test-Path $alertFile) { Get-Content $alertFile } else { '' }`n" ^
 "    $now = Get-Date -Format 'yyyy-MM-dd HH'`n" ^
 "    # Only alert once per hour per issue`n" ^
 "    if ($lastAlert -ne $now) {`n" ^
 "        $body = \"Workhorse Alert: \" + ($critical | ForEach-Object { \"$($_.Key) down ($($_.Value) checks)\" }) -join ', '`n" ^
 "        Log \"[ALERT] Sending notification: $body\"`n" ^
 "        # Write alert to a file Cowork can read`n" ^
 "        $body | Set-Content '%LOGDIR%\ALERT-ACTIVE.txt'`n" ^
 "        # Try sending email via Python (uses Rudy's SMTP if available)`n" ^
 "        try {`n" ^
 "            $emailScript = @\"`n" ^
 "import smtplib`n" ^
 "from email.mime.text import MIMEText`n" ^
 "try:`n" ^
 "    msg = MIMEText('$body\n\nCheck %LOGDIR%\\healthcheck.log for details.')`n" ^
 "    msg['Subject'] = 'Workhorse Alert: Service Down'`n" ^
 "    msg['From'] = 'rudy.ciminoassist@gmail.com'`n" ^
 "    msg['To'] = 'ccimino2@gmail.com'`n" ^
 "    with smtplib.SMTP('smtp.gmail.com', 587) as s:`n" ^
 "        s.starttls()`n" ^
 "        s.login('rudy.ciminoassist@gmail.com', 'bviuyjdptufrtnys')`n" ^
 "        s.send_message(msg)`n" ^
 "    print('Email sent')`n" ^
 "except Exception as e:`n" ^
 "    print(f'Email failed: {e}')`n" ^
 "\"@`n" ^
 "            $emailScript | & '$python' - 2>&1 | ForEach-Object { Log $_ }`n" ^
 "        } catch { Log \"[WARN] Email alert failed: $_\" }`n" ^
 "        $now | Set-Content $alertFile`n" ^
 "    }`n" ^
 "} else {`n" ^
 "    # Clear alert file if everything is healthy`n" ^
 "    if (Test-Path '%LOGDIR%\ALERT-ACTIVE.txt') { Remove-Item '%LOGDIR%\ALERT-ACTIVE.txt' }`n" ^
 "}`n" ^
 "`n" ^
 "# Trim log to last 500 lines`n" ^
 "if (Test-Path $logFile) {`n" ^
 "    $lines = Get-Content $logFile -Tail 500`n" ^
 "    $lines | Set-Content $logFile`n" ^
 "}`n" ^
 "'@"

echo   Health-check script written to %DESKTOP%\workhorse-healthcheck.ps1

:: ============================================================
:: STEP 2: Create Task Scheduler tasks
:: ============================================================
echo.
echo [2/4] Creating scheduled tasks...

:: --- Health Check: every 5 minutes ---
schtasks /delete /tn "WorkhorseHealthCheck" /f >nul 2>&1
schtasks /create /tn "WorkhorseHealthCheck" ^
  /tr "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File %DESKTOP%\workhorse-healthcheck.ps1" ^
  /sc minute /mo 5 ^
  /ru SYSTEM /rl HIGHEST /f
echo   [OK] WorkhorseHealthCheck — every 5 minutes

:: --- RustDesk Config Enforce: at boot ---
schtasks /delete /tn "RustDeskConfigEnforce" /f >nul 2>&1
schtasks /create /tn "RustDeskConfigEnforce" ^
  /tr "powershell.exe -ExecutionPolicy Bypass -File %DESKTOP%\enforce-rustdesk-config.ps1" ^
  /sc onstart /delay 0000:30 ^
  /ru SYSTEM /rl HIGHEST /f
echo   [OK] RustDeskConfigEnforce — 30s after boot

:: --- Command Runner: at logon + on-demand recovery ---
schtasks /delete /tn "WorkhorseCommandRunner" /f >nul 2>&1
schtasks /create /tn "WorkhorseCommandRunner" ^
  /tr "\"%PYTHON%\" \"%DESKTOP%\rudy-command-runner.py\"" ^
  /sc onlogon /delay 0000:45 ^
  /ru C /rp CMCPassTemp7508! /rl HIGHEST /f
echo   [OK] WorkhorseCommandRunner — at logon + 45s

:: --- Listener: at logon ---
schtasks /delete /tn "WorkhorseListener" /f >nul 2>&1
schtasks /create /tn "WorkhorseListener" ^
  /tr "\"%PYTHON%\" \"%DESKTOP%\rudy-listener.py\"" ^
  /sc onlogon /delay 0001:00 ^
  /ru C /rp CMCPassTemp7508! /rl HIGHEST /f
echo   [OK] WorkhorseListener — at logon + 60s

:: --- RustDesk Service Recovery: Windows built-in ---
echo.
echo   Configuring RustDesk service failure recovery...
sc failure RustDesk reset= 86400 actions= restart/5000/restart/10000/restart/30000
sc config RustDesk start= auto
echo   [OK] RustDesk will auto-restart on crash (5s, 10s, 30s delays)

:: --- Tailscale Service Recovery ---
sc failure Tailscale reset= 86400 actions= restart/5000/restart/10000/restart/30000 >nul 2>&1
echo   [OK] Tailscale will auto-restart on crash

:: ============================================================
:: STEP 3: Set up RustDesk service recovery (belt + suspenders)
:: ============================================================
echo.
echo [3/4] Verifying RustDesk permanent password...
"C:\Program Files\RustDesk\rustdesk.exe" --password CMCPassTemp7508!

:: Copy config to service paths
for %%D in (
    "C:\Windows\System32\config\systemprofile\AppData\Roaming\RustDesk\config"
    "C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config"
) do (
    if not exist %%D mkdir %%D 2>nul
    copy /Y "C:\Users\C\AppData\Roaming\RustDesk\config\RustDesk.toml" %%D\ >nul 2>&1
    copy /Y "C:\Users\C\AppData\Roaming\RustDesk\config\RustDesk2.toml" %%D\ >nul 2>&1
)
echo   Config synced to all service paths

:: ============================================================
:: STEP 4: Verify everything
:: ============================================================
echo.
echo [4/4] Verification...
echo.

echo --- Scheduled Tasks ---
for %%T in (WorkhorseHealthCheck RustDeskConfigEnforce WorkhorseCommandRunner WorkhorseListener) do (
    schtasks /query /tn "%%T" /fo list 2>nul | findstr "Status:"
    if errorlevel 1 echo   %%T: NOT FOUND
)

echo.
echo --- Services ---
sc query RustDesk | findstr STATE
sc query Tailscale | findstr STATE 2>nul

echo.
echo --- Service Recovery Policies ---
sc qfailure RustDesk | findstr "RESTART"

echo.
echo ============================================================
echo   RESILIENCE SYSTEM ACTIVE
echo ============================================================
echo.
echo   Layer 1: Windows Services (RustDesk, Tailscale)
echo            Auto-start + auto-restart on crash (5s/10s/30s)
echo.
echo   Layer 2: Task Scheduler
echo            CommandRunner + Listener start at logon
echo            RustDesk config enforced 30s after boot
echo.
echo   Layer 3: Health Check (every 5 minutes)
echo            Monitors: RustDesk, Tailscale, CommandRunner,
echo            Listener, Internet connectivity
echo            Auto-restarts failed services
echo            Emails ccimino2@gmail.com after 3+ failures
echo            Alert file: rudy-logs\ALERT-ACTIVE.txt
echo.
echo   Layer 4: Boot Sequence
echo            Auto-login → Services start → Logon tasks →
echo            Health check begins monitoring
echo.
echo   Logs: %LOGDIR%\healthcheck.log
echo   State: %LOGDIR%\healthcheck-state.json
echo ============================================================
echo.
echo Press any key to close...
pause >nul
