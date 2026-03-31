@echo off
REM Robin Chat GUI -- Web interface at http://localhost:7777
REM Runs as a Windows Scheduled Task under \Batcave\
REM Batman can chat with Robin, trigger activations, and start sessions.

cd /d C:\Users\ccimi\rudy-workhorse
C:\Python312\python.exe -m rudy.robin_chat_gui
