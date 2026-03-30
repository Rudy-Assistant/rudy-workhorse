@echo off
REM Robin Continuous Monitor — Starts at login via Windows Task Scheduler.
REM Runs robin_sentinel in continuous mode: boot sequence, then 5-min health loop.
REM Activates NightShift (which uses task queue) when Batman is inactive.

cd /d C:\Users\ccimi\Desktop\rudy-workhorse

echo [%date% %time%] Robin continuous monitor starting >> rudy-data\robin-continuous.log

python -m rudy.agents.robin_sentinel --continuous >> rudy-data\robin-continuous.log 2>&1

echo [%date% %time%] Robin continuous monitor exited >> rudy-data\robin-continuous.log
