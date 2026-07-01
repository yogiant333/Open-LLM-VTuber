param(
    [string]$InstallRoot = "",
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 18080,
    [int]$UeWsPort = 10002,
    [string]$TtsHost = "0.0.0.0",
    [int]$TtsPort = 50005,
    [string]$LiveTalkingHost = "127.0.0.1",
    [int]$LiveTalkingPort = 18010,
    [string]$LiveTalkingAvatar = "xiaomeng_wav2lip256",
    [string]$LiveTalkingPython = "",
    [string]$FrontendHost = "0.0.0.0",
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"

function Resolve-InstallRoot {
    param([string]$Value)
    if ($Value) {
        return (Resolve-Path -LiteralPath $Value).Path
    }
    return $PSScriptRoot
}

function Invoke-HealthRequest {
    param([string]$Url)
    if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
        & curl.exe --noproxy "*" -s -f --max-time 3 $Url | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "curl failed: $Url"
        }
        return
    }
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Url | Out-Null
}

function Wait-Http {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Attempts = 120
    )
    for ($i = 1; $i -le $Attempts; $i++) {
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

$Root = Resolve-InstallRoot $InstallRoot
$ProjectDir = Join-Path $Root "Open-LLM-VTuber"
if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "run_server.py"))) {
    $ProjectDir = $Root
}

$TtsDir = Join-Path $Root "voxcpm2-nanovllm-win-venv"
if (-not (Test-Path -LiteralPath $TtsDir)) {
    $TtsDir = "C:\AI\voxcpm2-nanovllm-win-venv"
}

$LiveTalkingDir = Join-Path $Root "LiveTalking"
if (-not (Test-Path -LiteralPath $LiveTalkingDir)) {
    $LiveTalkingDir = "E:\AI\LiveTalking"
}

$FrontendDir = Join-Path $Root "frontend-runtime"
if (-not (Test-Path -LiteralPath $FrontendDir)) {
    $FrontendDir = Join-Path $ProjectDir "frontend-runtime"
}

$LogsDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

Write-Host "Install root: $Root"
Write-Host "Project:      $ProjectDir"
Write-Host "TTS:          $TtsDir"
Write-Host "LiveTalking:  $LiveTalkingDir"
Write-Host "Frontend:     $FrontendDir"
Write-Host ""

if (Test-Path -LiteralPath (Join-Path $LiveTalkingDir "scripts\start_xiaomeng.ps1")) {
    $liveArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $LiveTalkingDir "scripts\start_xiaomeng.ps1"),
        "-HostAddress", $LiveTalkingHost,
        "-Port", "$LiveTalkingPort"
    )
    if ($LiveTalkingPython) {
        $liveArgs += @("-Python", $LiveTalkingPython)
    }
    & powershell.exe @liveArgs
} else {
    $python = if ($LiveTalkingPython) { $LiveTalkingPython } else { Join-Path $LiveTalkingDir ".venv\Scripts\python.exe" }
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Missing LiveTalking Python: $python"
    }
    Start-Process -FilePath $python `
        -ArgumentList @(
            "app.py",
            "--transport", "webrtc",
            "--model", "wav2lip",
            "--avatar_id", $LiveTalkingAvatar,
            "--listenhost", $LiveTalkingHost,
            "--listenport", "$LiveTalkingPort",
            "--max_session", "1"
        ) `
        -WorkingDirectory $LiveTalkingDir `
        -RedirectStandardOutput (Join-Path $LogsDir "livetalking.out.log") `
        -RedirectStandardError (Join-Path $LogsDir "livetalking.err.log") `
        -WindowStyle Hidden | Out-Null
    Wait-Http "LiveTalking" "http://127.0.0.1:$LiveTalkingPort/api/admin/sessions" 90
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectDir "Start-Windows-TTS.ps1") `
    -TtsDir $TtsDir -TtsHost $TtsHost -TtsPort $TtsPort

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectDir "Start-Windows-Backend-Only.ps1") `
    -BindHost $BackendHost -BackendPort $BackendPort -UeWsPort $UeWsPort

$Node = Get-Command "node.exe" -ErrorAction SilentlyContinue
if (-not $Node) {
    throw "node.exe not found. Install Node.js or include it in PATH on the production device."
}

$FrontendLog = Join-Path $LogsDir "frontend-runtime.log"
$FrontendErr = Join-Path $LogsDir "frontend-runtime.err.log"
$FrontendPid = Join-Path $LogsDir "frontend-runtime.pid"
Remove-Item $FrontendLog, $FrontendErr, $FrontendPid -ErrorAction SilentlyContinue

$env:FRONTEND_HOST = $FrontendHost
$env:FRONTEND_PORT = [string]$FrontendPort
$env:FRONTEND_DIST = Join-Path $FrontendDir "dist"
$env:BACKEND_HOST = "127.0.0.1"
$env:BACKEND_PORT = [string]$BackendPort
$env:LIVETALKING_HOST = "127.0.0.1"
$env:LIVETALKING_PORT = [string]$LiveTalkingPort

$FrontendProcess = Start-Process -FilePath $Node.Source `
    -ArgumentList @((Join-Path $FrontendDir "server.js")) `
    -WorkingDirectory $FrontendDir `
    -RedirectStandardOutput $FrontendLog `
    -RedirectStandardError $FrontendErr `
    -WindowStyle Hidden `
    -PassThru

Set-Content -LiteralPath $FrontendPid -Value $FrontendProcess.Id -Encoding ascii
Wait-Http "Frontend" "http://127.0.0.1:$FrontendPort/health" 30

Write-Host ""
Write-Host "All services are ready."
Write-Host "Frontend:    http://127.0.0.1:$FrontendPort/"
Write-Host "Backend:     http://127.0.0.1:$BackendPort/"
Write-Host "LiveTalking: http://127.0.0.1:$LiveTalkingPort/"
Write-Host "TTS:         http://127.0.0.1:$TtsPort/health"
