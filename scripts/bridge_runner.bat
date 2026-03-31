@echo off
REM Bridge Runner — Peers-to-TaskQueue bridge for Robin
REM Runs as a Windows Scheduled Task under \Batcave\
REM Registers Robin with broker, polls for delegations, writes heartbeat.
REM
REM This is a LONG-RUNNING process. The scheduled task should be configured
REM to NOT start a new instance if already running.

cd /d C:\Users\ccimi\rudy-workhorse
C:\Python312\python.exe rudy\bridge_runner.py --interval 10
