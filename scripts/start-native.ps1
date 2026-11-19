# RESOLVE native stack control (Windows).
# Starts isolated PostgreSQL (55432), Redis/Memurai, Ollama, Mailpit, API, worker,
# beat and the nginx LAN frontend on 0.0.0.0:8090. Safe to run repeatedly.

[CmdletBinding()]
param(
    [switch]$SkipMigrations,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root "apps\api"
$WebDir = Join-Path $Root "apps\web"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pgsql = "C:\Program Files\PostgreSQL\18\bin"
$Nssm = "C:\ProgramData\chocolatey\bin\nssm.exe"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

if (-not (Test-Admin)) {
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($SkipMigrations) { $arguments += "-SkipMigrations" }
    if ($NoRestart) { $arguments += "-NoRestart" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments | Out-Null
    Write-Host "RESOLVE needs administrator rights to control services. Accept the UAC prompt." -ForegroundColor Yellow
    exit 0
}

function Ensure-Service([string]$Name) {
    $service = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $service) {
        throw "Required service '$Name' is not installed."
    }
    if ($service.Status -ne "Running") {
        Write-Host "Starting $Name..." -ForegroundColor Cyan
        Start-Service -Name $Name
        $service.WaitForStatus("Running", [TimeSpan]::FromSeconds(60))
    }
}

function Wait-Http([string]$Url, [string]$Label, [int]$Attempts = 45) {
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                Write-Host "  $Label ready ($($response.StatusCode))" -ForegroundColor Green
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    Write-Host "  $Label did not become ready: $Url" -ForegroundColor Red
    return $false
}

function Read-EnvValue([string]$Key) {
    $line = Get-Content (Join-Path $ApiDir ".env") -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^$([regex]::Escape($Key))=" } |
        Select-Object -First 1
    if ($line) { return ($line -split "=", 2)[1].Trim() }
    return $null
}

Write-Host "RESOLVE start" -ForegroundColor White
Write-Host "Repository: $Root"

# Infrastructure services installed on this machine.
Ensure-Service "resolvepgtest"   # isolated PostgreSQL 18.6 on 127.0.0.1:55432
Ensure-Service "Memurai"         # Redis-compatible broker on 127.0.0.1:6379
Ensure-Service "RESOLVE-Ollama"
Ensure-Service "RESOLVE-Mailpit"

if (-not (Test-Path $Python)) { throw "Python virtualenv not found at $Python" }

$databaseUrl = Read-EnvValue "DATABASE_URL"
$embeddingDim = Read-EnvValue "AI_EMBEDDING_DIM"
if ($databaseUrl) { $env:DATABASE_URL = $databaseUrl }
if ($embeddingDim) { $env:AI_EMBEDDING_DIM = $embeddingDim }
$env:ENV = "development"

if (-not $SkipMigrations) {
    Write-Host "Applying database migrations..." -ForegroundColor Cyan
    $migrationLog = Join-Path $env:TEMP "resolve-migrate.log"
    $migrationErr = Join-Path $env:TEMP "resolve-migrate.err.log"
    $process = Start-Process -FilePath $Python -ArgumentList @("-m", "alembic", "upgrade", "head") -WorkingDirectory $ApiDir -Wait -PassThru -NoNewWindow -RedirectStandardOutput $migrationLog -RedirectStandardError $migrationErr
    Get-Content $migrationLog -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
    Get-Content $migrationErr -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
    if ($process.ExitCode -ne 0) { throw "Alembic migration failed with exit code $($process.ExitCode)" }
}

# Restart application services so they load the current code/config.
foreach ($name in @("RESOLVE-API", "RESOLVE-Worker", "RESOLVE-Beat", "RESOLVE-Web")) {
    $service = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $service) { throw "Required service '$name' is not installed." }
    if ($NoRestart -and $service.Status -eq "Running") { continue }
    if ($service.Status -eq "Running") {
        Write-Host "Restarting $name..." -ForegroundColor Cyan
        Restart-Service -Name $name
    } else {
        Write-Host "Starting $name..." -ForegroundColor Cyan
        Start-Service -Name $name
    }
    $service.WaitForStatus("Running", [TimeSpan]::FromSeconds(60))
}

Write-Host "Waiting for HTTP endpoints..." -ForegroundColor Cyan
$apiOk = Wait-Http "http://127.0.0.1:8000/health/ready" "API"
$webOk = Wait-Http "http://127.0.0.1:8090/" "Web"

$lanIp = (
    Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1
).IPv4Address.IPAddress
if (-not $lanIp) { $lanIp = "127.0.0.1" }

Write-Host ""
Write-Host "RESOLVE is ready" -ForegroundColor Green
Write-Host "  Windows:  http://localhost:8090"
Write-Host "  LAN:      http://${lanIp}:8090"
Write-Host "  Health:   http://${lanIp}:8090/health"
Write-Host "  API docs: http://localhost:8090/docs  (local only)"
Write-Host "  Demo:     admin@example.com (password in var\secrets\demo-credentials.txt)"
Write-Host ""
Get-Service RESOLVE-*, resolvepgtest, Memurai |
    Select-Object Name, Status |
    Format-Table -AutoSize

if (-not ($apiOk -and $webOk)) { exit 1 }
exit 0
