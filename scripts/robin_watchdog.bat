@echo off
REM Robin Watchdog — Runs every 15 minutes via Windows Task Scheduler.
REM Processes the next task from the queue. Seeds if queue is empty.
REM Lightweight: exits after one task. The scheduler re-invokes periodically.
REM
REM Portable: resolves repo root from this script's location.

set "REPO_ROOT=%~dp0.."
cd /d "%REPO_ROOT%"

REM Ensure data dir exists
if not exist "%REPO_ROOT%\..\rudy-data" mkdir "%REPO_ROOT%\..\rudy-data"

set "LOGFILE=%REPO_ROOT%\..\rudy-data\robin-watchdog.log"

REM Log start
echo [%date% %time%] Robin watchdog tick >> "%LOGFILE%"

REM Process one task (taskqueue handles empty-check internally)
python -m rudy.robin_taskqueue next >> "%LOGFILE%" 2>&1
if %errorlevel% neq 0 (
    REM Queue was empty or task failed — seed and retry
    echo [%date% %time%] No tasks or failure, seeding >> "%LOGFILE%"
    python -m rudy.robin_taskqueue seed >> "%LOGFILE%" 2>&1
    python -m rudy.robin_taskqueue next >> "%LOGFILE%" 2>&1
)

echo [%date% %time%] Robin watchdog done >> "%LOGFILE%"
