@echo off
cd /d "%~dp0"

REM ============================================================
REM  一鍵同步更新：監控電腦（本機）+ Jetson
REM  監控電腦：git pull -> pip install(venv) -> npm build(前端)
REM  Jetson  ：git pull -> 只裝新增的 openpyxl（避免動到 NVIDIA CUDA torch）
REM ============================================================

echo [1/5] Pulling monitoring PC repo...
git pull
if errorlevel 1 (
    echo [ERROR] git pull failed on this machine. Fix this before continuing.
    pause
    exit /b 1
)

echo.
echo [2/5] Installing backend deps in venv...
if exist "edge_backend\venv\Scripts\activate.bat" (
    call edge_backend\venv\Scripts\activate.bat
    python -m pip install -r edge_backend\requirements.txt
    if errorlevel 1 echo [WARN] pip install had errors. Check output above.
    call edge_backend\venv\Scripts\deactivate.bat >nul 2>&1
) else (
    echo [WARN] edge_backend\venv not found. Skipping pip install.
    echo        If backend fails to start, create venv and run:
    echo          pip install -r edge_backend\requirements.txt
)

echo.
echo [3/5] Rebuilding frontend...
where npm >nul 2>&1
if errorlevel 1 (
    echo [WARN] npm not found on PATH. Skipping frontend build.
) else (
    pushd web_frontend
    call npm run build
    if errorlevel 1 echo [WARN] npm run build failed. Check output above.
    popd
)

echo.
echo [4/5] Pulling Jetson repo via SSH (192.168.55.1)...
echo       Edit this file if Jetson's IP changed (e.g. switched to WiFi).
ssh lee@192.168.55.1 "cd ~/edge_ai_project && git pull"
if errorlevel 1 (
    echo [WARN] SSH to Jetson failed or git pull errored there. Check connection.
    echo        Skipping Jetson dep install.
    goto :done
)

echo.
echo [5/5] Installing new backend dep on Jetson (openpyxl only)...
echo       NOTE: intentionally NOT running full requirements.txt on Jetson to
echo       avoid overwriting its NVIDIA CUDA build of torch/onnxruntime.
ssh lee@192.168.55.1 "pip install openpyxl"
if errorlevel 1 echo [WARN] openpyxl install on Jetson errored. Check manually.

:done
echo.
echo Done. Restart backend (start_backend.bat) to pick up changes.
pause
