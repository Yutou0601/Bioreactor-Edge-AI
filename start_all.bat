@echo off
cd /d "%~dp0"

echo [1/3] Starting Jetson backend via SSH (opens a new window)...
echo       Edit this file if Jetson's IP changed (e.g. switched to WiFi).
start "Jetson Backend" cmd /k ssh lee@192.168.55.1 "cd ~/edge_ai_project/edge_backend && ./start_backend.sh"

echo [2/3] Starting CSV watcher (opens a new window)...
echo       Edit edge_backend\start_csv_watcher.bat if the data folder path changed.
start "CSV Watcher" cmd /k "edge_backend\start_csv_watcher.bat"

echo [3/3] Building and starting frontend...
cd web_frontend
call npm run build
if errorlevel 1 (
    echo [ERROR] npm run build failed. Frontend not started.
    pause
    exit /b 1
)

start "Frontend Preview" cmd /k npm run preview

echo.
echo All three started in separate windows:
echo   - Jetson Backend   : SSH window, will prompt for password
echo   - CSV Watcher       : forwards new CSV rows to Jetson via MQTT
echo   - Frontend Preview : http://localhost:4173
echo.
pause
