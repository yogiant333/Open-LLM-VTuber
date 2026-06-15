@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%Start-Windows-Backend-Only.ps1" %*
if errorlevel 1 (
    echo.
    echo Backend startup failed.
    pause
    exit /b 1
)

echo.
echo Backend is running. Keep this window open only if you want to see this message.
pause
