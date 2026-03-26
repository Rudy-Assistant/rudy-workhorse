# RustDesk Config Enforcement — runs at boot as SYSTEM
# Ensures RustDesk always starts in password-only unattended mode

$logFile = "C:\Users\C\Desktop\rudy-logs\rustdesk-enforce.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"$ts  Enforcement running" | Out-File -Append $logFile

# Wait for system to settle
Start-Sleep -Seconds 10

# Ensure password is set
& "C:\Program Files\RustDesk\rustdesk.exe" --password WorkhorseRD2026! 2>&1 | Out-Null

# Sync configs to all service profile locations
$userConfig = "C:\Users\C\AppData\Roaming\RustDesk\config"
$systemPaths = @(
    "C:\Windows\System32\config\systemprofile\AppData\Roaming\RustDesk\config",
    "C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config"
)

foreach ($sp in $systemPaths) {
    try {
        New-Item -ItemType Directory -Path $sp -Force -ErrorAction SilentlyContinue | Out-Null
        Copy-Item "$userConfig\RustDesk.toml" "$sp\RustDesk.toml" -Force -ErrorAction SilentlyContinue
        Copy-Item "$userConfig\RustDesk2.toml" "$sp\RustDesk2.toml" -Force -ErrorAction SilentlyContinue
    } catch { }
}

# Ensure service is running
$svc = Get-Service RustDesk -ErrorAction SilentlyContinue
if ($svc.Status -ne 'Running') {
    Start-Service RustDesk -ErrorAction SilentlyContinue
    "$ts  Service was stopped — restarted" | Out-File -Append $logFile
}

"$ts  Enforcement complete" | Out-File -Append $logFile
