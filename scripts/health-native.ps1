# Health check for the native RESOLVE stack. Exit code 0 = healthy.
# -Deep also performs a real Ollama generation request.

[CmdletBinding()]
param(
    [switch]$Deep
)

$ErrorActionPreference = "Continue"
$failures = New-Object System.Collections.Generic.List[string]

function Check-Http([string]$Label, [string]$Url, [scriptblock]$Validate) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
        $body = $response.Content
        if ($Validate) {
            $ok = & $Validate $body
        } else {
            $ok = $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
        }
        if ($ok) {
            Write-Host "[OK]   $Label" -ForegroundColor Green
        } else {
            Write-Host "[FAIL] $Label" -ForegroundColor Red
            $failures.Add($Label)
        }
    } catch {
        Write-Host "[FAIL] $Label ($($_.Exception.Message))" -ForegroundColor Red
        $failures.Add($Label)
    }
}

Write-Host "RESOLVE health check" -ForegroundColor White

Check-Http "API readiness" "http://127.0.0.1:8000/health/ready" {
    param($body)
    $json = $body | ConvertFrom-Json
    $json.status -eq "ready" -and $json.components.database.status -eq "ok" -and $json.components.storage.status -eq "ok"
}

Check-Http "Web frontend" "http://127.0.0.1:8090/" {
    param($body)
    $body -match "RESOLVE" -or $body -match "root"
}

Check-Http "Ollama" "http://127.0.0.1:11434/api/version" {
    param($body)
    ($body | ConvertFrom-Json).version -ne $null
}

Check-Http "Mailpit" "http://127.0.0.1:8025/api/v1/info" {
    param($body)
    $body -match "Version"
}

foreach ($name in @("resolvepgtest", "Memurai", "RESOLVE-API", "RESOLVE-Worker", "RESOLVE-Beat", "RESOLVE-Web", "RESOLVE-Ollama", "RESOLVE-Mailpit")) {
    $service = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq "Running") {
        Write-Host "[OK]   service $name" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] service $name" -ForegroundColor Red
        $failures.Add("service $name")
    }
}

$port = Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue
if ($port) {
    Write-Host "[OK]   Native localhost listener 8090" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Native localhost listener 8090" -ForegroundColor Red
    $failures.Add("LAN listener")
}

if ($Deep) {
    Write-Host "Deep AI generation test..." -ForegroundColor Cyan
    $payload = @{ model = "qwen2.5:7b-instruct"; stream = $false; messages = @(@{ role = "user"; content = "Reply with the single word OK" }); options = @{ temperature = 0 } } | ConvertTo-Json -Depth 5
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method POST -Body $payload -ContentType "application/json" -TimeoutSec 180
        if ($response.message.content) {
            Write-Host "[OK]   Ollama generated a response" -ForegroundColor Green
        } else {
            Write-Host "[FAIL] Ollama returned no content" -ForegroundColor Red
            $failures.Add("AI generation")
        }
    } catch {
        Write-Host "[FAIL] AI generation ($($_.Exception.Message))" -ForegroundColor Red
        $failures.Add("AI generation")
    }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "RESOLVE is healthy." -ForegroundColor Green
    exit 0
}
Write-Host "RESOLVE has $($failures.Count) failing checks." -ForegroundColor Red
exit 1
