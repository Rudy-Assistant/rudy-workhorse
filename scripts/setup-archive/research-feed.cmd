@echo off
REM Workhorse Research Feed - Quick Launcher
REM Usage: research-feed.cmd [quick|full|validate]

setlocal enabledelayedexpansion

cd /d "%~dp0"

if "%1"=="quick" (
    python workhorse-research-feed.py --quick
    goto end
)

if "%1"=="validate" (
    python workhorse-subscribe.py validate
    goto end
)

if "%1"=="full" (
    python workhorse-research-feed.py
    goto end
)

if "%1"=="" (
    REM No argument - show menu
    echo.
    echo Workhorse Research Feed Launcher
    echo ==================================
    echo.
    echo Usage: research-feed.cmd [command]
    echo.
    echo Commands:
    echo   quick              Run quick mode ^(30-60 seconds, 5 feeds^)
    echo   full               Run full mode ^(5-15 minutes, all feeds^)
    echo   validate           Check feed health ^(connectivity test^)
    echo.
    echo Examples:
    echo   research-feed.cmd quick
    echo   research-feed.cmd full
    echo   research-feed.cmd validate
    echo.
    echo Or use:
    echo   python workhorse-research-feed.py [--quick^|--debug]
    echo   python workhorse-subscribe.py [list^|add^|remove^|validate]
    echo.
    echo Reports saved to: rudy-logs\research-feed-[date].json
    echo Digest saved to:  rudy-logs\research-digest-[date].md
    echo.
    goto end
)

echo Unknown command: %1
echo Use: research-feed.cmd [quick^|full^|validate]

:end
pause
