param(
    [string]$BindHost = "127.0.0.1",
    [int]$BackendPort = 18080,
    [int]$UeWsPort = 10002,
    [switch]$VerboseLog
)

$ErrorActionPreference = "Stop"

function Stop-ProcessTree {
    param(
        [int]$ProcessId,
        [string]$Label
    )

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId) -Label $Label
    }

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        Write-Host "Stopped $Label PID $ProcessId ($($process.ProcessName))"
    } catch {
        # The process may already have exited.
    }
}

function Stop-RecordedProcessTree {
    param(
        [string]$PidPath,
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $PidPath)) {
        return
    }

    $recordedPid = Get-Content -LiteralPath $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    if ($recordedPid -match '^\d+$') {
        Stop-ProcessTree -ProcessId ([int]$recordedPid) -Label $Label
    }
}

function Stop-Listener {
    param(
        [int[]]$Ports,
        [string]$Label
    )

    $owners = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($ownerPid in $owners) {
        if ($ownerPid -and $ownerPid -ne 0) {
            try {
                Stop-ProcessTree -ProcessId ([int]$ownerPid) -Label $Label
            } catch {
                Write-Host "Could not stop $Label PID ${ownerPid}: $($_.Exception.Message)"
            }
        }
    }
}

function Invoke-HealthRequest {
    param([string]$Url)

    if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
        & curl.exe --noproxy "*" -s -f --max-time 2 $Url | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "curl health request failed: $Url"
        }
        return
    }

    Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $Url | Out-Null
}

function Wait-Http {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Attempts = 90,
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
            Invoke-HealthRequest -Url $Url
            Write-Host "$Name ready: $Url"
            return
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

$backendPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $backendPython)) {
    throw "Missing backend Python: $backendPython"
}

$backendPid = Join-Path $logsDir "backend-only-windows.pid"
$backendLog = Join-Path $logsDir "backend-only-windows.log"
$backendErr = Join-Path $logsDir "backend-only-windows.err.log"
Remove-Item $backendLog, $backendErr -ErrorAction SilentlyContinue

Stop-RecordedProcessTree -PidPath $backendPid -Label "Open-LLM-VTuber backend"
Stop-Listener -Ports @($BackendPort, $UeWsPort) -Label "Open-LLM-VTuber backend"

$waitHost = $BindHost
if ($waitHost -eq "0.0.0.0" -or $waitHost -eq "::") {
    $waitHost = "127.0.0.1"
}
$backendUrl = "http://${waitHost}:${BackendPort}/"

Write-Host "Starting Open-LLM-VTuber backend only"
Write-Host "Project: $root"
Write-Host "Backend: http://${BindHost}:${BackendPort}/"
Write-Host "UE WS:   ws://${BindHost}:${UeWsPort}"
Write-Host "TTS:     edge_tts from conf.yaml"
Write-Host ""

$args = @("-m", "uvicorn", "run_server:create_app", "--factory", "--host", $BindHost, "--port", $BackendPort)
if ($VerboseLog) {
    $args += @("--log-level", "debug")
}

$backendProcess = Start-Process -FilePath $backendPython `
    -ArgumentList $args `
    -WorkingDirectory $root `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError $backendErr `
    -WindowStyle Hidden `
    -PassThru
Set-Content -LiteralPath $backendPid -Value $backendProcess.Id -Encoding ascii

try {
    Wait-Http "Backend" $backendUrl 90 -Process $backendProcess -StdoutLog $backendLog -StderrLog $backendErr
} catch {
    if (-not $backendProcess.HasExited) {
        Stop-ProcessTree -ProcessId $backendProcess.Id -Label "Open-LLM-VTuber backend"
    }
    Remove-Item -LiteralPath $backendPid -Force -ErrorAction SilentlyContinue
    throw
}

Write-Host ""
Write-Host "Backend service is ready."
Write-Host "Backend: $backendUrl"
Write-Host "UE WS:   ws://${waitHost}:${UeWsPort}"
Write-Host "Logs:"
Write-Host "  $backendLog"
Write-Host "  $backendErr"
