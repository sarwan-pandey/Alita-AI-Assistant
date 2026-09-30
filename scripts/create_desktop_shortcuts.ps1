$WshShell = New-Object -ComObject WScript.Shell
$desktopDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
$appDir = "c:\Users\sarwa\Desktop\aura-assistant"

$shortcutAPath = Join-Path $desktopDir "Start MJ Servers.lnk"
$shortcutA = $WshShell.CreateShortcut($shortcutAPath)
$shortcutA.TargetPath = "wscript.exe"
$shortcutA.Arguments = "`"$appDir\Start-Alita-Servers.vbs`""
$shortcutA.WorkingDirectory = $appDir
$shortcutA.Description = "Start MJ AI Assistant Servers"
$shortcutA.IconLocation = "C:\Windows\System32\imageres.dll, 102"
$shortcutA.Save()
Write-Host "Created Shortcut A: $shortcutAPath"

$shortcutBPath = Join-Path $desktopDir "MJ AI Assistant.lnk"
$shortcutB = $WshShell.CreateShortcut($shortcutBPath)
$shortcutB.TargetPath = "wscript.exe"
$shortcutB.Arguments = "`"$appDir\Open-Alita-App.vbs`""
$shortcutB.WorkingDirectory = $appDir
$shortcutB.Description = "Open MJ AI Assistant App"
$shortcutB.IconLocation = "C:\Windows\System32\shell32.dll, 14"
$shortcutB.Save()
Write-Host "Created Shortcut B: $shortcutBPath"
