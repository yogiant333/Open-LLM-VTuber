@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%healthcheck.ps1"
if errorlevel 1 (
  set "RC=%ERRORLEVEL%"
  echo.
  echo Health check failed.
  pause
  exit /b %RC%
)
echo.
echo Health check passed.
pause
exit /b 0
