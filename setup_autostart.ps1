# PowerShell Autostart Installer / Uninstaller for Alita Jarvis Assistant
param (
    [switch]$Uninstall
)

$sourceVbs = "c:\Users\sarwa\Desktop\aura-assistant\JarvisLauncher.vbs"
$startupFolder = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$targetFile = "$startupFolder\AlitaJarvisBoot.vbs"

if ($Uninstall) {
    if (Test-Path $targetFile) {
        Remove-Item $targetFile -Force
        Write-Host "Alita removed from Windows Startup." -ForegroundColor Yellow
    } else {
        Write-Host "Alita was not found in Windows Startup." -ForegroundColor Gray
    }
    exit 0
}

if (-not (Test-Path $sourceVbs)) {
    Write-Error "Source launcher not found: $sourceVbs"
    exit 1
}

Copy-Item -Path $sourceVbs -Destination $targetFile -Force
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host "Alita Jarvis AI Assistant successfully installed to Startup!" -ForegroundColor Green
Write-Host "Location: $targetFile" -ForegroundColor Gray
Write-Host "Alita will launch silently on Windows boot as a desktop HUD." -ForegroundColor White
Write-Host "===============================================================" -ForegroundColor Cyan
