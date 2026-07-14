@echo off
cd /d "%~dp0"

echo [1/2] Pulling monitoring PC repo...
git pull
if errorlevel 1 (
    echo [ERROR] git pull failed on this machine. Fix this before syncing Jetson.
    pause
    exit /b 1
)

echo.
echo [2/2] Pulling Jetson repo via SSH (192.168.55.1)...
echo       Edit this file if Jetson's IP has changed (e.g. switched to WiFi).
ssh lee@192.168.55.1 "cd ~/edge_ai_project && git pull"
if errorlevel 1 (
    echo [WARN] SSH to Jetson failed or git pull errored there. Check connection.
)

echo.
echo Done.
pause
