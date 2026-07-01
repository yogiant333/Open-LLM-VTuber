@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%stop_all.ps1"
if errorlevel 1 (
  set "RC=%ERRORLEVEL%"
  echo.
  echo Stop failed.
  pause
  exit /b %RC%
)
echo.
echo Services stopped.
pause
exit /b 0
