@echo off
:: Quick-start the Command Runner + register it for auto-start
:: Run this once after RUDY-FULL-SETUP.bat completes
cd /d "%USERPROFILE%\Desktop"

echo Starting Rudy Command Runner...
start "Rudy-CommandRunner" /MIN python rudy-command-runner.py

echo Registering for auto-start (needs admin for Task Scheduler)...
powershell -ExecutionPolicy Bypass -File install-command-runner.ps1

echo.
echo [OK] Command Runner is active.
echo     Cowork can now execute commands on this machine.
echo     Drop files in: Desktop\rudy-commands\
echo.
pause
