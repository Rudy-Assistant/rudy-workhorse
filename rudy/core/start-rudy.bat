@echo off
:: ══════════════════════════════════════════════════════════
::  Rudy v2.0 — Full Startup
::  Launches BOTH:
::    1. Command Runner (Cowork-to-Windows bridge)
::    2. Email Listener (IMAP monitor)
:: ══════════════════════════════════════════════════════════

:: Credentials — passwords must be set in system environment variables
set RUDY_EMAIL=rudy.ciminoassist@gmail.com
if not defined RUDY_GMAIL_APP_PASSWORD (
    echo WARNING: RUDY_GMAIL_APP_PASSWORD not set. Email features will not work.
)

:: Working directory
cd /d "%USERPROFILE%\Desktop"

:: ── Start Command Runner in background ──────────────────
echo [%date% %time%] Starting Command Runner... >> rudy-logs\restart.log
start "Rudy-CommandRunner" /MIN python rudy-command-runner.py

:: ── Email Listener with auto-restart ────────────────────
:loop
echo [%date% %time%] Starting Rudy listener... >> rudy-logs\restart.log
python rudy-listener.py
echo [%date% %time%] Rudy exited with code %ERRORLEVEL% >> rudy-logs\restart.log

if %ERRORLEVEL% EQU 1 (
    echo [%date% %time%] Self-test failed — running diagnostics... >> rudy-logs\restart.log
    python rudy-diagnose.py >> rudy-logs\restart.log 2>&1
    echo [%date% %time%] Waiting 5 minutes before retry... >> rudy-logs\restart.log
    timeout /t 300 /nobreak >nul
) else (
    echo [%date% %time%] Unexpected exit — restarting in 30s... >> rudy-logs\restart.log
    timeout /t 30 /nobreak >nul
)
goto loop
