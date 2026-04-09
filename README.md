# Bioreactor Edge AI Project
> **基於 NVIDIA Jetson Orin Nano 的生物反應器壓力即時預測系統**

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Vue3](https://img.shields.io/badge/Frontend-Vue%203-4FC08D?style=flat-square&logo=vue.js)](https://vuejs.org/)
[![PyTorch](https://img.shields.io/badge/AI-PyTorch-EE4C2C?style=flat-square&logo=pytorch)](https://pytorch.org/)
[![Jetson](https://img.shields.io/badge/Hardware-NVIDIA%20Jetson-76B900?style=flat-square&logo=nvidia)](https://www.nvidia.com/zh-tw/autonomous-machines/embedded-systems/jetson-orin/)

本專案旨在利用邊緣運算（Edge Computing）技術，針對生物反應器進行即時壓力監測與趨勢預測。透過 LSTM 深度學習模型，系統能提前 5 分鐘預警潛在的壓力異常，協助管理人員進行預防性維護。

## 目錄
- [系統架構](#-系統架構)
- [工程日誌 (重要變更)](#-工程日誌-重要變更)
- [快速啟動](#-快速啟動)
- [API 說明](#-api-說明)
- [技術重點](#-技術重點)

---

## 系統架構

專案採用前後端分離的微服務設計，確保邊緣端運算與使用者介面展示的解耦：

* **Edge Backend**: 運行於 Jetson Orin Nano。負責 CSV 資料流處理、AI 模型推論及 RESTful API 提供。
* **Web Frontend**: 運行於控制端。使用 Vue 3 與 ECharts 繪製即時動態折線圖，具備異常注入測試功能。

---

## 工程日誌 (Engineering Log)

### 2026-03-27: 工業級架構重構 (Refactoring)
- **問題**: 原始程式碼邏輯耦合，API 啟動時需重複讀取 6 萬筆資料導致初始化緩慢。
- **變更**:
    - 實作 `data_pipeline` 模組，將資料載入 (`loader`) 與預處理 (`preprocessor`) 獨立化。
    - **Scaler 持久化**: 導入 `joblib` 將 `MinMaxScaler` 儲存為 `.pkl` 格式。
- **結果**: API 啟動時間從 >10 秒優化至 <1 秒，且保證推論時的數值比例尺與訓練時完全一致。

### 2026-03-26: 解決 GPU 記憶體溢位 (OOM)
- **問題**: 增加訓練資料量至 62,640 筆後，Jetson 出現 `RuntimeError: NVML_SUCCESS == r`。
- **解決方案**: 捨棄全量訓練，導入 PyTorch `DataLoader` 實作 **Batch Training (批次訓練)**，設定 `batch_size=128`。
- **結果**: 成功將運算負載壓制在 8GB 統一記憶體內，模型收斂誤差 (Loss) 降至 **0.0222**。

### 2026-03-25: 雙向通訊機制開發
- **功能**: 新增 `POST /upload_sensor` 通道，支援從前端同步模擬/真實感測器數據至後端，達成閉環監控。

---

## 快速啟動

### 1. 後端 (Jetson Orin Nano)
```bash
cd edge_backend
# 安裝依賴
pip3 install -r requirements.txt
# 執行模型訓練並產生權重與比例尺
python3 train.py
# 啟動 API 伺服器
python3 main.py
```

### 2. 前端 (Website)
```bash
npm run dev
```
