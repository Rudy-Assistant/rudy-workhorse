@echo off
REM Bridge Runner — Peers-to-TaskQueue bridge for Robin
REM Runs as a Windows Scheduled Task under \Batcave\
REM Registers Robin with broker, polls for delegations, writes heartbeat.
REM
REM Session 34 fix: verify we're on the right branch before starting.
REM This prevents running stale code from main when work is on a feature branch.

cd /d C:\Users\ccimi\rudy-workhorse

REM Session 36 fix (LG-S33-003): ensure git/node/python in PATH
set "PATH=C:\Program Files\Git\cmd;C:\Program Files\nodejs;C:\Python312;%PATH%"

REM Log current branch for diagnostics
"C:\Program Files\Git\cmd\git.exe" branch --show-current > C:\Users\ccimi\rudy-data\logs\bridge-branch.log 2>&1
echo Started at %DATE% %TIME% on branch: >> C:\Users\ccimi\rudy-data\logs\bridge-branch.log
"C:\Program Files\Git\cmd\git.exe" branch --show-current >> C:\Users\ccimi\rudy-data\logs\bridge-branch.log 2>&1

C:\Python312\python.exe rudy\bridge_runner.py --interval 10
