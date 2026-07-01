param(
    [int]$FrontendPort = 3000,
    [int]$LiveTalkingPort = 18010,
    [int]$BackendPort = 18080,
    [int]$TtsPort = 50005
)

$ErrorActionPreference = "Stop"

function Test-Http {
    param([string]$Name, [string]$Url)

    try {
        if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
            & curl.exe --noproxy "*" -s -f --max-time 3 $Url | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "curl exited with $LASTEXITCODE"
            }
        } else {
            Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Url | Out-Null
        }
        Write-Host "[OK]   $Name $Url"
        return $true
    } catch {
        Write-Host "[FAIL] $Name $Url :: $($_.Exception.Message)"
        return $false
    }
}

$ok = $true
$ok = (Test-Http "Frontend" "http://127.0.0.1:$FrontendPort/health") -and $ok
$ok = (Test-Http "Backend" "http://127.0.0.1:$BackendPort/") -and $ok
$ok = (Test-Http "TTS" "http://127.0.0.1:$TtsPort/health") -and $ok
$ok = (Test-Http "LiveTalking" "http://127.0.0.1:$LiveTalkingPort/api/admin/sessions") -and $ok

if (-not $ok) {
    exit 1
}

Write-Host "All health checks passed."
