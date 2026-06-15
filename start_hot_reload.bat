@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR_NO_TRAILING_SLASH=%SCRIPT_DIR:~0,-1%"
set "BACKEND_URL=http://127.0.0.1:18080"
set "FRONTEND_URL=http://127.0.0.1:3000"

where wsl.exe >nul 2>nul
if errorlevel 1 (
    echo WSL was not found. Please install WSL first, then run this script again.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%I in (`wsl.exe wslpath -a "%SCRIPT_DIR_NO_TRAILING_SLASH%"`) do set "WSL_DIR=%%I"

if not defined WSL_DIR (
    echo Failed to convert this folder to a WSL path.
    pause
    exit /b 1
)

echo Starting Open-LLM-VTuber hot reload services from:
echo %WSL_DIR%
echo.
echo Backend:  %BACKEND_URL%
echo Frontend: %FRONTEND_URL%
echo UE WS:    ws://127.0.0.1:10002
echo.
echo Two terminal windows will stay open for logs.
echo Close those windows to stop the services.
echo.

start "Open-LLM-VTuber Backend Hot Reload" cmd /k "wsl.exe bash -lc ""cd '%WSL_DIR%' && uv run uvicorn run_server:create_app --factory --reload --host 127.0.0.1 --port 18080 --reload-dir src --reload-dir prompts"""

start "Open-LLM-VTuber Frontend Hot Reload" cmd /k "wsl.exe bash -lc ""cd '%WSL_DIR%/frontend' && npm run dev:web -- --host 127.0.0.1 --force"""

powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 8; Start-Process '%FRONTEND_URL%'" >nul 2>nul

echo Hot reload services are starting.
echo Browser will open shortly: %FRONTEND_URL%
echo.
pause
