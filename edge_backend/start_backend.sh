#!/bin/bash
# Jetson 用啟動腳本，對應 Windows 版的 start_backend.bat
cd "$(dirname "$0")"

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
