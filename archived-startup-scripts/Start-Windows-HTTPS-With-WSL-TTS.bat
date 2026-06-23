@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%Start-Windows-HTTPS-With-WSL-TTS.ps1"

if not exist "%PS_SCRIPT%" (
    echo Missing script: %PS_SCRIPT%
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*

echo.
echo Script exited with code %ERRORLEVEL%.
pause
