@echo off
REM Bridge Watchdog — Checks if bridge_runner.py is alive, restarts if dead.
REM Runs every 5 minutes via scheduled task.
REM Session 36 fix for P4: bridge_runner auto-restart.

cd /d C:\Users\ccimi\rudy-workhorse

REM Ensure git/node/python in PATH
set "PATH=C:\Program Files\Git\cmd;C:\Program Files\nodejs;C:\Python312;%PATH%"

REM Check if bridge_runner.py is in the process list
tasklist /fi "imagename eq python.exe" /v 2>nul | findstr /i "bridge_runner" >nul
if %ERRORLEVEL% EQU 0 (
    REM Bridge is running, nothing to do
    exit /b 0
)

REM Bridge is NOT running — restart it
echo [%DATE% %TIME%] Bridge dead, restarting... >> C:\Users\ccimi\rudy-data\logs\bridge-watchdog.log
start /b "" C:\Python312\python.exe rudy\bridge_runner.py --interval 10
echo [%DATE% %TIME%] Restart issued >> C:\Users\ccimi\rudy-data\logs\bridge-watchdog.log
