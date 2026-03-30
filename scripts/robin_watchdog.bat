@echo off
REM Robin Watchdog — Runs every 15 minutes via Windows Task Scheduler.
REM Processes the next task from the queue. Seeds if queue is empty.
REM Lightweight: exits after one task. The scheduler re-invokes periodically.

cd /d C:\Users\ccimi\Desktop\rudy-workhorse

REM Log start
echo [%date% %time%] Robin watchdog tick >> rudy-data\robin-watchdog.log

REM Process one task (taskqueue handles empty-check internally)
python -m rudy.robin_taskqueue next >> rudy-data\robin-watchdog.log 2>&1
if %errorlevel% neq 0 (
    REM Queue was empty or task failed — seed and retry
    echo [%date% %time%] No tasks or failure, seeding >> rudy-data\robin-watchdog.log
    python -m rudy.robin_taskqueue seed >> rudy-data\robin-watchdog.log 2>&1
    python -m rudy.robin_taskqueue next >> rudy-data\robin-watchdog.log 2>&1
)

echo [%date% %time%] Robin watchdog done >> rudy-data\robin-watchdog.log
