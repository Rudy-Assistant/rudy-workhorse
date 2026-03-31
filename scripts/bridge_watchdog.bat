@echo off
REM Bridge Watchdog - Checks if bridge_runner.py is alive, restarts if dead.
REM Runs every 5 minutes via scheduled task.
REM Session 36: Created for P4 bridge_runner auto-restart.
REM Session 37: Fixed LG-S37-001 - use lock file + heartbeat instead of
REM   unreliable tasklist/findstr (which checked window titles, not cmdlines).
REM   bridge_runner.py now has PID lockfile singleton enforcement.

cd /d C:\Users\ccimi\rudy-workhorse

REM Ensure git/node/python in PATH
set "PATH=C:\Program Files\Git\cmd;C:\Program Files\nodejs;C:\Python312;%PATH%"

REM Ensure OPENAI_API_KEY is set (doesn't propagate from setx to scheduled tasks)
for /f "usebackq tokens=*" %%k in (`powershell -Command "[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User')"`) do set "OPENAI_API_KEY=%%k"

set "LOCK_FILE=C:\Users\ccimi\rudy-data\bridge-runner.lock"
set "LOG_FILE=C:\Users\ccimi\rudy-data\logs\bridge-watchdog.log"

REM Strategy: bridge_runner.py now enforces singleton via PID lockfile.
REM The watchdog just needs to attempt a start -- bridge_runner will exit
REM immediately if another instance is already running (prints ALREADY_RUNNING).
REM This is simpler and more reliable than parsing process lists.

REM Check if lock file exists and extract PID
if not exist "%LOCK_FILE%" goto :start_bridge

REM Lock file exists -- check if the PID is still alive
for /f "usebackq tokens=*" %%p in (`powershell -Command "(Get-Content '%LOCK_FILE%' | ConvertFrom-Json).pid"`) do set "LOCK_PID=%%p"
if "%LOCK_PID%"=="" goto :start_bridge

REM Check if PID is alive
tasklist /fi "PID eq %LOCK_PID%" 2>nul | findstr /i "%LOCK_PID%" >nul
if %ERRORLEVEL% EQU 0 (
    REM Bridge is running (PID alive), nothing to do
    exit /b 0
)

REM PID from lock is dead -- stale lock, clean up and restart
echo [%DATE% %TIME%] Stale lock (PID %LOCK_PID% dead), cleaning up >> "%LOG_FILE%"
del "%LOCK_FILE%" 2>nul

:start_bridge
echo [%DATE% %TIME%] Starting bridge_runner... >> "%LOG_FILE%"
start /b "" C:\Python312\python.exe rudy\bridge_runner.py --interval 10
echo [%DATE% %TIME%] Start issued >> "%LOG_FILE%"
