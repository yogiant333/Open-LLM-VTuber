@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR_NO_TRAILING_SLASH=%SCRIPT_DIR:~0,-1%"
set "PORT=12393"

for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$configPath = Join-Path '%SCRIPT_DIR%' 'conf.yaml'; if (Test-Path -LiteralPath $configPath) { $inSystemConfig = $false; foreach ($line in Get-Content -LiteralPath $configPath -Encoding UTF8) { if ($line -match '^\s*system_config\s*:') { $inSystemConfig = $true; continue }; if ($inSystemConfig -and $line -match '^\S') { break }; if ($inSystemConfig -and $line -match '^\s*port\s*:\s*(\d+)') { $matches[1]; exit 0 } } }"`) do set "PORT=%%P"

set "URL=http://localhost:%PORT%"

where wsl.exe >nul 2>nul
if errorlevel 1 (
    echo WSL was not found. Please install WSL first, then run this script again.
    pause
    exit /b 1
)

powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%' | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 (
    echo Open-LLM-VTuber is already running.
    start "" "%URL%"
    pause
    exit /b 0
)

for /f "usebackq delims=" %%I in (`wsl.exe wslpath -a "%SCRIPT_DIR_NO_TRAILING_SLASH%"`) do set "WSL_DIR=%%I"

if not defined WSL_DIR (
    echo Failed to convert this folder to a WSL path.
    pause
    exit /b 1
)

echo Starting Open-LLM-VTuber from:
echo %WSL_DIR%
echo.
echo The browser will open automatically after a short delay.
echo Keep this window open while using the app.
echo.

powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 10; Start-Process '%URL%'" >nul 2>nul

wsl.exe bash -lc "cd '%WSL_DIR%' && if ! command -v uv >/dev/null 2>&1; then echo 'uv was not found in WSL. Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh'; exit 1; fi; uv run run_server.py"

echo.
echo Server process exited.
pause
