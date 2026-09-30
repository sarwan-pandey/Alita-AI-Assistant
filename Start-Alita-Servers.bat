@echo off
title Alita / MJ Server Controller
setlocal enabledelayedexpansion

set "SCRIPT_FILE=%~dp0scripts\start_servers.ps1"
if not exist "%SCRIPT_FILE%" set "SCRIPT_FILE=c:\Users\sarwa\Desktop\aura-assistant\scripts\start_servers.ps1"

REM Check for CLI arguments:
if /i "%~1"=="--restart" goto do_restart
if /i "%~1"=="-r" goto do_restart
if /i "%~1"=="restart" goto do_restart
if /i "%~1"=="--restart-all" goto do_restart_all
if /i "%~1"=="-ra" goto do_restart_all
if /i "%~1"=="--stop" goto do_stop
if /i "%~1"=="-s" goto do_stop
if /i "%~1"=="stop" goto do_stop
if /i "%~1"=="--status" goto do_status
if /i "%~1"=="status" goto do_status

echo.
echo ========================================================
echo               ALITA / MJ SERVER CONTROLLER             
echo ========================================================
echo   [1] Start / Ensure Servers (Auto-starts in 5 seconds)
echo   [2] Restart App Servers    (Backend + Frontends + Tunnel)
echo   [3] Restart ALL Servers    (Including Ollama LLM)
echo   [4] Stop All Servers
echo   [5] Check Server Status
echo ========================================================
echo.

choice /c 12345 /n /t 5 /d 1 /m "Select option [1-5] (Default: 1): "
set "OPT=%errorlevel%"

if "%OPT%"=="1" goto do_start
if "%OPT%"=="2" goto do_restart
if "%OPT%"=="3" goto do_restart_all
if "%OPT%"=="4" goto do_stop
if "%OPT%"=="5" goto do_status
goto do_start

:do_start
powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_FILE%"
goto end

:do_restart
powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_FILE%" -Restart
goto end

:do_restart_all
powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_FILE%" -Restart -RestartAll
goto end

:do_stop
powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_FILE%" -Stop
goto end

:do_status
powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_FILE%" -Status
goto end

:end
echo.
pause
