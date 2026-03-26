@echo off
title Digital Avatar Creator
echo ============================================
echo   Digital Avatar Creator
echo ============================================
echo.
echo Options:
echo   1. Create talking-head video (photo + audio)
echo   2. Face swap in a video
echo   3. Generate avatar from description
echo.
set /p CHOICE="Choose (1/2/3): "
cd /d "%USERPROFILE%\Desktop"
if "%CHOICE%"=="1" (
    set /p PHOTO="Path to face photo: "
    set /p AUDIO="Path to audio file: "
    python -c "from rudy.avatar import AvatarStudio; a=AvatarStudio(); r=a.talking_head(r'%PHOTO%', r'%AUDIO%'); print(r)"
)
if "%CHOICE%"=="2" (
    set /p SOURCE="Path to source face photo: "
    set /p TARGET="Path to target video: "
    python -c "from rudy.avatar import AvatarStudio; a=AvatarStudio(); r=a.face_swap(r'%SOURCE%', r'%TARGET%'); print(r)"
)
if "%CHOICE%"=="3" (
    set /p DESC="Describe the avatar: "
    python -c "from rudy.avatar import AvatarStudio; a=AvatarStudio(); r=a.generate_avatar('%DESC%'); print(r)"
)
echo.
pause
