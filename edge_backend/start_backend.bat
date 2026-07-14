@echo off
cd /d "%~dp0"

echo [INFO] Freeing port 8000 if in use...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [INFO] Killing PID %%a on port 8000...
    taskkill /F /PID %%a >nul 2>&1
)

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found. Run these first:
    echo   python -m venv venv
    echo   venv\Scripts\activate
    echo   pip install torch --index-url https://download.pytorch.org/whl/cpu
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python main.py

echo.
echo [main.py exited]
pause
