@echo off
REM ===================================================================
REM  PACK  --  run this on the DEVELOPMENT laptop
REM
REM  Builds a self-contained zip for the monitoring PC.  Use this when
REM  git is not an option: a brand new machine, or the network cannot
REM  be turned on right now.
REM
REM  Normal updates should still go through git (update.bat) -- it only
REM  transfers what changed and rollback is one command.  This pack is
REM  the fallback, not the main channel.
REM
REM  The zip contains the Python wheels too, so install.bat works with
REM  no network at all.  Without them, pip would try to reach PyPI and
REM  fail on an offline machine -- which is exactly when you need this.
REM
REM  NEVER packed: reactor.db, experiment_runs.json, .env, venv,
REM  Testing_data, __pycache__.  Those are field data or machine
REM  specific; shipping them would overwrite the site's own state.
REM
REM  ASCII only: cmd.exe reads .bat with the system ANSI codepage.
REM ===================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if "%~1"=="" (
  echo.
  echo   Usage:  pack.bat ^<version^>
  echo   Example: pack.bat v1.3.0
  exit /b 1
)
set VERSION=%~1
set STAGE=%TEMP%\bioreactor_pack_%VERSION%
set OUTZIP=%~dp0Bioreactor-%VERSION%.zip

echo.
echo === 1/5  Building the frontend ====================================
pushd web_frontend
call npm run build
if errorlevel 1 ( echo   [!] Build failed. & popd & exit /b 1 )
popd

echo.
echo === 2/5  System test =============================================
pushd edge_backend
if exist venv\Scripts\python.exe (
  venv\Scripts\python.exe system_test.py
) else (
  python system_test.py
)
if errorlevel 1 ( echo   [!] System test FAILED -- not packing. & popd & exit /b 1 )
popd

echo.
echo === 3/5  Downloading wheels (for offline install) =================
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%\wheels"
if exist edge_backend\venv\Scripts\python.exe (
  edge_backend\venv\Scripts\python.exe -m pip download -q ^
    -r edge_backend\requirements.txt -d "%STAGE%\wheels"
) else (
  python -m pip download -q -r edge_backend\requirements.txt -d "%STAGE%\wheels"
)
if errorlevel 1 (
  echo   [!] Could not download wheels.  You need network for THIS step
  echo       even though the resulting pack installs offline.
  exit /b 1
)

echo.
echo === 4/5  Assembling ==============================================
robocopy edge_backend "%STAGE%\edge_backend" /E ^
  /XD venv __pycache__ Testing_data picture .pytest_cache ^
  /XF *.pyc reactor.db reactor.db-* experiment_runs.json* .env *.log ^
  /NFL /NDL /NJH /NJS /NP >nul
robocopy web_frontend\dist "%STAGE%\web_frontend\dist" /E /NFL /NDL /NJH /NJS /NP >nul
copy /y update.bat  "%STAGE%\" >nul
copy /y START.bat   "%STAGE%\" >nul
copy /y launcher.pyw "%STAGE%\" >nul 2>nul

REM ---- version stamp so the field machine can say what it is running
> "%STAGE%\VERSION.txt" echo %VERSION%
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do >> "%STAGE%\VERSION.txt" echo commit %%i
>> "%STAGE%\VERSION.txt" echo packed %DATE% %TIME%

REM ---- the offline installer is a real file in deploy/, not generated
REM      here.  Generating a .bat with echo lines needs every ( ) ^ and >
REM      escaped, which is unreadable and breaks silently.
copy /y deploy\install.bat "%STAGE%\" >nul
if errorlevel 1 ( echo   [!] deploy\install.bat missing. & exit /b 1 )

echo.
echo === 5/5  Zipping =================================================
if exist "%OUTZIP%" del /q "%OUTZIP%"
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%OUTZIP%' -Force"
if errorlevel 1 ( echo   [!] Zip failed. & exit /b 1 )
rmdir /s /q "%STAGE%"

for %%A in ("%OUTZIP%") do set SIZE=%%~zA
set /a SIZEMB=!SIZE!/1048576
echo.
echo   Built %OUTZIP%  ^(!SIZEMB! MB^)
echo.
echo   On the monitoring PC:  unzip, then run install.bat
echo.
endlocal
