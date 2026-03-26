@echo off
:: ──────────────────────────────────────────────
:: One-click launcher for mini PC setup
:: Right-click → Run as Administrator
:: ──────────────────────────────────────────────
echo.
echo ============================================
echo   Claude Workhorse - Mini PC Setup
echo ============================================
echo.
echo This will run two scripts:
echo   1. setup-mini-pc.ps1    (requires Admin - power, login, RDP, etc.)
echo   2. install-claude-toolkits.ps1  (user-level - plugins, MCP servers)
echo.
echo Press any key to start, or Ctrl+C to cancel...
pause >nul

:: Check for admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Please right-click this file and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

:: Get script directory
set "SCRIPT_DIR=%~dp0"

echo.
echo ── Step 1/2: System Configuration (Admin) ──
echo.
powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%setup-mini-pc.ps1"

echo.
echo ── Step 2/2: Claude Code Toolkits (User) ──
echo.
powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install-claude-toolkits.ps1"

echo.
echo ============================================
echo   ALL DONE
echo ============================================
echo.
echo Remember the manual steps:
echo   1. BIOS: Set AC Power Recovery to Power On
echo   2. RustDesk: Set permanent unattended password
echo   3. Router: Reserve static IP
echo   4. Claude Code: /plugin install superpowers@superpowers-marketplace
echo   5. Claude Code: /plugin install everything-claude-code@everything-claude-code
echo.
pause
