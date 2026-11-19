# Starts the Docker Compose deployment (primary) without rebuilding images.
# Idempotent; volumes and databases are preserved.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$Desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
Remove-Item (Join-Path $Root "var\docker-watchdog.disabled") -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $Docker)) { throw "Docker CLI not found. Install Docker Desktop first." }
Set-Location $Root

$engine = $false
for ($i = 1; $i -le 60; $i++) {
    $version = & $Docker info --format "{{.ServerVersion}}" 2>$null
    if ($LASTEXITCODE -eq 0 -and $version -match "^\d+\.\d+") { $engine = $true; break }
    if ($i -eq 1) {
        Write-Host "Starting Docker Desktop..." -ForegroundColor Cyan
        Start-Process explorer.exe -ArgumentList "`"$Desktop`"" | Out-Null
    }
    Start-Sleep -Seconds 5
}
if (-not $engine) { throw "Docker engine did not become ready. Open Docker Desktop and check WSL2." }
Write-Host "Docker engine ready ($version)." -ForegroundColor Green

Write-Host "Starting Compose services..." -ForegroundColor Cyan
& $Docker image inspect resolve-api:local *> $null
$apiImage = $LASTEXITCODE -eq 0
& $Docker image inspect resolve-web:local *> $null
$webImage = $LASTEXITCODE -eq 0
if (-not ($apiImage -and $webImage)) {
    Write-Host "Application images are missing; building them..." -ForegroundColor Yellow
    & $Docker compose --env-file .env build api web
    if ($LASTEXITCODE -ne 0) { throw "docker compose build failed" }
}
& $Docker compose --env-file .env --profile monitoring up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

function Wait-Http([string]$Url, [string]$Label, [int]$Attempts = 60) {
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                Write-Host "  $Label ready" -ForegroundColor Green
                return $true
            }
        } catch { }
        Start-Sleep -Seconds 3
    }
    Write-Host "  $Label did not become ready ($Url)" -ForegroundColor Red
    return $false
}

$apiOk = Wait-Http "http://127.0.0.1:8100/health/ready" "API"
$webOk = Wait-Http "https://127.0.0.1:8180/" "Web"

# Firewall: one application entry point, private LAN only.
$ruleName = "RESOLVE Docker Web (TCP 8180)"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8180 -Profile Private -RemoteAddress LocalSubnet | Out-Null
        Write-Host "Created firewall rule $ruleName" -ForegroundColor Green
    } else {
        Write-Warning "Firewall rule $ruleName is missing. Run scripts\install-windows-services.ps1 as Administrator or create it manually."
    }
}

$lanIp = (
    Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1
).IPv4Address.IPAddress
if (-not $lanIp) { $lanIp = "127.0.0.1" }

Write-Host ""
Write-Host "RESOLVE Docker deployment is ready" -ForegroundColor Green
Write-Host "  Windows:   https://localhost:8180"
Write-Host "  LAN:       https://${lanIp}:8180"
Write-Host "  API:       http://127.0.0.1:8100"
Write-Host "  Mailpit:   http://127.0.0.1:8125"
Write-Host "  n8n:       http://127.0.0.1:5679"
Write-Host "  Grafana:   http://127.0.0.1:3101"
Write-Host "  Prometheus:http://127.0.0.1:9190"
Write-Host ""
& $Docker compose --env-file .env ps

if (-not ($apiOk -and $webOk)) { exit 1 }
exit 0
