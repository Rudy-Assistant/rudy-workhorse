@echo off
title Photo Timeline Generator
echo ============================================
echo   Photo Timeline Generator
echo ============================================
echo.
set /p FOLDER="Enter photo folder path: "
set /p TITLE="Enter timeline title (e.g. Japan Trip 2026): "
cd /d "%USERPROFILE%\Desktop"
python -c "import sys; from rudy.photo_intel import PhotoIntel; pi=PhotoIntel(); tl=pi.timeline(r'%FOLDER%', '%TITLE%'); html=pi.timeline_html(r'%FOLDER%', '%TITLE%'); open(r'rudy-data\photo-intel\reports\timeline.html','w').write(html); print('Timeline saved! Opening...'); import os; os.startfile(r'rudy-data\photo-intel\reports\timeline.html')"
echo.
pause
