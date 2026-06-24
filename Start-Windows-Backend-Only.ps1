param(
    [string]$BindHost = "127.0.0.1",
    [int]$BackendPort = 18080,
    [int]$UeWsPort = 10002,
    [int]$StartupAttempts = 300,
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

$preflightScript = @'
from pathlib import Path
import importlib.util
import sys

import yaml

conf = yaml.safe_load(Path("conf.yaml").read_text(encoding="utf-8"))
asr = conf.get("character_config", {}).get("asr_config", {})
asr_model = asr.get("asr_model")
if asr_model not in {"qwen3_asr", "qwen3_asr_gguf"}:
    raise SystemExit(0)

if sys.version_info < (3, 12):
    raise SystemExit(f"{asr_model} requires the Windows backend .venv to use Python 3.12.")

if asr_model == "qwen3_asr":
    if importlib.util.find_spec("qwen_asr") is None:
        raise SystemExit("Qwen3-ASR is enabled but qwen_asr is not installed. Run scripts\\setup_windows_qwen3_asr_gpu.ps1.")

    import torch

    if not torch.cuda.is_available():
        raise SystemExit("Qwen3-ASR is enabled but CUDA is not available in torch. Run scripts\\setup_windows_qwen3_asr_gpu.ps1.")

    print(f"Qwen3-ASR GPU preflight OK: python={sys.version.split()[0]}, torch={torch.__version__}, gpu={torch.cuda.get_device_name(0)}")

if asr_model == "qwen3_asr_gguf":
    gguf = asr.get("qwen3_asr_gguf") or {}
    working_dir = Path(gguf.get("working_dir") or "Qwen3-ASR-GGUF")
    model_dir = Path(gguf.get("model_dir") or "Qwen3-ASR-GGUF/model")
    required_packages = ("gguf", "srt", "onnxruntime")
    missing_packages = [name for name in required_packages if importlib.util.find_spec(name) is None]
    if missing_packages:
        raise SystemExit("Qwen3-ASR-GGUF is enabled but packages are missing: " + ", ".join(missing_packages))
    import onnxruntime as ort
    if bool(gguf.get("use_dml", True)) and "DmlExecutionProvider" not in ort.get_available_providers():
        raise SystemExit(
            "Qwen3-ASR-GGUF is configured for DirectML, but onnxruntime does not expose DmlExecutionProvider."
        )
    if not working_dir.is_dir():
        raise SystemExit(f"Qwen3-ASR-GGUF submodule directory is missing: {working_dir}")
    bin_dir = working_dir / "qwen_asr_gguf" / "inference" / "bin"
    if not (bin_dir / "llama.dll").is_file():
        raise SystemExit(f"Qwen3-ASR-GGUF llama.cpp runtime DLLs are missing from: {bin_dir}")
    required_files = [
        gguf.get("asr_encoder_frontend") or "qwen3_asr_encoder_frontend.int4.onnx",
        gguf.get("asr_encoder_backend") or "qwen3_asr_encoder_backend.int4.onnx",
        gguf.get("asr_llm") or "qwen3_asr_llm.q4_k.gguf",
    ]
    if bool(gguf.get("timestamp", False)):
        required_files.extend(
            [
                gguf.get("aligner_encoder_frontend") or "qwen3_aligner_encoder_frontend.int4.onnx",
                gguf.get("aligner_encoder_backend") or "qwen3_aligner_encoder_backend.int4.onnx",
                gguf.get("aligner_llm") or "qwen3_aligner_llm.q4_k.gguf",
            ]
        )
    missing_files = [name for name in required_files if not (model_dir / name).is_file()]
    if missing_files:
        raise SystemExit(f"Qwen3-ASR-GGUF model files are missing from {model_dir}: " + ", ".join(missing_files))
    print(f"Qwen3-ASR-GGUF preflight OK: python={sys.version.split()[0]}, submodule={working_dir}, model_dir={model_dir}")
'@

$preflightScript | & $backendPython -
if ($LASTEXITCODE -ne 0) {
    throw "Backend environment preflight failed."
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

$env:OPEN_LLM_VTUBER_UE_WS_HOST = $BindHost
$env:OPEN_LLM_VTUBER_UE_WS_PORT = [string]$UeWsPort
$env:OPEN_LLM_VTUBER_PUBLIC_URL = "http://${waitHost}:${BackendPort}"
$env:KMP_DUPLICATE_LIB_OK = "TRUE"

Write-Host "Starting Open-LLM-VTuber backend only"
Write-Host "Project: $root"
Write-Host "Backend: http://${BindHost}:${BackendPort}/"
Write-Host "UE WS:   ws://${BindHost}:${UeWsPort}"
Write-Host "Config:  conf.yaml"
Write-Host ""

$args = @("-m", "uvicorn", "run_server:create_app", "--factory", "--host", $BindHost, "--port", $BackendPort)
if ($VerboseLog) {
    $args += @("--log-level", "debug")
}

$env:OPEN_LLM_VTUBER_UE_WS_HOST = $BindHost
$env:OPEN_LLM_VTUBER_UE_WS_PORT = [string]$UeWsPort

$backendProcess = Start-Process -FilePath $backendPython `
    -ArgumentList $args `
    -WorkingDirectory $root `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError $backendErr `
    -WindowStyle Hidden `
    -PassThru
Set-Content -LiteralPath $backendPid -Value $backendProcess.Id -Encoding ascii

try {
    Wait-Http "Backend" $backendUrl $StartupAttempts -Process $backendProcess -StdoutLog $backendLog -StderrLog $backendErr
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
