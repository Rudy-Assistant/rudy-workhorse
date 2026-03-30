@echo off
REM Robin Liveness Watchdog — Runs every 5 minutes via Windows Task Scheduler.
REM Checks if Robin is alive and restarts him if not.
REM Lightweight: single Python call, exits immediately.
REM
REM Portable: resolves repo root from this script's location.

set "REPO_ROOT=%~dp0.."
cd /d "%REPO_ROOT%"

REM Ensure log directory exists
set "LOG_DIR=%REPO_ROOT%\..\rudy-logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] Liveness watchdog tick >> "%LOG_DIR%\robin-liveness-watchdog.log"

python -m rudy.robin_liveness --ensure >> "%LOG_DIR%\robin-liveness-watchdog.log" 2>&1

echo [%date% %time%] Liveness watchdog done >> "%LOG_DIR%\robin-liveness-watchdog.log"
