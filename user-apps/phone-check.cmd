@echo off
title Phone Check — Mobile Security Scanner
echo ============================================
echo   Phone Check — Mobile Security Scanner
echo ============================================
echo.
echo Connect your phone via USB, then press any key.
echo   iOS: Tap "Trust This Computer" on the phone
echo   Android: Enable USB Debugging in Developer Options
echo.
pause
cd /d "%USERPROFILE%\Desktop"
python -c "from rudy.phone_check import PhoneCheck; c=PhoneCheck(); reports=c.auto_scan(); [print(c.generate_report_summary(r)) for r in reports if 'error' not in r or print(r.get('error','') or r.get('troubleshooting',''))]"
echo.
pause
