@echo off
REM Alita - Smart Ollama Starter
REM Starts Ollama in the background (detached) using GPU mode (or CPU fallback).

set OLLAMA_HOST=127.0.0.1:11434
set OLLAMA_ORIGINS=*
set OLLAMA_KEEP_ALIVE=-1

REM Check if already running
powershell -NoProfile -Command "try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    echo Ollama is already running.
    exit /b 0
)

REM Start Ollama in background (detached process)
echo Starting Ollama LLM server...
powershell -NoProfile -Command "$env:OLLAMA_HOST='127.0.0.1:11434'; $env:OLLAMA_ORIGINS='*'; $env:OLLAMA_KEEP_ALIVE='-1'; Start-Process -FilePath 'C:\Users\sarwa\AppData\Local\Programs\Ollama\ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden"

REM Poll for Ollama ready up to 15 seconds
for /L %%i in (1,1,15) do (
    powershell -NoProfile -Command "try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 1; exit 0 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        echo Ollama server is ready!
        exit /b 0
    )
    powershell -NoProfile -Command "Start-Sleep -Seconds 1"
)

REM If GPU initialization failed, retry with CPU mode
echo GPU mode timed out. Retrying with CPU mode fallback...
taskkill /F /IM ollama.exe >nul 2>&1
taskkill /F /IM ollama_llama_server.exe >nul 2>&1
powershell -NoProfile -Command "Start-Sleep -Seconds 2"

powershell -NoProfile -Command "$env:CUDA_VISIBLE_DEVICES='-1'; $env:OLLAMA_HOST='127.0.0.1:11434'; $env:OLLAMA_ORIGINS='*'; $env:OLLAMA_KEEP_ALIVE='-1'; Start-Process -FilePath 'C:\Users\sarwa\AppData\Local\Programs\Ollama\ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden"

for /L %%i in (1,1,15) do (
    powershell -NoProfile -Command "try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 1; exit 0 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        echo Ollama server is ready (CPU mode)!
        exit /b 0
    )
    powershell -NoProfile -Command "Start-Sleep -Seconds 1"
)

echo ERROR: Ollama failed to start.
exit /b 1
