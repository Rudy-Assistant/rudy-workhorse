@echo off
REM Robin Continuous Monitor — Starts at login via Windows Task Scheduler.
REM Runs robin_sentinel in continuous mode: boot sequence, then 5-min health loop.
REM Activates NightShift (which uses task queue) when Batman is inactive.
REM
REM Portable: resolves repo root from this script's location.

cd /d "%~dp0.."

echo [%date% %time%] Robin continuous monitor starting >> "%~dp0..\rudy-data\robin-continuous.log"

python -m rudy.agents.robin_sentinel --continuous >> "%~dp0..\rudy-data\robin-continuous.log" 2>&1

echo [%date% %time%] Robin continuous monitor exited >> "%~dp0..\rudy-data\robin-continuous.log"
