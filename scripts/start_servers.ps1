# ==============================================================================
# MJ AI ASSISTANT - MASTER SERVER STACK CONTROLLER
# Supports: Start, Restart (-Restart), Restart All (-RestartAll), Stop (-Stop), Status (-Status)
# ==============================================================================

param(
    [switch]$Restart,
    [switch]$RestartAll,
    [switch]$Stop,
    [switch]$Status
)

$ErrorActionPreference = "SilentlyContinue"
$appDir = "c:\Users\sarwa\Desktop\aura-assistant"
$backendDir = "$appDir\backend"
$frontendDir = "$appDir\frontend"
$avatarDir = "$appDir\frontend-avatar"
$pyExe = "$backendDir\venv\Scripts\python.exe"
$ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
$ngrokExe = "$appDir\scripts\ngrok.exe"
if (-not (Test-Path $ngrokExe)) {
    $ngrokExe = "C:\Users\sarwa\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
}

function Test-Port([int]$port) {
    if ($port -le 0) { return $false }
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $port)
        $tcp.Close()
        return $true
    } catch {}

    try {
        $tcp = New-Object System.Net.Sockets.TcpClient([System.Net.Sockets.AddressFamily]::InterNetworkV6)
        $tcp.Connect("::1", $port)
        $tcp.Close()
        return $true
    } catch {}

    return $false
}

function Get-PortPID([int]$targetPort) {
    if ($targetPort -le 0) { return $null }

    try {
        $conn = Get-NetTCPConnection -LocalPort $targetPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn -and $conn.OwningProcess -gt 4) {
            return [int]$conn.OwningProcess
        }
    } catch {}

    # Netstat fallback
    try {
        $lines = netstat -ano | Select-String ":$targetPort\s+.*LISTENING"
        foreach ($line in $lines) {
            $parts = ($line -replace '\s+', ' ').Trim().Split(' ')
            if ($parts.Length -ge 5) {
                $candidate = [int]$parts[$parts.Length - 1]
                if ($candidate -gt 4) {
                    return $candidate
                }
            }
        }
    } catch {}

    return $null
}

function Stop-PortProcess([int]$port, [string]$label) {
    $foundPid = Get-PortPID $port
    if ($foundPid) {
        $proc = Get-Process -Id $foundPid -ErrorAction SilentlyContinue
        $pName = if ($proc) { $proc.Name } else { "PID $foundPid" }
        Write-Host "  [-] Stopping $label ($pName, PID $foundPid on port $port)..." -ForegroundColor Yellow
        Stop-Process -Id $foundPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 400
    }
}

