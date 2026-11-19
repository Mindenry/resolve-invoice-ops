# Runs after the required Windows reboot to finish the Docker/WSL2 path.
# Docker Desktop is launched through Explorer so it is not tied to this task's
# process tree. The native services are not touched; Compose uses separate ports.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "var\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "post-reboot-docker.log"

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

Write-Log "Post-reboot Docker resume started."

if (Test-Path (Join-Path $Root "var\docker-resume.disabled")) {
    Write-Log "Disabled by var\docker-resume.disabled; exiting."
    exit 0
}

$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
if (-not (Test-Path $docker)) {
    Write-Log "Docker CLI not found at $docker."
    exit 1
}

Write-Log "Updating WSL2..."
& wsl.exe --update 2>&1 | ForEach-Object { Write-Log "wsl: $_" }
& wsl.exe --set-default-version 2 2>&1 | ForEach-Object { Write-Log "wsl: $_" }

$engine = $false
for ($i = 1; $i -le 60; $i++) {
    $version = & $docker info --format "{{.ServerVersion}}" 2>$null
    if ($LASTEXITCODE -eq 0 -and $version -match "^\d+\.\d+") {
        $engine = $true
        Write-Log "Docker engine ready ($version)."
        break
    }
    if ($i -eq 1 -and (Test-Path $desktop)) {
        Write-Log "Starting Docker Desktop through Explorer..."
        Start-Process explorer.exe -ArgumentList "`"$desktop`"" | Out-Null
    }
    Start-Sleep -Seconds 5
}
if (-not $engine) {
    Write-Log "Docker engine did not become ready. Open Docker Desktop and inspect its diagnostics."
    exit 1
}

Push-Location $Root
try {
    Write-Log "Starting the Compose stack..."
    & $docker compose --env-file .env --profile monitoring up -d 2>&1 | ForEach-Object { Write-Log "compose: $_" }
    & $docker compose --env-file .env ps 2>&1 | ForEach-Object { Write-Log "compose: $_" }

    $healthy = $false
    for ($i = 1; $i -le 60; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "https://127.0.0.1:8180/" -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { $healthy = $true; break }
        } catch { }
        Start-Sleep -Seconds 5
    }
    if ($healthy) {
        Write-Log "Docker Compose stack is healthy at https://127.0.0.1:8180"
        Write-Log "LAN URL: https://<host-LAN-IP>:8180 (Private-profile firewall rule required)."
    } else {
        Write-Log "Compose started but the web health check failed. Inspect: docker compose logs api web worker"
    }
} finally {
    Pop-Location
}
