# Installs/updates the verified native RESOLVE Windows services and firewall rule.
# Run as Administrator. Existing databases, documents and volumes are not touched.

[CmdletBinding()]
param([switch]$NoStart)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ServiceDir = "C:\ProgramData\RESOLVE\service"
$Nssm = "C:\ProgramData\chocolatey\bin\nssm.exe"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"") | Out-Null
    Write-Host "Accept the UAC prompt to install the services."
    exit 0
}

if (-not (Test-Path $Nssm)) { throw "NSSM is required. Install it with: choco install nssm -y" }
if (-not (Test-Path $Python)) { throw "Python virtualenv not found: $Python" }

New-Item -ItemType Directory -Force -Path $ServiceDir, (Join-Path $Root "var\logs"), (Join-Path $Root "var\nginx") | Out-Null
Copy-Item (Join-Path $Root "scripts\service\*.cmd") $ServiceDir -Force

$services = @(
    @{ Name = "RESOLVE-API"; Command = "run-api.cmd" },
    @{ Name = "RESOLVE-Worker"; Command = "run-worker.cmd" },
    @{ Name = "RESOLVE-Beat"; Command = "run-beat.cmd" },
    @{ Name = "RESOLVE-Web"; Command = "run-web.cmd" },
    @{ Name = "RESOLVE-Ollama"; Command = "run-ollama.cmd" },
    @{ Name = "RESOLVE-Mailpit"; Command = "run-mailpit.cmd" }
)

foreach ($service in $services) {
    $name = $service.Name
    $existing = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $existing) {
        & $Nssm install $name "C:\Windows\System32\cmd.exe" "/c $ServiceDir\$($service.Command)"
    }
    & $Nssm set $name AppParameters "/c $ServiceDir\$($service.Command)"
    & $Nssm set $name AppDirectory $Root
    & $Nssm set $name Start SERVICE_AUTO_START
    & $Nssm set $name AppExit Default Restart
    & $Nssm set $name AppRestartDelay 5000
    & $Nssm set $name AppStdout (Join-Path $Root "var\logs\$name.out.log")
    & $Nssm set $name AppStderr (Join-Path $Root "var\logs\$name.err.log")
    & $Nssm set $name AppRotateFiles 1
    & $Nssm set $name AppRotateOnline 1
    & $Nssm set $name AppRotateBytes 10485760
    Write-Host "Configured $name" -ForegroundColor Green
}

# Firewall: one port, private profile, local subnet only.
$ruleName = "RESOLVE LAN Web (TCP 8090)"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8090 -Profile Private -RemoteAddress LocalSubnet | Out-Null
    Write-Host "Created firewall rule $ruleName" -ForegroundColor Green
}

# Ollama models must be readable by the LocalSystem service account.
$ollamaModels = "C:\Users\Administrator\.ollama"
if (Test-Path $ollamaModels) { & icacls $ollamaModels /grant "SYSTEM:(OI)(CI)R" /T | Out-Null }

if (-not $NoStart) { & (Join-Path $Root "scripts\start-resolve.ps1") }
