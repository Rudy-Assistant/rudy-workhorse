@echo off
title Voice Clone Studio
echo ============================================
echo   Voice Clone Studio
echo ============================================
echo.
echo Options:
echo   1. Clone a voice from audio sample(s)
echo   2. Generate speech with a cloned voice
echo   3. List available voice profiles
echo.
set /p CHOICE="Choose (1/2/3): "
cd /d "%USERPROFILE%\Desktop"
if "%CHOICE%"=="1" (
    set /p AUDIO="Path to audio sample (WAV/MP3): "
    set /p NAME="Name for this voice profile: "
    python -c "from rudy.voice_clone import VoiceCloner; vc=VoiceCloner(); r=vc.clone_voice(r'%AUDIO%', '%NAME%'); print(r)"
)
if "%CHOICE%"=="2" (
    set /p NAME="Voice profile name: "
    set /p TEXT="Text to speak: "
    python -c "from rudy.voice_clone import VoiceCloner; vc=VoiceCloner(); r=vc.speak('%TEXT%', '%NAME%'); print(r)"
)
if "%CHOICE%"=="3" (
    python -c "from rudy.voice_clone import VoiceCloner; vc=VoiceCloner(); [print(f'  {p}') for p in vc.list_profiles()]"
)
echo.
pause
