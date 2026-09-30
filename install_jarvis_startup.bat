@echo off
title MJ AI Assistant — Jarvis Startup Configurator
color 0B

echo.
echo =======================================================
echo     MJ AI ASSISTANT — JARVIS STARTUP INSTALLER      
echo =======================================================
echo.

set "SOURCE_VBS=c:\Users\sarwa\Desktop\aura-assistant\JarvisLauncher.vbs"
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "DEST_SHORTCUT=%STARTUP_FOLDER%\AlitaJarvisBoot.vbs"

if not exist "%SOURCE_VBS%" (
    echo [ERROR] Launcher file not found at: %SOURCE_VBS%
    pause
    exit /b 1
)

echo [1/2] Copying silent Jarvis launcher to Windows Startup folder...
copy /Y "%SOURCE_VBS%" "%DEST_SHORTCUT%" >nul 2>&1

if %errorlevel% equ 0 (
    echo [2/2] SUCCESS! Registered in:
    echo       "%DEST_SHORTCUT%"
    echo.
    echo =======================================================
    echo  MJ will now boot AUTOMATICALLY when Windows starts!
    echo  - Zero terminal windows on boot
    echo  - Permanent Admin login remembered
    echo  - Summon anytime with "Arise MJ" / "Hey MJ"
    echo =======================================================
) else (
    echo [ERROR] Failed to register in Startup folder.
)

echo.
pause
