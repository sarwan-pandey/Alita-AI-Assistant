# ==============================================================================
# MJ AI ASSISTANT — DIRECT APP WINDOW LAUNCHER
# Opens the MJ frontend directly in standalone Application Mode (no browser URL bar/tabs)
# ==============================================================================

$ErrorActionPreference = "SilentlyContinue"
$appDir = "c:\Users\sarwa\Desktop\aura-assistant"

function Test-Port($port) {
    try {
        $req = [System.Net.HttpWebRequest]::Create("http://localhost:$port")
        $req.Timeout = 800
        $req.Method = "HEAD"
        $resp = $req.GetResponse()
        $resp.Close()
        return $true
    } catch {
        if ($_.Exception.Response) {
            $_.Exception.Response.Close()
            return $true
        }
        return $false
    }
}

# If servers are not running, spin them up automatically
if (-not (Test-Port 5173)) {
    Write-Host "⚡ Frontend not running. Auto-starting MJ servers..." -ForegroundColor Yellow
    & "$appDir\scripts\start_servers.ps1"
}

# Launch standalone app window
$url = "http://localhost:5173"
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"

if (Test-Path $chromePath) {
    Start-Process -FilePath $chromePath -ArgumentList "--app=$url", "--window-size=1366,860"
} elseif (Test-Path $edgePath) {
    Start-Process -FilePath $edgePath -ArgumentList "--app=$url", "--window-size=1366,860"
} else {
    Start-Process $url
}
