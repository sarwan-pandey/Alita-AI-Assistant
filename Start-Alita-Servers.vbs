' ==============================================================================
' MJ AI ASSISTANT — SILENT SERVER LAUNCHER (VBSCRIPT)
' Boots Ollama, Backend, Frontend, and Cloudflare/Ngrok Tunnel silently in background.
' Supports optional /restart parameter
' ==============================================================================

Option Explicit
Dim WshShell, strAppDir, extraArg

Set WshShell = CreateObject("WScript.Shell")
strAppDir = "c:\Users\sarwa\Desktop\aura-assistant"

extraArg = ""
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "/restart" Or LCase(WScript.Arguments(0)) = "-restart" Or LCase(WScript.Arguments(0)) = "-r" Then
        extraArg = " -Restart"
    End If
End If

WshShell.Run "powershell -ExecutionPolicy Bypass -NoProfile -File """ & strAppDir & "\scripts\start_servers.ps1""" & extraArg, 0, False

Set WshShell = Nothing
