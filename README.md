# Bioreactor Edge AI Real-time Monitoring System
## 基於 NVIDIA Jetson Orin Nano 的生物反應器壓力預測與效能分析中樞

### 專案簡介
本專案利用邊緣運算（Edge Computing）技術，針對生物反應器進行即時壓力監測與趨勢預測。透過 LSTM 深度學習模型與 MQTT 異步通訊架構，系統能以極低延遲預警壓力異常，並分析不同氣體比例對系統效能之影響。

---

### 核心功能
* **實時數據流**：全面採用 MQTT Pub/Sub 協定，達成數據變動即渲染，取代傳統 HTTP 輪詢以降低開銷。
* **AI 壓力趨勢預測**：基於時間序列模型預測未來 5 分鐘之反應器壓力曲線，提供預防性維護。
* **真實推論延遲監控**：實時顯示 Jetson Orin Nano 執行 PyTorch 運算的真實耗時（ms）。
* **多維度特徵分析**：整合 ORP、pH、溫度及氣體比例，評估生物碳轉換系統穩定性。
* **異常注入模擬**：內建異常觸發機制，驗證系統在壓力危險狀態下的自動報警邏輯。

---

### 系統架構
專案採用事件驅動（Event-Driven）設計，確保邊緣端推論引擎與監控介面高度解耦。



* **Edge Node (Jetson Orin Nano)**
  - 運行 Mosquitto MQTT Broker 作為通訊中樞。
  - Inference Engine：監聽感測器數據主題，使用 PyTorch 進行即時推論。
  - FastAPI：負責模型生命週期管理與提供輔助 API。

* **Web Dashboard (Vue 3)**
  - 透過 WebSocket over MQTT 訂閱推論結果。
  - 使用 ECharts 繪製動態即時折線圖與 AI 預測軌跡（虛線）。
  - 展示邊緣節點硬體資訊、連線協定狀態與真實延遲數據。

---

### 技術棧
* **通訊協定**：MQTT (v5.0), WebSocket
* **邊緣硬體**：NVIDIA Jetson Orin Nano (8GB)
* **AI 框架**：PyTorch (CUDA 加速), LSTM Network
* **後端架構**：Python 3.10, FastAPI, Paho-MQTT
* **前端介面**：Vue 3, Vite, ECharts, Tailwind CSS

---

### 快速啟動

#### 1. 基礎環境配置 (Jetson 端)
確保已安裝 Mosquitto 並配置 WebSocket 支援（Port 9001）。編輯 /etc/mosquitto/mosquitto.conf 確保包含 listener 1883 與 9001 (protocol websockets) 設定後重啟服務。

#### 2. 後端推論啟動
進入 edge_backend 目錄，安裝 Python 依賴，並執行 main.py 啟動 FastAPI 與背景 MQTT 客戶端。

#### 3. 前端控制台啟動
進入 web_frontend 目錄，執行 npm install 與 npm run dev 開啟監控介面。

---

### 數據分析目標
本系統主要針對邊緣計算不同氣體比例影響生物碳轉換系統效能進行深度分析。

* **變量控制**：固定進出入壓力，調整氣體比例（4:1、2:1、1:1）。
* **效能分析指標**：長期觀察（1週、2週、1個月）ORP 與 pH 的波動趨勢，評估轉換效率。
* **系統穩定性預警**：透過 AI 提早發現反應器壓力異常，防止生物反應失衡。
