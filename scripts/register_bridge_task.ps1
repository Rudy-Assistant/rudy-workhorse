# register_bridge_task.ps1 — Creates BridgeRunner scheduled task (requires admin)
# Run: Start-Process powershell -Verb RunAs -ArgumentList "-File C:\Users\ccimi\rudy-workhorse\scripts\register_bridge_task.ps1"

$ErrorActionPreference = "Stop"

$action = New-ScheduledTaskAction `
    -Execute "C:\Users\ccimi\rudy-workhorse\scripts\bridge_runner.bat" `
    -WorkingDirectory "C:\Users\ccimi\rudy-workhorse"

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "BridgeRunner" `
    -TaskPath "\Batcave\" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Peers-to-TaskQueue bridge. Registers Robin with broker, polls delegations, writes heartbeat." `
    -Force

Write-Host "BridgeRunner task registered successfully in \Batcave\" -ForegroundColor Green

# Start it immediately
Start-ScheduledTask -TaskPath "\Batcave\" -TaskName "BridgeRunner"
Write-Host "BridgeRunner started." -ForegroundColor Green
