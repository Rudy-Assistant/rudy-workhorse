@echo off
:: ============================================================
:: ONE-CLICK RUSTDESK UNATTENDED ACCESS FIX
:: Right-click → Run as Administrator (or just double-click)
:: ============================================================

:: Self-elevate to admin if not already
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo   RUSTDESK PERMANENT UNATTENDED ACCESS FIX
echo ============================================================

set PW=CMCPassTemp7508!
set RDEXE="C:\Program Files\RustDesk\rustdesk.exe"
set USERCONFIG=C:\Users\C\AppData\Roaming\RustDesk\config
set LOGDIR=C:\Users\C\Desktop\rudy-logs

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo.
echo [1/7] Stopping RustDesk...
net stop RustDesk >nul 2>&1
taskkill /F /IM rustdesk.exe >nul 2>&1
timeout /t 3 /nobreak >nul

echo [2/7] Setting permanent password via CLI...
%RDEXE% --password %PW%

echo [3/7] Ensuring user config has password-only mode...
powershell -ExecutionPolicy Bypass -Command ^
  "$f = '%USERCONFIG%\RustDesk2.toml'; " ^
  "$c = Get-Content $f -Raw -EA SilentlyContinue; " ^
  "if ($c -notmatch 'use-permanent-password') { " ^
  "  $c = $c -replace '(?s)\[options\].*', ''; " ^
  "  $c += \"`n[options]`nverification-method = \`\"use-permanent-password\`\"`napprove-mode = \`\"password\`\"`nallow-remote-config-modification = \`\"Y\`\"`ndirect-server = \`\"Y\`\"`nenable-file-transfer = \`\"Y\`\"`n\"; " ^
  "  Set-Content $f $c; Write-Host '  User config FIXED' " ^
  "} else { Write-Host '  User config already correct' }"

echo [4/7] Copying config to ALL service profile paths...
for %%D in (
    "C:\Windows\System32\config\systemprofile\AppData\Roaming\RustDesk\config"
    "C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config"
    "C:\Windows\ServiceProfiles\LocalSystem\AppData\Roaming\RustDesk\config"
) do (
    if not exist %%D mkdir %%D 2>nul
    copy /Y "%USERCONFIG%\RustDesk.toml" %%D\ >nul 2>&1
    copy /Y "%USERCONFIG%\RustDesk2.toml" %%D\ >nul 2>&1
    echo   Copied to %%D
)

echo [5/7] Setting service to auto-start...
sc config RustDesk start= auto >nul
echo   Done

echo [6/7] Creating boot-time enforcement task...
:: Write enforcement PowerShell script
powershell -ExecutionPolicy Bypass -Command ^
  "$s = @'`n" ^
  "Start-Sleep 10`n" ^
  "& 'C:\Program Files\RustDesk\rustdesk.exe' --password CMCPassTemp7508! 2>&1 | Out-Null`n" ^
  "$src = 'C:\Users\C\AppData\Roaming\RustDesk\config'`n" ^
  "@(`n" ^
  "  'C:\Windows\System32\config\systemprofile\AppData\Roaming\RustDesk\config',`n" ^
  "  'C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config'`n" ^
  ") | ForEach-Object {`n" ^
  "  New-Item -ItemType Directory -Path $_ -Force -EA SilentlyContinue | Out-Null`n" ^
  "  Copy-Item \"$src\RustDesk.toml\" \"$_\RustDesk.toml\" -Force -EA SilentlyContinue`n" ^
  "  Copy-Item \"$src\RustDesk2.toml\" \"$_\RustDesk2.toml\" -Force -EA SilentlyContinue`n" ^
  "}`n" ^
  "if ((Get-Service RustDesk -EA SilentlyContinue).Status -ne 'Running') { Start-Service RustDesk -EA SilentlyContinue }`n" ^
  "(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  Enforcement complete' | Out-File -Append 'C:\Users\C\Desktop\rudy-logs\rustdesk-enforce.log'`n" ^
  "'@; Set-Content 'C:\Users\C\Desktop\enforce-rustdesk-config.ps1' $s; Write-Host '  Script written'"

:: Create scheduled task running as SYSTEM at boot
schtasks /delete /tn "RustDeskConfigEnforce" /f >nul 2>&1
schtasks /create /tn "RustDeskConfigEnforce" /tr "powershell.exe -ExecutionPolicy Bypass -File C:\Users\C\Desktop\enforce-rustdesk-config.ps1" /sc onstart /delay 0000:30 /ru SYSTEM /rl HIGHEST /f
echo   Boot enforcement task created

echo [7/7] Starting RustDesk service...
net start RustDesk
timeout /t 3 /nobreak >nul

echo.
echo ============================================================
echo   VERIFICATION
echo ============================================================
sc query RustDesk | findstr STATE
tasklist /FI "IMAGENAME eq rustdesk.exe" /FO TABLE /NH 2>nul
schtasks /query /tn "RustDeskConfigEnforce" /fo list | findstr "Status:"
echo.
echo ============================================================
echo   DONE! Now:
echo   1. Disconnect from RustDesk
echo   2. Reconnect using password: %PW%
echo   3. It should connect WITHOUT asking for manual approval
echo   4. Boot enforcement task will re-apply on every restart
echo ============================================================
echo.
echo Press any key to close...
pause >nul
