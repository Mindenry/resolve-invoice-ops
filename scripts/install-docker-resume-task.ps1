# Registers the Docker Desktop and post-reboot tasks. Docker Desktop is launched
# through Explorer so it survives the task process exiting.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$resumeScript = Join-Path $Root "scripts\resume-after-reboot.ps1"

$desktopAction = New-ScheduledTaskAction -Execute "explorer.exe" -Argument "`"$dockerDesktop`""
$desktopTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$desktopPrincipal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$desktopSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "RESOLVE-Docker-Desktop" -Action $desktopAction -Trigger $desktopTrigger -Principal $desktopPrincipal -Settings $desktopSettings -Force | Out-Null

$argument = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $resumeScript + '"'
$resumeAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$resumeTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$resumeTrigger.Delay = "PT1M"
Register-ScheduledTask -TaskName "RESOLVE-PostReboot-Docker" -Action $resumeAction -Trigger $resumeTrigger -Principal $desktopPrincipal -Settings $desktopSettings -Force | Out-Null

Write-Host "Registered RESOLVE-Docker-Desktop and RESOLVE-PostReboot-Docker."
