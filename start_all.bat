@echo off
cd /d "%~dp0"

echo [1/2] Starting Jetson backend via SSH (opens a new window)...
echo       Edit this file if Jetson's IP changed (e.g. switched to WiFi).
start "Jetson Backend" cmd /k ssh lee@192.168.55.1 "cd ~/edge_ai_project/edge_backend && ./start_backend.sh"

echo [2/2] Building and starting frontend...
cd web_frontend
call npm run build
if errorlevel 1 (
    echo [ERROR] npm run build failed. Frontend not started.
    pause
    exit /b 1
)

start "Frontend Preview" cmd /k npm run preview

echo.
echo Both started in separate windows:
echo   - Jetson Backend   : SSH window, will prompt for password
echo   - Frontend Preview : http://localhost:4173
echo.
pause
