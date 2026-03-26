@echo off
REM ============================================================
REM  The Workhorse — Master Startup Script
REM  Ensures all critical services are running after reboot.
REM  Deployed to Task Scheduler to run at logon + on boot.
REM ============================================================

set LOGDIR=C:\Users\C\Desktop\rudy-logs
set LOGFILE=%LOGDIR%\workhorse-startup.log
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo  Workhorse Startup — %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

REM --- 1. RustDesk (remote access — CRITICAL) ---
echo [1] Checking RustDesk... >> "%LOGFILE%"
tasklist /FI "IMAGENAME eq rustdesk.exe" 2>NUL | find /I /N "rustdesk.exe" >NUL
if "%ERRORLEVEL%"=="0" (
    echo     RustDesk already running >> "%LOGFILE%"
) else (
    echo     Starting RustDesk... >> "%LOGFILE%"
    REM Try common install locations
    if exist "C:\Program Files\RustDesk\rustdesk.exe" (
        start "" "C:\Program Files\RustDesk\rustdesk.exe" --tray
        echo     Started from Program Files >> "%LOGFILE%"
    ) else if exist "%LOCALAPPDATA%\RustDesk\rustdesk.exe" (
        start "" "%LOCALAPPDATA%\RustDesk\rustdesk.exe" --tray
        echo     Started from LocalAppData >> "%LOGFILE%"
    ) else (
        echo     WARNING: RustDesk not found! >> "%LOGFILE%"
    )
)

REM --- 2. Tailscale (VPN/networking) ---
echo [2] Checking Tailscale... >> "%LOGFILE%"
REM Tailscale runs as a Windows service (Tailscale IPN), should auto-start
sc query Tailscale >NUL 2>&1
if "%ERRORLEVEL%"=="0" (
    echo     Tailscale service exists >> "%LOGFILE%"
    sc query Tailscale | find "RUNNING" >NUL 2>&1
    if "%ERRORLEVEL%"=="0" (
        echo     Tailscale service running >> "%LOGFILE%"
    ) else (
        echo     Starting Tailscale service... >> "%LOGFILE%"
        net start Tailscale >> "%LOGFILE%" 2>&1
    )
) else (
    REM Try "Tailscaled" service name
    sc query Tailscaled >NUL 2>&1
    if "%ERRORLEVEL%"=="0" (
        sc query Tailscaled | find "RUNNING" >NUL 2>&1
        if not "%ERRORLEVEL%"=="0" (
            net start Tailscaled >> "%LOGFILE%" 2>&1
        )
        echo     Tailscaled service handled >> "%LOGFILE%"
    ) else (
        echo     WARNING: No Tailscale service found >> "%LOGFILE%"
    )
)

REM --- 3. Wait for network (important after boot) ---
echo [3] Waiting for network... >> "%LOGFILE%"
timeout /t 10 /nobreak >NUL
ping -n 1 8.8.8.8 >NUL 2>&1
if "%ERRORLEVEL%"=="0" (
    echo     Network is up >> "%LOGFILE%"
) else (
    echo     Network not ready, waiting 20 more seconds... >> "%LOGFILE%"
    timeout /t 20 /nobreak >NUL
)

REM --- 4. Rudy ecosystem (command runner + listener) ---
echo [4] Starting Rudy ecosystem... >> "%LOGFILE%"
if exist "C:\Users\C\Desktop\start-rudy.bat" (
    start "" /MIN cmd /c "C:\Users\C\Desktop\start-rudy.bat"
    echo     Launched start-rudy.bat >> "%LOGFILE%"
) else (
    echo     start-rudy.bat not found, starting components individually... >> "%LOGFILE%"
    if exist "C:\Users\C\Desktop\rudy-command-runner.py" (
        start "" /MIN cmd /c "python C:\Users\C\Desktop\rudy-command-runner.py"
        echo     Started rudy-command-runner.py >> "%LOGFILE%"
    )
    if exist "C:\Users\C\Desktop\rudy-listener.py" (
        start "" /MIN cmd /c "python C:\Users\C\Desktop\rudy-listener.py"
        echo     Started rudy-listener.py >> "%LOGFILE%"
    )
)

REM --- 5. Start watchdog (monitors everything, restarts if needed) ---
echo [5] Starting watchdog... >> "%LOGFILE%"
if exist "C:\Users\C\Desktop\workhorse-watchdog.py" (
    start "" /MIN cmd /c "python C:\Users\C\Desktop\workhorse-watchdog.py"
    echo     Started workhorse-watchdog.py >> "%LOGFILE%"
) else (
    echo     watchdog not found (optional) >> "%LOGFILE%"
)

echo. >> "%LOGFILE%"
echo  Startup sequence complete — %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
