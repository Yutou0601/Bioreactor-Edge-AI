# Bioreactor Edge AI Project
> **基於 NVIDIA Jetson Orin Nano 的生物反應器壓力即時預測系統**

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Vue3](https://img.shields.io/badge/Frontend-Vue%203-4FC08D?style=flat-square&logo=vue.js)](https://vuejs.org/)
[![PyTorch](https://img.shields.io/badge/AI-PyTorch-EE4C2C?style=flat-square&logo=pytorch)](https://pytorch.org/)
[![Jetson](https://img.shields.io/badge/Hardware-NVIDIA%20Jetson-76B900?style=flat-square&logo=nvidia)](https://www.nvidia.com/zh-tw/autonomous-machines/embedded-systems/jetson-orin/)

本專案旨在利用邊緣運算（Edge Computing）技術，針對生物反應器進行即時壓力監測與趨勢預測。透過 LSTM 深度學習模型，系統能提前 5 分鐘預警潛在的壓力異常，協助管理人員進行預防性維護。

## 目錄
- [系統架構](#-系統架構)
- [快速啟動](#-快速啟動)
- [API 說明](#-api-說明)
- [技術重點](#-技術重點)

---

## 系統架構

專案採用前後端分離的微服務設計，確保邊緣端運算與使用者介面展示的解耦：

* **Edge Backend**: 運行於 Jetson Orin Nano。負責 CSV 資料流處理、AI 模型推論及 RESTful API 提供。
* **Web Frontend**: 運行於控制端。使用 Vue 3 與 ECharts 繪製即時動態折線圖，具備異常注入測試功能。

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
