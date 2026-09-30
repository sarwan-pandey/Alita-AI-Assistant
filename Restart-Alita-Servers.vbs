' ==============================================================================
' MJ AI ASSISTANT — SILENT SERVER RESTART (VBSCRIPT)
' Kills and reboots Backend, Frontend, and Ngrok Tunnel silently in background.
' Zero startup overlay. Zero command prompt popups.
' ==============================================================================

Option Explicit
Dim WshShell, strAppDir

Set WshShell = CreateObject("WScript.Shell")
strAppDir = "c:\Users\sarwa\Desktop\aura-assistant"

WshShell.Run "powershell -ExecutionPolicy Bypass -NoProfile -File """ & strAppDir & "\scripts\start_servers.ps1"" -Restart", 0, False

Set WshShell = Nothing
