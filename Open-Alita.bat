@echo off
title Open MJ AI
set "SCRIPT_FILE=%~dp0scripts\open_frontend.ps1"
if not exist "%SCRIPT_FILE%" set "SCRIPT_FILE=c:\Users\sarwa\Desktop\aura-assistant\scripts\open_frontend.ps1"
powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_FILE%"
