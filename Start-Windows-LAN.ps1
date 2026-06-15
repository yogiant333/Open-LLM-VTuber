param(
    [string]$PublicIp = "10.0.2.155",
    [string]$BindHost = "0.0.0.0",
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 18080,
    [string]$TtsWslDir = "/mnt/d/AI/fay",
    [int]$TtsPort = 50005
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

function Convert-ToWslPath {
    param([string]$WindowsPath)
    $converted = & wsl.exe wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($converted)) {
        throw "Failed to convert Windows path to WSL path: $WindowsPath"
    }
    return $converted.Trim()
}

function Wait-Http {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Attempts = 150
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $Url | Out-Null
            Write-Host "$Name ready: $Url"
            return
        } catch {
            Write-Host "waiting $Name ($i/$Attempts): $Url"
            Start-Sleep -Seconds 2
        }
    }

    throw "$Name did not become ready: $Url"
}

Require-Command "wsl.exe"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$wslRoot = Convert-ToWslPath $root

$backendUrl = "http://${PublicIp}:${BackendPort}/"
$frontendUrl = "http://${PublicIp}:${FrontendPort}/"
$ttsUrl = "http://${PublicIp}:${TtsPort}/"
$ttsHealthUrl = "http://${PublicIp}:${TtsPort}/health"

Write-Host "Starting Open-LLM-VTuber for LAN access"
Write-Host "Project:  $wslRoot"
Write-Host "Bind:     $BindHost"
Write-Host "Frontend: $frontendUrl"
Write-Host "Backend:  $backendUrl"
Write-Host "TTS:      $ttsUrl"
Write-Host ""

$wslCommand = @"
set -e
tmux kill-session -t open-llm-vtuber 2>/dev/null || true
tmux kill-session -t open-llm-vtuber-frontend 2>/dev/null || true
tmux kill-session -t voxcpm2-nanovllm 2>/dev/null || true
tmux new-session -d -s open-llm-vtuber "cd '$wslRoot' && uv run uvicorn run_server:create_app --factory --host $BindHost --port $BackendPort"
tmux new-session -d -s open-llm-vtuber-frontend "cd '$wslRoot/frontend' && npm run dev:web -- --host $BindHost --force"
tmux new-session -d -s voxcpm2-nanovllm "cd '$TtsWslDir' && VOXCPM2_HOST=$BindHost VOXCPM2_PORT=$TtsPort ./Start-VoxCPM2-NanoVLLM-WSL.sh"
"@

& wsl.exe bash -lc $wslCommand
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start WSL tmux services."
}

Wait-Http "Frontend" $frontendUrl 60
Wait-Http "Backend" $backendUrl 90
Wait-Http "TTS" $ttsHealthUrl 150

Start-Process $frontendUrl
Start-Process $ttsUrl

Write-Host ""
Write-Host "All services are ready."
Write-Host "Frontend: $frontendUrl"
Write-Host "Backend:  $backendUrl"
Write-Host "TTS page: $ttsUrl"
Write-Host "UE WS:    ws://${PublicIp}:10002"
Write-Host ""
Write-Host "Logs:"
Write-Host "  wsl.exe tmux attach -t open-llm-vtuber"
Write-Host "  wsl.exe tmux attach -t open-llm-vtuber-frontend"
Write-Host "  wsl.exe tmux attach -t voxcpm2-nanovllm"
