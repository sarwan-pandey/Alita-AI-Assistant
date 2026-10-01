@echo off
title MJ AI Assistant - Startup
color 0A

echo.
echo ==============================================
echo        MJ AI ASSISTANT - STARTUP           
echo ==============================================
echo.

REM --- Step 1: Kill any stale processes ---
echo [1/5] Checking environment and processes...
taskkill /F /IM ollama_llama_server.exe >nul 2>&1
powershell -NoProfile -Command "Start-Sleep -Seconds 1"

REM --- Step 2: Ensure Ollama is running ---
echo [2/5] Initializing Ollama LLM server...
call "c:\Users\sarwa\Desktop\aura-assistant\backend\start_ollama.bat"
if %errorlevel% neq 0 (
    echo ERROR: Ollama failed to start!
    pause
    exit /b 1
)

REM --- Step 3: Warm up the active model (Qwen3 4B Q4) ---
echo [3/5] Warming up primary LLM (qwen3:4b-instruct) into memory...
powershell -NoProfile -Command "try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/chat' -Method Post -ContentType 'application/json' -Body '{\"model\":\"qwen3:4b-instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false,\"keep_alive\":-1,\"options\":{\"num_predict\":5,\"num_ctx\":4096}}' -TimeoutSec 60; exit 0 } catch { exit 1 }" >nul 2>&1
echo       Model (qwen3:4b-instruct) is pinned in memory (4096 context, keep_alive=-1). Response turnaround is instant.

REM --- Step 4: Ensure Frontend Dev Server is running ---
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:5173' -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    echo [4/5] Starting Frontend dev server in background...
    start /min cmd /c "cd /d c:\Users\sarwa\Desktop\aura-assistant\frontend && npm run dev -- --port 5173"
) else (
    echo [4/5] Frontend dev server is active!
)

REM --- Step 5: Start Overlay Auto-Launcher ---
echo [5/5] Launching Overlay Auto-Poller (pops up borderless crystal orb when ready)...
start /b "" powershell -NoProfile -Command "Start-Process -FilePath 'c:\Users\sarwa\Desktop\aura-assistant\backend\venv\Scripts\python.exe' -ArgumentList 'launch_overlay.py' -WorkingDirectory 'c:\Users\sarwa\Desktop\aura-assistant\backend' -WindowStyle Hidden"

echo.
echo ==============================================
echo   MJ is running on http://localhost:8000   
echo   Press Ctrl+C in this window to stop         
echo ==============================================
echo.

cd /d "c:\Users\sarwa\Desktop\aura-assistant\backend"
call venv\Scripts\activate.bat
echo       Environment: %VIRTUAL_ENV%
python main.py
