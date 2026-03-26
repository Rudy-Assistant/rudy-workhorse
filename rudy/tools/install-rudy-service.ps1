<#
.SYNOPSIS
    Register Rudy as a Windows scheduled task that auto-starts on login.
.DESCRIPTION
    Creates a Task Scheduler entry so the Rudy listener starts
    automatically whenever the machine boots and logs in.
    Run this once after setting up the app password.
.NOTES
    Requires the RUDY_APP_PASSWORD to be set in start-rudy.bat first.
#>

$taskName = "Rudy-FamilyAssistant"
$desktopPath = "$env:USERPROFILE\Desktop"

# Check if task already exists
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Task '$taskName' already exists. Removing old version..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Create the task
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$desktopPath\start-rudy.bat`"" `
    -WorkingDirectory $desktopPath

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Rudy - Cimino Family AI Assistant (email listener)" `
    -RunLevel Limited | Out-Null

Write-Host ""
Write-Host "Rudy registered as scheduled task: '$taskName'" -ForegroundColor Green
Write-Host "Will auto-start on login." -ForegroundColor Green
Write-Host ""
Write-Host "To start now:  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Cyan
Write-Host "To check:      Get-ScheduledTask -TaskName '$taskName' | Select State" -ForegroundColor Cyan
Write-Host "To stop:       Stop-ScheduledTask -TaskName '$taskName'" -ForegroundColor Cyan
Write-Host ""
