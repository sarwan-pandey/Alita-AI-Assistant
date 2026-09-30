@echo off
title Alita / MJ - Restarting All Servers
set "SCRIPT_FILE=%~dp0scripts\start_servers.ps1"
if not exist "%SCRIPT_FILE%" set "SCRIPT_FILE=c:\Users\sarwa\Desktop\aura-assistant\scripts\start_servers.ps1"
powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_FILE%" -Restart
pause
