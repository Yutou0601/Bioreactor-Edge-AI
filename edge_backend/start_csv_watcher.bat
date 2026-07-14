@echo off
cd /d "%~dp0"

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
python csv_watcher.py --dir "C:\Users\BTP\Desktop\data"

echo.
echo [csv_watcher.py exited]
pause
