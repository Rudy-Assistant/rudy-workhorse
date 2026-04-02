@echo off
REM robin-session-launcher.bat -- Launch a Claude Code session from a prompt file.
REM Usage: robin-session-launcher.bat <prompt-file-path>
REM This is Robin's Option B for session initiation (S62).
set "CLAUDE_EXE=claude"
set "REPO_ROOT=%~dp0.."
if "%~1"=="" (
    echo ERROR: No prompt file specified.
    echo Usage: %~nx0 ^<prompt-file-path^>
    exit /b 1
)
set "PROMPT_FILE=%~1"
if not exist "%PROMPT_FILE%" (
    echo ERROR: Prompt file not found: %PROMPT_FILE%
    exit /b 1
)
echo [robin-session-launcher] Launching from: %PROMPT_FILE%
cd /d "%REPO_ROOT%"
%CLAUDE_EXE% -p "%PROMPT_FILE%" --output-format text
set "EXIT_CODE=%ERRORLEVEL%"
echo [robin-session-launcher] Claude exited with code: %EXIT_CODE%
exit /b %EXIT_CODE%
