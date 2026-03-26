@echo off
:: ══════════════════════════════════════════════════════════
::  RUDY FULL SETUP — One-click empowerment + auth fix
::  Installs all capability libraries, then diagnoses and
::  fixes the email listener.
:: ══════════════════════════════════════════════════════════

cd /d "%USERPROFILE%\Desktop"
echo.
echo  ====================================================
echo   RUDY FULL SETUP
echo   Phase 1: Install capability libraries
echo   Phase 2: Diagnose and fix email auth
echo  ====================================================
echo.

:: ── Phase 1: Libraries ───────────────────────────────────
echo [Phase 1] Installing capability libraries...
echo.

echo   Document creation...
pip install --break-system-packages python-pptx python-docx openpyxl reportlab PyPDF2 markdown >nul 2>&1

echo   Image and media...
pip install --break-system-packages Pillow svgwrite qrcode >nul 2>&1

echo   Web research...
pip install --break-system-packages requests beautifulsoup4 lxml feedparser httpx >nul 2>&1

echo   Data processing...
pip install --break-system-packages pandas matplotlib tabulate pyyaml jinja2 >nul 2>&1

echo   Email...
pip install --break-system-packages imapclient >nul 2>&1

echo   Browser automation (Playwright)...
pip install --break-system-packages playwright >nul 2>&1
python -m playwright install chromium >nul 2>&1

echo.
echo [Phase 1] Verifying installs...
python -c "import pptx; print('   [OK] python-pptx')"
python -c "import docx; print('   [OK] python-docx')"
python -c "import openpyxl; print('   [OK] openpyxl')"
python -c "import reportlab; print('   [OK] reportlab')"
python -c "import PIL; print('   [OK] Pillow')"
python -c "import requests; print('   [OK] requests')"
python -c "import bs4; print('   [OK] beautifulsoup4')"
python -c "import pandas; print('   [OK] pandas')"
python -c "import matplotlib; print('   [OK] matplotlib')"
python -c "import playwright; print('   [OK] playwright')"
echo.

:: ── Phase 2: Auth diagnostic ─────────────────────────────
echo [Phase 2] Running auth diagnostic...
echo.

set RUDY_EMAIL=rudy.ciminoassist@gmail.com
set RUDY_APP_PASSWORD=bviuyjdptufrtnys

python rudy-auth-fix.py

echo.
echo  ====================================================
echo   SETUP COMPLETE
echo   Check rudy-logs\auth-diagnostic.json for results
echo  ====================================================
echo.
pause
