@echo off
:: ══════════════════════════════════════════════════════════
::  Install Desktop Commander MCP + Windows-MCP
::  Gives Cowork/Claude full terminal + desktop control
:: ══════════════════════════════════════════════════════════

cd /d "%USERPROFILE%\Desktop"
echo.
echo  Installing Desktop Commander MCP...
echo  (terminal control, file search, diff editing)
echo.

:: Desktop Commander — terminal + filesystem
call npx @wonderwhy-er/desktop-commander@latest setup

echo.
echo  Installing Windows-MCP...
echo  (Windows UI control: click, type, open apps, screenshots)
echo.

:: Windows-MCP — full desktop automation
pip install --break-system-packages windows-mcp 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo  Windows-MCP pip install not available, trying npm...
    call npm install -g windows-mcp 2>nul
)

:: Also install MCPControl as a backup — another Windows automation MCP
echo.
echo  Installing MCPControl (Windows OS automation)...
call npm install -g mcp-control 2>nul

echo.
echo  ════════════════════════════════════════════════
echo   Verifying installations...
echo  ════════════════════════════════════════════════
echo.

:: Check Desktop Commander
call npx @wonderwhy-er/desktop-commander --version 2>nul && (
    echo  [OK] Desktop Commander MCP installed
) || (
    echo  [!!] Desktop Commander may need manual verification
)

echo.
echo  ════════════════════════════════════════════════
echo   NEXT STEP: Add to Claude Code MCP config
echo  ════════════════════════════════════════════════
echo.
echo  Desktop Commander should auto-configure itself.
echo  If not, add to Claude Code settings:
echo.
echo  "desktop-commander": {
echo    "command": "npx",
echo    "args": ["-y", "@wonderwhy-er/desktop-commander"]
echo  }
echo.

pause
