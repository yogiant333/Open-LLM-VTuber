param(
    [string]$TtsDir = "C:\AI\voxcpm2-nanovllm-win-venv",
    [string]$TtsHost = "127.0.0.1",
    [int]$TtsPort = 50005,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"

function Stop-Listener {
    param(
        [int[]]$Ports,
        [string]$Label
    )

    $owners = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($ownerPid in $owners) {
        if ($ownerPid -and $ownerPid -gt 4) {
            try {
                Stop-Process -Id $ownerPid -Force -ErrorAction Stop
                Write-Host "Stopped $Label PID $ownerPid"
            } catch {
                Write-Host "Could not stop $Label PID ${ownerPid}: $($_.Exception.Message)"
            }
        }
    }
}

function Invoke-HealthRequest {
    param([string]$Url)

    if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
        $content = & curl.exe --noproxy "*" -s -f --max-time 2 $Url
        if ($LASTEXITCODE -ne 0) {
            throw "curl health request failed: $Url"
        }
        return [pscustomobject]@{
            Content = ($content -join "`n")
        }
    }

    return Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $Url
}

function Wait-Http {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Attempts = 180,
        [System.Diagnostics.Process]$Process = $null,
        [string]$StdoutLog = $null,
        [string]$StderrLog = $null
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        if ($Process -and $Process.HasExited) {
            Start-Sleep -Milliseconds 500
            Write-Host "$Name process exited early with code $($Process.ExitCode)."
            if ($StdoutLog -and (Test-Path -LiteralPath $StdoutLog)) {
                Write-Host ""
                Write-Host "$Name stdout:"
                Get-Content -LiteralPath $StdoutLog -Tail 80
            }
            if ($StderrLog -and (Test-Path -LiteralPath $StderrLog)) {
                Write-Host ""
                Write-Host "$Name stderr:"
                Get-Content -LiteralPath $StderrLog -Tail 80
            }
            throw "$Name process exited before becoming ready: $Url"
        }

        try {
            $response = Invoke-HealthRequest -Url $Url
            Write-Host "$Name ready: $Url"
            return $response
        } catch {
            if (($i % 10) -eq 0) {
                Write-Host "waiting $Name ($i/$Attempts): $Url"
            }
            Start-Sleep -Seconds 2
        }
    }

    throw "$Name did not become ready: $Url"
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logsDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$ttsScript = Join-Path $TtsDir "Start-VoxCPM2-NanoVLLM-Windows.ps1"
if (-not (Test-Path -LiteralPath $ttsScript)) {
    throw "Missing Windows TTS starter: $ttsScript"
}

$ttsHealthUrl = "http://127.0.0.1:${TtsPort}/health"
$ttsLog = Join-Path $logsDir "voxcpm2-windows.log"
$ttsErr = Join-Path $logsDir "voxcpm2-windows.err.log"
Remove-Item $ttsLog, $ttsErr -ErrorAction SilentlyContinue

Write-Host "Starting Windows VoxCPM2 NanoVLLM TTS"
Write-Host "TTS dir: $TtsDir"
Write-Host "Bind:    $TtsHost"
Write-Host "TTS:     $ttsHealthUrl"
Write-Host ""

Stop-Listener -Ports @($TtsPort) -Label "Windows VoxCPM2 TTS"

$ttsProcess = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ttsScript, "-HostName", $TtsHost, "-Port", $TtsPort) `
    -WorkingDirectory $TtsDir `
    -RedirectStandardOutput $ttsLog `
    -RedirectStandardError $ttsErr `
    -WindowStyle Hidden `
    -PassThru

if ($NoWait) {
    Write-Host "TTS launch requested. Skipped health wait."
    Write-Host "PID:  $($ttsProcess.Id)"
    Write-Host "Logs: $ttsErr"
    exit 0
}

$ttsResponse = Wait-Http "Windows VoxCPM2 TTS" $ttsHealthUrl 180 -Process $ttsProcess -StdoutLog $ttsLog -StderrLog $ttsErr

Write-Host ""
Write-Host "TTS service is ready."
Write-Host "TTS:      $ttsHealthUrl"
Write-Host "TTS info: $($ttsResponse.Content)"
Write-Host "PID:      $($ttsProcess.Id)"
Write-Host "Logs:     $ttsErr"

exit 0
