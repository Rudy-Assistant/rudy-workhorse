@echo off
title Quick Security Scan
echo ============================================
echo   Quick Security Scan
echo ============================================
echo.
cd /d "%USERPROFILE%\Desktop"
python -c "import sys; sys.path.insert(0,'.'); from rudy.agents.system_master import SystemMaster; SystemMaster().execute(mode='quick')"
echo.
pause
