@echo off
cd /d "%~dp0"

REM ============================================================
REM  Launch the desktop control panel.
REM
REM  NOTE: keep this file ASCII-only. cmd.exe reads .bat files using the
REM  system ANSI codepage, so UTF-8 Chinese text here gets mangled into
REM  garbage commands and the launcher fails in a confusing way.
REM
REM  Double-clicking control_panel.pyw relies on the .pyw file association;
REM  if that association is broken nothing happens at all (silent failure),
REM  which is the worst outcome for a launcher. This wrapper resolves an
REM  interpreter explicitly and reports a clear error when none is found.
REM ============================================================

set PANEL=control_panel.pyw

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
