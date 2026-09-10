@echo off
cd /d "%~dp0"

REM ============================================================
REM  One-click launcher for the bioreactor monitoring system.
REM
REM  NOTE: keep this file ASCII-only. cmd.exe reads .bat files with the
REM  system ANSI codepage, so UTF-8 Chinese here becomes garbage commands
REM  and the launcher fails in a confusing way.
REM
REM  Jetson Orin Nano is gone (2026-09-01). Everything now runs on this
REM  one machine as a single process:
REM
REM      uvicorn main:app --port 8000
REM          /api/*  backend
REM          /       frontend dist/ (served by StaticFiles)
REM
REM  No SSH, no npm at runtime, no MQTT broker required.
REM  The old start_all.bat / sync_jetson.bat are obsolete.
REM  ADDITIONAL NOTES:
REM  Jetosn Orin Nano will be remove in next update. The new architecture is simpler and more robust.
REM ============================================================

set PANEL=launcher.pyw

if exist "edge_backend\venv\Scripts\pythonw.exe" (
    start "" "edge_backend\venv\Scripts\pythonw.exe" "%PANEL%"
    exit /b 0
)

where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%PANEL%"
    exit /b 0
)

where python >nul 2>&1
if not errorlevel 1 (
    echo [INFO] pythonw not found; using python instead.
    echo        An extra console window will stay open - this is normal.
    python "%PANEL%"
    exit /b 0
)

echo.
echo [ERROR] No Python interpreter found.
echo         Install Python, or make sure edge_backend\venv exists.
echo.
pause
exit /b 1
