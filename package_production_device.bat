@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "LIVETALKING_DIR=E:\AI\LiveTalking"
set "TTS_DIR=C:\AI\voxcpm2-nanovllm-win-venv"

if exist "%TTS_DIR%\" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\package_production_device.ps1" -LiveTalkingDir "%LIVETALKING_DIR%" -TtsDir "%TTS_DIR%"
) else (
  echo TTS directory not found: %TTS_DIR%
  echo Packaging without TTS. Copy or install TTS on the production device before starting.
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\package_production_device.ps1" -LiveTalkingDir "%LIVETALKING_DIR%" -SkipTts
)

if errorlevel 1 (
  set "RC=%ERRORLEVEL%"
  echo.
  echo Packaging failed.
  pause
  exit /b %RC%
)

echo.
echo Packaging completed.
pause
exit /b 0
