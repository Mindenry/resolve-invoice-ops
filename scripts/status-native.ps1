# Reports the real state of the native RESOLVE stack.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root "apps\api"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pgsql = "C:\Program Files\PostgreSQL\18\bin"

function Port-State([int]$Port) {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) {
        $owner = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        return "listening ($($connection.LocalAddress)) pid=$($connection.OwningProcess) $($owner.ProcessName)"
    }
    return "not listening"
}

function Http-State([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return "$($response.StatusCode) $($response.StatusDescription)"
    } catch {
        return "unreachable: $($_.Exception.Message)"
    }
}

Write-Host "RESOLVE status" -ForegroundColor White
Get-Service RESOLVE-*, resolvepgtest, Memurai -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType |
    Format-Table -AutoSize

Write-Host "Ports" -ForegroundColor Cyan
foreach ($port in @(8000, 8090, 55432, 6379, 11434, 1025, 8025)) {
    "  {0,-6} {1}" -f $port, (Port-State $port)
}

Write-Host "HTTP" -ForegroundColor Cyan
"  API      {0}" -f (Http-State "http://127.0.0.1:8000/health/ready")
"  Web      {0}" -f (Http-State "http://127.0.0.1:8090/")
"  Health   {0}" -f (Http-State "http://127.0.0.1:8090/health")
"  Ollama   {0}" -f (Http-State "http://127.0.0.1:11434/api/version")
"  Mailpit  {0}" -f (Http-State "http://127.0.0.1:8025/api/v1/info")

Write-Host "AI models" -ForegroundColor Cyan
$ollama = "C:\Users\Administrator\AppData\Local\Programs\Ollama\ollama.exe"
if (Test-Path $ollama) { & $ollama list }

if (Test-Path $Python) {
    Write-Host "Database" -ForegroundColor Cyan
    $databaseUrl = Get-Content (Join-Path $ApiDir ".env") |
        Where-Object { $_ -match "^DATABASE_URL=" } |
        Select-Object -First 1
    if ($databaseUrl) {
        $env:DATABASE_URL = ($databaseUrl -split "=", 2)[1].Trim()
        Push-Location $ApiDir
        try {
            & $Python -c "from sqlalchemy import text; from app.db.session import engine; c=engine.connect(); print('  organizations', c.execute(text('select count(*) from organizations')).scalar()); print('  invoices', c.execute(text('select count(*) from invoices')).scalar()); print('  cases', c.execute(text('select count(*) from cases')).scalar()); print('  documents', c.execute(text('select count(*) from documents')).scalar()); print('  chunks', c.execute(text('select count(*) from document_chunks')).scalar()); print('  vector rows', c.execute(text('select count(embedding_vec) from document_chunks')).scalar()); c.close()"
        } catch {
            Write-Host "  database query failed: $($_.Exception.Message)" -ForegroundColor Red
        } finally {
            Pop-Location
        }
    }

    Write-Host "Local rollback (not LAN)" -ForegroundColor Cyan
    $lanIp = (
        Get-NetIPConfiguration |
            Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" } |
            Select-Object -First 1
    ).IPv4Address.IPAddress
    "  http://localhost:8090"
}
