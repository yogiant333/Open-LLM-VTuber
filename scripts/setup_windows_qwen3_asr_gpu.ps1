param(
    [string]$PythonVersion = "3.12",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu129"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    throw "Missing uv. Install uv first, or run from an environment where uv is available."
}

Write-Host "Creating Python $PythonVersion virtual environment at $root\.venv"
if (Test-Path -LiteralPath ".venv") {
    $existingPython = Join-Path $root ".venv\Scripts\python.exe"
    $existingVersion = ""
    if (Test-Path -LiteralPath $existingPython) {
        $existingVersion = (& $existingPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    }
    if ($existingVersion -ne $PythonVersion) {
        $venvPath = (Resolve-Path ".venv").Path
        if (-not $venvPath.StartsWith($root.Path, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove .venv outside project root: $venvPath"
        }
        Write-Host "Existing .venv uses Python $existingVersion. Removing it to create Python $PythonVersion environment."
        Remove-Item -LiteralPath $venvPath -Recurse -Force
    } else {
        Write-Host "Existing Python $existingVersion .venv found. It will be reused by uv."
    }
}

uv venv --python $PythonVersion .venv

Write-Host "Installing Open-LLM-VTuber dependencies"
uv pip install --python .\.venv\Scripts\python.exe -e .

Write-Host "Installing CUDA PyTorch from $TorchIndexUrl"
uv pip install --python .\.venv\Scripts\python.exe --reinstall torch torchaudio --index-url $TorchIndexUrl

Write-Host "Verifying Qwen3-ASR GPU runtime"
$verify = @'
import importlib.util
import sys

if not importlib.util.find_spec("qwen_asr"):
    raise SystemExit("qwen_asr is not installed")

import torch

print("python", sys.version)
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("cuda_device_count", torch.cuda.device_count())
if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available in this environment")
print("cuda_device_0", torch.cuda.get_device_name(0))
'@

$verify | .\.venv\Scripts\python.exe -

Write-Host ""
Write-Host "Qwen3-ASR GPU environment is ready."
