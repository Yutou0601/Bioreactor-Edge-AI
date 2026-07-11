# x86 監控電腦用映像。Python 版本對齊 Jetson 上實測的 3.10.12，
# 盡量拉近兩邊語言層級的行為一致性（底層 CUDA/wheel 仍會因架構而異，
# 這點 Docker 無法完全消除，Jetson 端需另外用 L4T 對應的基礎映像）。
FROM python:3.10-slim

WORKDIR /app/edge_backend

COPY requirements.txt .

# CPU 版 PyTorch：體積小、下載快，這條分析管線的模型也不需要 GPU 加速
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 注意：USB 感測器（/dev/ttyUSB0）在 Windows + Docker Desktop 環境下
# 沒有直接的裝置直通，usb_receiver.py 這條路徑在容器內無法運作，
# 需要 usbipd-win 之類的工具額外處理，本 Dockerfile 目前只涵蓋
# API 服務與離線分析（ch4_peak_analysis.py），不含即時 USB 接收。
CMD ["python", "main.py"]
