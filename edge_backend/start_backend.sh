#!/bin/bash
# Jetson 用啟動腳本，對應 Windows 版的 start_backend.bat
cd "$(dirname "$0")"

echo "[INFO] Freeing port 8000 if in use..."
if command -v fuser >/dev/null 2>&1; then
    fuser -k 8000/tcp 2>/dev/null
elif command -v lsof >/dev/null 2>&1; then
    lsof -ti:8000 | xargs -r kill -9
else
    echo "[WARN] Neither fuser nor lsof found, cannot auto-free port 8000."
    echo "       Install with: sudo apt install -y psmisc"
fi
sleep 1

if [ -f "venv/bin/activate" ]; then
    echo "[INFO] venv found, activating..."
    source venv/bin/activate
else
    echo "[INFO] No venv found, using system python3 (normal on Jetson where"
    echo "       NVIDIA's CUDA-linked PyTorch is usually installed system-wide)."
fi

python3 main.py
status=$?

echo
if [ $status -ne 0 ]; then
    echo "[main.py exited with error, code $status]"
else
    echo "[main.py exited normally]"
fi
read -p "Press Enter to close..."