function Stop-AlitaServers([bool]$includeOllama) {
    Write-Host ""
    Write-Host "[*] Stopping Alita Server Stack..." -ForegroundColor Red

    # 1. Stop Backend (Port 8000)
    Stop-PortProcess 8000 "Backend API"

    # 2. Stop Frontend Vite (Port 5173)
    Stop-PortProcess 5173 "Frontend App"

    # 3. Stop 3D Avatar (Port 5174)
    Stop-PortProcess 5174 "3D Human Avatar"

    # 4. Stop Ngrok Tunnel
    $ngrokProcs = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
    if ($ngrokProcs) {
        Write-Host "  [-] Stopping Ngrok Tunnel..." -ForegroundColor Yellow
        $ngrokProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    }

    # 5. Stop Ollama if explicitly requested
    if ($includeOllama) {
        Stop-PortProcess 11434 "Ollama LLM"
        Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 1
    Write-Host "[OK] All requested services stopped." -ForegroundColor Green
}

function Show-AlitaStatus {
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "              ALITA SERVER STACK STATUS                 " -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan

    $services = @(
        @{ Name = "FastAPI Backend";  Port = 8000;  URL = "http://localhost:8000" },
        @{ Name = "Frontend App";     Port = 5173;  URL = "http://localhost:5173" },
        @{ Name = "3D Human Avatar";  Port = 5174;  URL = "http://localhost:5174" },
        @{ Name = "Ollama LLM";       Port = 11434; URL = "http://localhost:11434" }
    )

    foreach ($s in $services) {
        $portNum = [int]$s["Port"]
        $foundPid = Get-PortPID $portNum
        if ($foundPid) {
            $proc = Get-Process -Id $foundPid -ErrorAction SilentlyContinue
            $procName = if ($proc) { $proc.Name } else { "unknown" }
            Write-Host ("  [ACTIVE]   {0,-18} Port {1,-5} (PID {2,-5} - {3}) {4}" -f $s["Name"], $portNum, $foundPid, $procName, $s["URL"]) -ForegroundColor Green
        } else {
            Write-Host ("  [INACTIVE] {0,-18} Port {1,-5} {2}" -f $s["Name"], $portNum, $s["URL"]) -ForegroundColor DarkGray
        }
    }

    $ngrok = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
    if ($ngrok) {
        Write-Host "  [ACTIVE]   Ngrok Tunnel       (PID $($ngrok.Id)) -> https://praising-cahoots-safely.ngrok-free.dev" -ForegroundColor Green
    } else {
        Write-Host "  [INACTIVE] Ngrok Tunnel       (Not running)" -ForegroundColor DarkGray
    }

    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host ""
}

# ── Execute Status Mode ───────────────────────────────────────────────────────
if ($Status) {
    Show-AlitaStatus
    exit 0
}

# ── Execute Stop Mode ─────────────────────────────────────────────────────────
if ($Stop) {
    Stop-AlitaServers -includeOllama $RestartAll
    Show-AlitaStatus
    exit 0
}

# ── Execute Restart Mode ──────────────────────────────────────────────────────
if ($Restart -or $RestartAll) {
    Write-Host ""
    Write-Host "[*] RESTART REQUESTED - Recycling active services..." -ForegroundColor Magenta
    Stop-AlitaServers -includeOllama $RestartAll
    Start-Sleep -Seconds 1
}

# ── Start Services ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[*] Starting MJ AI Server Stack..." -ForegroundColor Cyan

# 1. Ollama Server (Port 11434)
if (Test-Port 11434) {
    Write-Host "  [OK] Ollama already running on port 11434" -ForegroundColor Green
} else {
    Write-Host "  [*] Launching Ollama daemon..." -ForegroundColor Yellow
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $env:OLLAMA_ORIGINS = '*'
    if (Test-Path $ollamaExe) {
        Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    }
}

# 2. FastAPI Backend (Port 8000)
if (Test-Port 8000) {
    Write-Host "  [OK] Backend already running on port 8000" -ForegroundColor Green
} else {
    Write-Host "  [*] Launching FastAPI backend (main.py)..." -ForegroundColor Yellow
    Start-Process -FilePath $pyExe -ArgumentList "main.py" -WorkingDirectory $backendDir -WindowStyle Hidden
}

# 3. Frontend Dev Server (Port 5173)
if (Test-Port 5173) {
    Write-Host "  [OK] Frontend already running on port 5173" -ForegroundColor Green
} else {
    Write-Host "  [*] Launching Vite Frontend server (port 5173)..." -ForegroundColor Yellow
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev -- --port 5173" -WorkingDirectory $frontendDir -WindowStyle Hidden
}

# 3b. 3D Living Human Avatar Frontend (Port 5174)
if (Test-Path $avatarDir) {
    if (Test-Port 5174) {
        Write-Host "  [OK] 3D Human Avatar already running on port 5174" -ForegroundColor Green
    } else {
        Write-Host "  [*] Launching 3D Human Avatar server (port 5174)..." -ForegroundColor Yellow
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory $avatarDir -WindowStyle Hidden
    }
}

# 4. Permanent Remote Tunnel (Ngrok Static Domain)
$ngrokRunning = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
if ($ngrokRunning) {
    Write-Host "  [OK] Ngrok Permanent Tunnel already active" -ForegroundColor Green
} else {
    if (Test-Path $ngrokExe) {
        Write-Host "  [*] Launching Ngrok Permanent Tunnel (praising-cahoots-safely.ngrok-free.dev)..." -ForegroundColor Yellow
        Start-Process -FilePath $ngrokExe -ArgumentList "http 8000 --domain=praising-cahoots-safely.ngrok-free.dev" -WorkingDirectory $appDir -WindowStyle Hidden
    }
}

# 5. Wait for readiness
Write-Host "  [~] Verifying services readiness..." -ForegroundColor DarkGray
$ready = $false
for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Milliseconds 500
    if ((Test-Port 8000) -and (Test-Port 5173)) {
        $ready = $true
        break
    }
}

Write-Host ""
if ($ready) {
    Write-Host "[OK] All MJ Servers are READY!" -ForegroundColor Green
    Write-Host "   - Backend API:      http://localhost:8000" -ForegroundColor White
    Write-Host "   - Frontend App:     http://localhost:5173" -ForegroundColor White
    Write-Host "   - Avatar 3D (M1):   http://localhost:5174" -ForegroundColor White
    Write-Host "   - Ollama LLM:       http://localhost:11434" -ForegroundColor White
    Write-Host "   - Permanent Tunnel: https://praising-cahoots-safely.ngrok-free.dev" -ForegroundColor Cyan
    Write-Host "   - Phone Bridge WS:  wss://praising-cahoots-safely.ngrok-free.dev/ws/phone" -ForegroundColor Cyan
} else {
    Write-Host "[!] Servers launched. Still initializing in background." -ForegroundColor Yellow
}
Write-Host ""
