# ============================================================
# BATCAVE STARTUP SCRIPT
# Oracle Boot Sequence - Ensures all Bat Family systems online
# Location: shell:startup\batcave-startup.ps1
# ============================================================

$logPath = "C:\Users\ccimi\Desktop\rudy-logs\batcave-startup.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] === BATCAVE BOOT SEQUENCE INITIATED ===" | Out-File $logPath -Append

# 1. NordVPN (verify - should auto-start from HKCU\Run)
$nord = Get-Process -Name "NordVPN" -ErrorAction SilentlyContinue
if (-not $nord) {
    Start-Process "C:\Program Files\NordVPN\NordVPN.exe" -ArgumentList "--auto-start"
    "[$timestamp] NordVPN: STARTED" | Out-File $logPath -Append
} else {
    "[$timestamp] NordVPN: ALREADY RUNNING (PID $($nord[0].Id))" | Out-File $logPath -Append
}

# 2. Claude Desktop (MSIX app)
$claude = Get-Process -Name "claude" -ErrorAction SilentlyContinue
if (-not $claude) {
    Start-Process "shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"
    "[$timestamp] Claude Desktop: STARTED" | Out-File $logPath -Append
} else {
    "[$timestamp] Claude Desktop: ALREADY RUNNING" | Out-File $logPath -Append
}

# 3. Zoho Mail Desktop
$zoho = Get-Process -Name "Zoho Mail*" -ErrorAction SilentlyContinue
if (-not $zoho) {
    Start-Process "C:\Program Files\Zoho Mail - Desktop\Zoho Mail - Desktop.exe"
    "[$timestamp] Zoho Mail: STARTED" | Out-File $logPath -Append
} else {
    "[$timestamp] Zoho Mail: ALREADY RUNNING" | Out-File $logPath -Append
}

# 4. Wait for network then open Gmail in Chrome
Start-Sleep -Seconds 10
$chrome = "C:\Users\ccimi\AppData\Local\Google\Chrome SxS\Application\chrome.exe"
Start-Process $chrome -ArgumentList "https://mail.google.com"
"[$timestamp] Chrome: Opened Gmail tab" | Out-File $logPath -Append

# 5. Robin Nightwatch (THE CRITICAL ONE)
$robin = Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
    (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine -match "nightwatch"
}
if (-not $robin) {
    $env:PYTHONPATH = "C:\Users\ccimi\Desktop\rudy-workhorse"
    Start-Process "C:\Python312\python.exe" -ArgumentList "-m rudy.robin_main --nightwatch" -WorkingDirectory "C:\Users\ccimi\Desktop\rudy-workhorse" -WindowStyle Hidden -RedirectStandardOutput "C:\Users\ccimi\Desktop\rudy-logs\robin-nightwatch.log" -RedirectStandardError "C:\Users\ccimi\Desktop\rudy-logs\robin-nightwatch-err.log"
    "[$timestamp] Robin Nightwatch: STARTED" | Out-File $logPath -Append
} else {
    "[$timestamp] Robin Nightwatch: ALREADY RUNNING (PID $($robin[0].Id))" | Out-File $logPath -Append
}

# 6. Verify Ollama (should auto-start from Startup folder)
$ollama = Get-Process -Name "ollama*" -ErrorAction SilentlyContinue
if ($ollama) {
    "[$timestamp] Ollama: RUNNING" | Out-File $logPath -Append
} else {
    Start-Process "C:\Users\ccimi\AppData\Local\Programs\Ollama\ollama app.exe"
    "[$timestamp] Ollama: STARTED (was not running)" | Out-File $logPath -Append
}

$timestamp2 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp2] === BATCAVE BOOT SEQUENCE COMPLETE ===" | Out-File $logPath -Append
"[$timestamp2] Systems: NordVPN, Claude, Zoho Mail, Gmail, Robin, Ollama" | Out-File $logPath -Append
