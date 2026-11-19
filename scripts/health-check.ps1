# Health check for the primary Docker deployment, with native fallback support.
# Exit code 0 means the primary stack is healthy.

[CmdletBinding()]
param(
    [switch]$Deep,
    [switch]$Native
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$failures = New-Object System.Collections.Generic.List[string]

if ($Native) {
    & (Join-Path $PSScriptRoot "health-native.ps1") -Deep:$Deep
    exit $LASTEXITCODE
}

function Check([string]$Label, [scriptblock]$Test) {
    try {
        $ok = & $Test
        if ($ok) {
            Write-Host "[OK]   $Label" -ForegroundColor Green
            return
        }
    } catch { }
    Write-Host "[FAIL] $Label" -ForegroundColor Red
    $failures.Add($Label)
}

Write-Host "RESOLVE Docker health check" -ForegroundColor White

Check "Docker engine" {
    $v = & $Docker info --format "{{.ServerVersion}}" 2>$null
    $LASTEXITCODE -eq 0 -and $v -match "^\d+\.\d+"
}

$required = @("api", "worker", "beat", "web", "postgres", "redis", "seaweedfs", "mailpit")

# Containers with healthchecks can still be "starting" right after a restart.
for ($attempt = 1; $attempt -le 30; $attempt++) {
    $waiting = $false
    foreach ($service in $required) {
        $id = & $Docker compose ps -q $service 2>$null
        if (-not $id) { $waiting = $true; continue }
        $state = & $Docker inspect $id --format "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" 2>$null
        if ($state -notmatch "^(running)\|(healthy|none)$") { $waiting = $true }
    }
    if (-not $waiting) { break }
    Start-Sleep -Seconds 2
}

$states = @{}
foreach ($service in $required) {
    $id = & $Docker compose ps -q $service 2>$null
    if ($id) {
        $states[$service] = (& $Docker inspect $id --format "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" 2>$null)
    } else {
        $states[$service] = "missing|none"
    }
}
foreach ($service in $required) {
    Check "container $service" { $states[$service] -match "^(running)\|(healthy|none)$" }
}

Check "API readiness (DB/storage/Redis/AI)" {
    $body = Invoke-RestMethod -Uri "http://127.0.0.1:8100/health/ready" -TimeoutSec 10
    $body.status -eq "ready" -and $body.components.database.status -eq "ok" -and $body.components.storage.status -eq "ok" -and $body.components.redis.status -eq "ok"
}

Check "Web frontend" {
    (Invoke-WebRequest -Uri "https://127.0.0.1:8180/" -UseBasicParsing -TimeoutSec 8).StatusCode -eq 200
}

Check "Container can reach Ollama" {
    $version = & $Docker compose exec -T api curl -sS --max-time 8 http://host.docker.internal:11434/api/version 2>$null
    $LASTEXITCODE -eq 0 -and $version -match "version"
}

Check "PostgreSQL pgvector extension" {
    $value = & $Docker compose exec -T postgres psql -U resolve -d resolve -t -A -c "select extversion from pg_extension where extname='vector'" 2>$null
    $value -match "^\d+\.\d+"
}

Check "Vector rows and HNSW index" {
    $counts = & $Docker compose exec -T postgres psql -U resolve -d resolve -t -A -F ":" -c "select count(1), count(embedding_vec) from document_chunks" 2>$null
    $index = & $Docker compose exec -T postgres psql -U resolve -d resolve -t -A -c "select count(1) from pg_indexes where tablename='document_chunks' and indexname='ix_document_chunks_embedding_vec'" 2>$null
    $counts -match "^\d+:\d+$" -and $index.Trim() -eq "1"
}

Check "n8n" {
    (Invoke-WebRequest -Uri "http://127.0.0.1:5679/healthz" -UseBasicParsing -TimeoutSec 8).StatusCode -eq 200
}

Check "Mailpit" {
    (Invoke-WebRequest -Uri "http://127.0.0.1:8125/api/v1/info" -UseBasicParsing -TimeoutSec 8).StatusCode -eq 200
}

$rule = Get-NetFirewallRule -DisplayName "RESOLVE Docker Web (TCP 8180)" -ErrorAction SilentlyContinue
Check "Firewall 8180 (Private, LocalSubnet)" {
    $rule -and $rule.Enabled -eq "True" -and $rule.Profile -match "Private"
}

if ($Deep) {
    Write-Host "Deep AI generation test..." -ForegroundColor Cyan
    $payload = @{ model = "qwen2.5:7b-instruct"; stream = $false; messages = @(@{ role = "user"; content = "Reply with the single word OK" }); options = @{ temperature = 0 } } | ConvertTo-Json -Depth 5
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method POST -Body $payload -ContentType "application/json" -TimeoutSec 180
        if ($response.message.content) {
            Write-Host "[OK]   Ollama generation" -ForegroundColor Green
        } else {
            Write-Host "[FAIL] Ollama returned no content" -ForegroundColor Red
            $failures.Add("AI generation")
        }
    } catch {
        Write-Host "[FAIL] Ollama generation ($($_.Exception.Message))" -ForegroundColor Red
        $failures.Add("AI generation")
    }
}

$lanIp = (
    Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1
).IPv4Address.IPAddress

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "RESOLVE Docker deployment is healthy." -ForegroundColor Green
    Write-Host "  Windows: https://localhost:8180"
    Write-Host "  LAN:     https://${lanIp}:8180"
    exit 0
}
Write-Host "RESOLVE Docker deployment has $($failures.Count) failing checks." -ForegroundColor Red
exit 1
