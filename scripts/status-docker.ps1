# Reports Docker Compose status and the actual endpoints.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
Set-Location $Root

Write-Host "Docker engine" -ForegroundColor Cyan
$version = & $Docker info --format "{{.ServerVersion}} | {{.OperatingSystem}} | {{.Driver}}" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "  $version" -ForegroundColor Green } else { Write-Host "  not running" -ForegroundColor Red }

Write-Host "Containers" -ForegroundColor Cyan
& $Docker compose --env-file .env --profile monitoring ps

Write-Host "HTTP" -ForegroundColor Cyan
foreach ($item in @(
    @("Web", "https://127.0.0.1:8180/"),
    @("Health", "https://127.0.0.1:8180/health"),
    @("API readiness", "http://127.0.0.1:8100/health/ready"),
    @("Mailpit", "http://127.0.0.1:8125/api/v1/info"),
    @("n8n", "http://127.0.0.1:5679/healthz"),
    @("Prometheus", "http://127.0.0.1:9190/-/healthy"),
    @("Grafana", "http://127.0.0.1:3101/api/health")
)) {
    try {
        $response = Invoke-WebRequest -Uri $item[1] -UseBasicParsing -TimeoutSec 5
        "  {0,-14} {1}" -f $item[0], $response.StatusCode
    } catch {
        "  {0,-14} unreachable" -f $item[0]
    }
}

$lanIp = (
    Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1
).IPv4Address.IPAddress
Write-Host "LAN" -ForegroundColor Cyan
Write-Host "  https://${lanIp}:8180"

Write-Host "Volumes" -ForegroundColor Cyan
& $Docker volume ls --format "  {{.Name}}" | Select-String -Pattern "resolve_"
