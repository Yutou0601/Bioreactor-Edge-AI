@echo off
REM ===================================================================
REM  UPDATE  --  run this on the MONITORING PC
REM
REM  Pulls the latest released code and restarts nothing by itself.
REM  Close the control panel first, run this, then start it again.
REM
REM  SAFE BY DESIGN:
REM   * Field data is never touched.  reactor.db, experiment_runs.json
REM     and .env are all gitignored, so a pull cannot overwrite them.
REM   * It REFUSES to run if someone edited files on this machine,
REM     rather than silently discarding their work.
REM   * It records the previous commit so you can roll back.
REM
REM  ASCII only: cmd.exe reads .bat with the system ANSI codepage.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   Bioreactor -- update from GitHub
echo ============================================================

where git >nul 2>&1
if errorlevel 1 (
  echo   [!] git is not installed on this machine.
  echo       Install Git for Windows, then run this again.
  pause & exit /b 1
)

echo.
echo --- Current version -----------------------------------------
git describe --tags --always 2>nul
for /f "delims=" %%i in ('git rev-parse HEAD') do set OLDREV=%%i
echo   commit %OLDREV%

echo.
echo --- Checking for local edits --------------------------------
git diff --quiet
if errorlevel 1 (
  echo.
  echo   [!] This machine has edited files.  Update stopped.
  echo       Nothing was changed.  Someone modified the code here;
  echo       find out what and why before overwriting it:
  echo.
  git status --short
  echo.
  echo       To discard those edits and update anyway:
  echo           git checkout -- .
  echo           update.bat
  echo.
  pause & exit /b 1
)
echo   clean

echo.
echo --- Pulling --------------------------------------------------
git pull --ff-only origin main
if errorlevel 1 (
  echo.
  echo   [!] Pull failed.  Common causes: no network, or the history
  echo       diverged.  Nothing was changed.  Old version still runs.
  pause & exit /b 1
)

echo.
echo --- Python dependencies -------------------------------------
if exist edge_backend\venv\Scripts\python.exe (
  edge_backend\venv\Scripts\python.exe -m pip install -q -r edge_backend\requirements.txt
  if errorlevel 1 echo   [!] pip reported a problem -- check above.
) else (
  echo   [!] No venv found at edge_backend\venv
  echo       First-time setup: python -m venv edge_backend\venv
  echo       then rerun this script.
  pause & exit /b 1
)

echo.
echo --- Site settings -------------------------------------------
if exist edge_backend\.env (
  echo   .env present -- your local settings are kept.
) else (
  echo   [!] No .env on this machine.  Copying the template:
  copy /y edge_backend\.env.example edge_backend\.env >nul
  echo       Created edge_backend\.env -- OPEN IT AND CHECK THE PATHS.
)

echo.
echo --- Self check ----------------------------------------------
echo ------------------------------------------------------------
edge_backend\venv\Scripts\python.exe edge_backend\selfcheck.py
if errorlevel 1 (
  echo ------------------------------------------------------------
  echo.
  echo   [!] Self check FAILED after the update.  NOT starting.
  echo.
  echo       Fix what is marked above, then run update.bat again.
  echo       If the new version itself is broken, roll back with:
  echo           git reset --hard %OLDREV%
  echo.
  pause & exit /b 1
)
echo ------------------------------------------------------------

echo.
echo ============================================================
echo   Updated to:
git describe --tags --always 2>nul
echo.
echo   Previous version was %OLDREV%
echo   To roll back:  git reset --hard %OLDREV%
echo ============================================================

echo.
echo   Self check passed.  Starting...
if exist START.bat (
  start "" START.bat
  echo   Started.  The control panel window should appear.
) else (
  echo   [!] START.bat not found; start it manually.
)
echo.
pause
endlocal
