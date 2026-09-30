' ==============================================================================
' MJ AI ASSISTANT — SILENT APP WINDOW LAUNCHER (VBSCRIPT)
' Opens MJ web application directly in standalone app window mode.
' Zero startup overlay. Zero command prompt popups.
' ==============================================================================

Option Explicit
Dim WshShell, strAppDir

Set WshShell = CreateObject("WScript.Shell")
strAppDir = "c:\Users\sarwa\Desktop\aura-assistant"

WshShell.Run "powershell -ExecutionPolicy Bypass -NoProfile -File """ & strAppDir & "\scripts\open_frontend.ps1""", 0, False

Set WshShell = Nothing
