# Run this script as Administrator to schedule Lucius Fox weekly audit
# Usage: Right-click PowerShell -> Run as Administrator -> .\schedule_lucius_task.ps1
#
# Portable: resolves paths from this script's location.

$taskName = "BatFamily\LuciusFoxAudit"
$RudyRoot = if ($PSScriptRoot) { (Resolve-Path "$PSScriptRoot\..").Path } else { "$env:USERPROFILE\Desktop\rudy-workhorse" }
$scriptPath = "$RudyRoot\scripts\run_lucius_audit.py"

# Find Python dynamically
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) { $pythonPath = "C:\Python312\python.exe" }

# Remove existing if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create action
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath

# Trigger: Weekly on Sunday at 3:00 AM
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3:00AM

# Settings
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Register
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Weekly Lucius Fox code audit for the Bat Family system" -RunLevel Highest

Write-Host "Lucius Fox weekly audit scheduled successfully!" -ForegroundColor Green
Write-Host "Schedule: Every Sunday at 3:00 AM"
Write-Host "Task name: $taskName"
