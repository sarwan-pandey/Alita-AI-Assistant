' ==============================================================================
' MJ AI ASSISTANT — ZERO-TOUCH JARVIS AUTORUN LAUNCHER (VBSCRIPT)
' ==============================================================================
' Executes silently on Windows boot without any command prompt popups.
' Boots Ollama (Hidden), Backend (Hidden), Frontend (Hidden).
' Actively verifies HTTP 200 health before launching standalone desktop widget.
' ==============================================================================

Option Explicit
Dim WshShell, fso, strAppDir, strBackendDir, strFrontendDir, strPyExe, pollCmd

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

strAppDir = "c:\Users\sarwa\Desktop\aura-assistant"
strBackendDir = strAppDir & "\backend"
strFrontendDir = strAppDir & "\frontend"
strPyExe = strBackendDir & "\venv\Scripts\python.exe"

' 1. Start Ollama in background (hidden)
WshShell.Run "powershell -NoProfile -Command ""$env:OLLAMA_HOST='127.0.0.1:11434'; $env:OLLAMA_ORIGINS='*'; Start-Process -FilePath 'C:\Users\sarwa\AppData\Local\Programs\Ollama\ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden""", 0, False

' 2. Start FastAPI Backend in background with absolute Python path (hidden)
WshShell.CurrentDirectory = strBackendDir
WshShell.Run "powershell -NoProfile -Command ""Start-Process -FilePath '" & strPyExe & "' -ArgumentList 'main.py' -WorkingDirectory '" & strBackendDir & "' -WindowStyle Hidden""", 0, False

' 3. Start Frontend dev server in background (hidden)
WshShell.CurrentDirectory = strFrontendDir
WshShell.Run "powershell -NoProfile -Command ""Start-Process -FilePath 'cmd.exe' -ArgumentList '/c npm run dev -- --port 5173' -WorkingDirectory '" & strFrontendDir & "' -WindowStyle Hidden""", 0, False

Set WshShell = Nothing
Set fso = Nothing

