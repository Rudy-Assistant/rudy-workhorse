@echo off
REM Robin Killswitch (S195 / P0-C) -- Batman one-click kill
REM Usage: robin-killswitch.bat            -> kill Robin gracefully then force
REM        robin-killswitch.bat --restart  -> kill then relaunch via canonical launcher
REM        robin-killswitch.bat --dry-run  -> list what would be killed, kill nothing
REM See docs\runbooks\robin-killswitch.md for full runbook.

setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0robin-killswitch.ps1" %*
endlocal
