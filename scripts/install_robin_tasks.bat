@echo off
REM Install Windows Scheduled Tasks for Robin autonomous operation.
REM Run this script as Administrator (elevated).
REM
REM Portable: resolves paths from this script's location.

set "SCRIPTS_DIR=%~dp0"
set "REPO_ROOT=%SCRIPTS_DIR%.."

echo Installing Robin Scheduled Tasks...
echo Repo root: %REPO_ROOT%

REM Task 1: Robin Watchdog — every 15 minutes, process one task from queue
schtasks /create /tn "Batcave\Robin Watchdog" /tr "\"%SCRIPTS_DIR%robin_watchdog.bat\"" /sc MINUTE /mo 15 /f
if %errorlevel% == 0 (
    echo [OK] Robin Watchdog installed (every 15 min)
) else (
    echo [FAIL] Robin Watchdog - try running as Administrator
)

REM Task 2: Robin Continuous — starts at user logon, persistent process
schtasks /create /tn "Batcave\Robin Continuous" /tr "\"%SCRIPTS_DIR%robin_continuous.bat\"" /sc ONLOGON /f
if %errorlevel% == 0 (
    echo [OK] Robin Continuous installed (at logon)
) else (
    echo [FAIL] Robin Continuous - try running as Administrator
)

echo.
echo Robin tasks installed. Verify with: schtasks /query /tn "Batcave\Robin Watchdog"
echo.
pause
