@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_all.ps1"
if errorlevel 1 (
  set "RC=%ERRORLEVEL%"
  echo.
  echo Start failed.
  pause
  exit /b %RC%
)
echo.
echo Services started.
pause
exit /b 0
