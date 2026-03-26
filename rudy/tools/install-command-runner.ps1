# Register Rudy Command Runner as a Windows Scheduled Task
# Runs at login, auto-restarts on failure
# This gives Cowork the ability to execute commands on the Windows host

$TaskName = "Rudy-CommandRunner"
$Desktop = "$env:USERPROFILE\Desktop"
$Python = (Get-Command python).Source
$Script = "$Desktop\rudy-command-runner.py"

# Remove old task if exists
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $Script `
    -WorkingDirectory $Desktop

$Trigger = New-ScheduledTaskTrigger -AtLogon

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Rudy Command Runner — Cowork-to-Windows execution bridge" `
    -RunLevel Highest

# Start it immediately
Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "[OK] Rudy Command Runner registered and started" -ForegroundColor Green
Write-Host "     Task: $TaskName" -ForegroundColor White
Write-Host "     Watching: $Desktop\rudy-commands\" -ForegroundColor White
Write-Host ""
