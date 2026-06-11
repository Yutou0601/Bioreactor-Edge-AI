# 技術規格文件
## 基於邊緣運算之生物反應器即時 ORP 變化分析與 CH4 峰值預測系統

**文件版本**：v1.0  
**撰寫日期**：2026-06-11  
**作者**：李承育（國立高雄科技大學）  
**合作單位**：金屬工業研究發展中心（MIRDC）

---

## 目錄

1. [系統概述](#1-系統概述)
2. [硬體架構](#2-硬體架構)
3. [資料擷取層](#3-資料擷取層)
4. [訊號前處理層](#4-訊號前處理層)
5. [ORP 特徵工程](#5-orp-特徵工程)
6. [生物相位偵測](#6-生物相位偵測)
7. [週期級特徵萃取](#7-週期級特徵萃取)
8. [CH4 峰值預測模型（離線分析）](#8-ch4-峰值預測模型離線分析)
9. [LSTM 即時預測模型](#9-lstm-即時預測模型)
10. [邊緣部署架構](#10-邊緣部署架構)
11. [REST API 規格](#11-rest-api-規格)
12. [前端介面規格](#12-前端介面規格)
13. [效能指標](#13-效能指標)
14. [已知限制與建議](#14-已知限制與建議)
15. [依賴套件清單](#15-依賴套件清單)

---

## 1. 系統概述

### 1.1 研究背景

本系統針對金屬工業研究發展中心開發之生物產氫／甲烷雙效微正壓循環生物反應器，建立一套以邊緣運算為核心的即時監控與預測平台。

**核心問題**：反應器在厭氧發酵過程中，氣體累積導致壓力上升，排氣時機判斷依賴人工觀測，存在安全風險與效率瓶頸。

**解決方案**：以 ORP（氧化還原電位, Oxidation-Reduction Potential）訊號作為嗜氫厭氧菌活性的間接量測指標，結合 LSTM 神經網路，在 Jetson Orin Nano 邊緣節點上完成即時推論，預測未來 5 分鐘的反應器壓力與 CH4 濃度。

### 1.2 ORP 生物意義

ORP（mV）反映溶液中的氧化還原環境，其動態行為與微生物代謝直接相關：

| 現象 | 生化機制 | ORP 變化 |
|------|---------|---------|
| CO₂ 溶於水 | CO₂ + H₂O → H₂CO₃（酸化）| pH 下降，ORP 波動 |
| 嗜氫甲烷菌活化 | CO₂ + 4H₂ → CH₄ + 2H₂O | ORP 回升，pH 上升 |
| 底物耗盡 | 菌相活動降低 | ORP 趨於穩態 |

ORP 訊號的週期性波動直接對應排氣前甲烷菌的代謝節律，是偵測排氣事件的關鍵特徵。

### 1.3 系統三層架構

```
[感測器層]          [邊緣計算層]              [展示層]
BTP 生物反應器  →   Jetson Orin Nano        →  Vue3 前端
  ORP / pH           訊號前處理                 MonitorView
  溫度 / 壓力        LSTM 推論                  ReportView
  CH4 / CO2          FastAPI (port 8000)
                     MQTT (port 1883)
```

---

## 2. 硬體架構

### 2.1 邊緣計算節點

| 規格項目 | 規格值 |
|---------|-------|
| 硬體平台 | NVIDIA Jetson Orin Nano |
| 作業系統 | Linux 5.15.136-tegra |
| 計算單元 | ARM CPU + NVIDIA GPU（CUDA 可用時自動啟用） |
| 感測器介面 | USB Serial `/dev/ttyUSB0`，鮑率 9600 bps |

### 2.2 感測器規格

| 感測器 | 量測範圍 | 解析度 | 採樣頻率 |
|-------|---------|-------|---------|
| ORP 電極 | 0 ~ 1000 mV | 1 mV | 1 min/筆 |
| pH 感測器 | 0 ~ 14 | 0.01 | 1 min/筆 |
| 溫度感測器 | 0 ~ 100 °C | 0.1 °C | 1 min/筆 |
| 壓力感測器（反應器） | 0 ~ 10 kg/cm² | 0.01 kg/cm² | 1 min/筆 |
| 壓力感測器（混合槽） | 0 ~ 10 kg/cm² | 0.01 kg/cm² | 1 min/筆 |
| CO2 感測器 | 0 ~ 100 % | 0.1 % | 1 min/筆 |
| CH4 感測器 | 0 ~ 100 % | 0.1 % | 1 min/筆 |

### 2.3 資料格式（CSV 原始行）

```
年,月,日,時,分,秒,_,ORP(mV),反應器壓力(kg/cm²),pH,溫度(°C),混合槽壓力(kg/cm²),CO2%,CH4%
2026,2,10,15,3,34,_,568,2.34,7.08,30.0,1.07,3.5,51.02
```

欄位索引對應（0-based）：

| 索引 | 欄位 | 說明 |
|-----|------|------|
| 0–5 | 年月日時分秒 | 時間戳記 |
| 6 | _ | 保留欄位 |
| 7 | ORP (mV) | 氧化還原電位 |
| 8 | 反應器壓力 (kg/cm²) | 生物反應器內壓 |
| 9 | 酸鹼值 (pH) | 溶液 pH 值 |
| 10 | 溫度 (°C) | 反應槽溫度 |
| 11 | 混合槽壓力 (kg/cm²) | 混合槽壓力 |
| 12 | CO2 濃度 (%) | 二氧化碳濃度 |
| 13 | CH4 濃度 (%) | 甲烷濃度 |

---

## 3. 資料擷取層

### 3.1 USB 即時接收（`usb_receiver.py`）

系統啟動後以 daemon 執行緒持續監聽 USB 序列埠，感測器未接時不阻塞 FastAPI 服務。

**處理流程**：

```
USB 讀取原始行
    │
    ▼
_parse_line()        ← 格式驗證、欄位解析
    │
    ▼
ORPSignalProcessor   ← 突波偵測 + 線性內插 + EMA
    │
    ▼
append_record()      ← 寫入記憶體資料倉儲
    │
    ▼
_write_csv_row()     ← 逐日備份至 data/BTP_Sensor_log-YYYY-MM-DD.csv
```

### 3.2 CSV 批次匯入（`POST /api/import_csv`）

支援離線 CSV 檔案上傳，自動套用相同的訊號前處理流程，並針對 timestamp 去重，避免重複匯入。

---

## 4. 訊號前處理層

**實作檔案**：`edge_backend/core/signal_processor.py`  
**類別**：`ORPSignalProcessor`

ORP 感測器在工業環境中會產生突波干擾（電磁雜訊、感測器接觸不良），需在進入特徵工程前完成清洗。

### 4.1 三階段處理流程

#### 階段一：一階差分突波偵測

$$\Delta x_t = x_t - x_{t-1}$$

當 $\Delta x_t < \theta_{\text{drop}}$（預設 $\theta_{\text{drop}} = -20\ \text{mV/min}$）時，判定為突波起始。

#### 階段二：線性內插重建

突波區間內所有資料點暫存至緩衝區，結束後統一以線性內插重建：

$$\hat{x}(t) = x_{\text{start}} + \frac{x_{\text{end}} - x_{\text{start}}}{N} \cdot i, \quad i = 1, 2, \ldots, N$$

**突波結束條件**（任一成立）：
- ORP 回升至起始值的 90% 以上且持續上升：`raw_orp >= spike_start_val × 0.90 AND Δx > 0`
- 突波持續超過最大視窗：`len(buffer) >= 15`（分鐘）

#### 階段三：指數移動平均（EMA）

$$y_t = \alpha \cdot \hat{x}_t + (1 - \alpha) \cdot y_{t-1}, \quad \alpha = \frac{2}{N+1} = \frac{2}{11} \approx 0.1818 \quad (N=10)$$

對清洗後的訊號做即時平滑輸出，作為後續特徵工程的輸入。

### 4.2 處理器參數表

| 參數 | 預設值 | 說明 |
|-----|-------|------|
| `ema_window` | 10 | EMA 平滑視窗 N |
| `spike_threshold` | −20.0 mV/min | 突波偵測閾值 |
| `spike_max_minutes` | 15 min | 突波最大持續時間 |

### 4.3 輸出資料結構（`ProcessedPoint`）

| 欄位 | 型別 | 說明 |
|-----|------|------|
| `timestamp` | str | ISO 格式時間戳記 |
| `raw` | float | 原始 ORP (mV) |
| `cleaned` | float | 突波修復後 ORP (mV) |
| `ema` | float | EMA 平滑後 ORP (mV) |
| `is_anomaly` | bool | 是否為突波修復點 |

---

## 5. ORP 特徵工程

### 5.1 即時三維特徵（`data_pipeline/preprocessor.py`）

從原始 ORP 序列衍生三個時序特徵，用於 LSTM 即時推論輸入：

| 特徵名稱 | 計算式 | 物理意義 |
|---------|-------|---------|
| `orp_ema` | EMA(N=10), α=2/11 | ORP 平滑趨勢值 |
| `orp_slope` | $(y_{\text{ema}}[t] - y_{\text{ema}}[t-5]) / 5$ | ORP 變化斜率（mV/min），描述趨勢方向與速率 |
| `orp_macd` | EMA(5) − EMA(30) | 短長期動能差，用於偵測趨勢反轉訊號 |

MACD 計算中：
- 短期 EMA(5)：α = 2/6 ≈ 0.3333
- 長期 EMA(30)：α = 2/31 ≈ 0.0645

### 5.2 穩態分析（`core/feature_extractor.py`）

**類別**：`ORPFeatureExtractor`

| 功能 | 方法 | 判斷條件 |
|-----|------|---------|
| 穩態判定 | 滑動視窗標準差 + 區間檢查 | σ < 5.0 mV 且 480 ≤ ORP ≤ 650 mV |
| 基準漂移率 | 最小平方線性迴歸 | 回看 120 筆，輸出 β₁ (mV/hr) |
| 穩態持續時間 | 末尾往回計數 | 連續在正常區間的分鐘數 |

---

## 6. 生物相位偵測

**實作位置**：`edge_backend/ch4_peak_analysis.py` → `detect_phases()`

### 6.1 自適應閾值計算

以週期內 ORP 斜率序列的統計量作為動態閾值，應對不同實驗條件：

1. 對原始斜率序列做**滾動平均平滑**（視窗 60 min），消除分鐘級雜訊
2. 計算平滑斜率的全局統計量：

$$\mu = \text{mean}(\text{smoothed\_slope}), \quad \sigma = \text{std}(\text{smoothed\_slope})$$

$$\text{低閾值} = \mu - k\sigma, \quad \text{高閾值} = \mu + k\sigma, \quad k = 0.5$$

### 6.2 三相位定義

| 相位 | 名稱 | 條件 | 生物意義 |
|-----|------|------|---------|
| Phase 1 | 底物利用期 | smoothed_slope < μ − 0.5σ | 嗜氫菌活躍消耗底物，ORP 下降 |
| Phase 2 | 產甲烷活躍期 | μ − 0.5σ ≤ slope ≤ μ + 0.5σ | 甲烷菌代謝活躍，ORP 相對穩定 |
| Phase 3 | 底物耗盡期 | smoothed_slope > μ + 0.5σ | 底物接近耗盡，ORP 回升 |

### 6.3 去抖動（Debounce）機制

相位切換後需**連續維持 30 分鐘**才接受切換，防止短暫越界觸發偽切換。

---

## 7. 週期級特徵萃取

**實作位置**：`ch4_peak_analysis.py` → `extract_cycle_features()`

以每個排氣週期為單位，萃取 11 個週期級統計特徵作為 CH4 峰值預測的輸入。

### 7.1 特徵列表

| 特徵名稱 | 說明 | 單位 |
|---------|------|-----|
| `cycle_length_min` | 週期總長 | min |
| `phase2_duration_min` | Phase 2 持續時間 | min |
| `phase2_fraction` | Phase 2 佔週期比例 | — |
| `phase1_mean_slope` | Phase 1 平均 ORP 斜率 | mV/min |
| `phase2_orp_mean` | Phase 2 ORP EMA 均值 | mV |
| `phase2_orp_std` | Phase 2 ORP EMA 標準差（穩定度指標） | mV |
| `phase2_macd_mean` | Phase 2 MACD 均值（動能） | mV |
| `orp_drop_magnitude` | Phase 1 ORP 下降幅度（起始值 − 最低值） | mV |
| `phase3_onset_fraction` | Phase 3 開始位置（佔週期比例） | — |
| `pressure_mean` | 週期平均反應器壓力 | kg/cm² |
| `ph_mean` | 週期平均 pH | — |

**備注**：`temp_mean` 已排除。實驗在恆溫 30°C 條件下進行，各週期溫度方差為零；StandardScaler 正規化後為全零列，對模型無貢獻且污染 GA 搜索空間。

### 7.2 排氣事件偵測

**方法**：`scipy.signal.find_peaks()`  
**參數**：
- `prominence = 10`（峰值需高出周圍基線 ≥ 10%）
- `distance = 60`（兩次排氣最短間隔 60 分鐘）

**資料集排氣事件**：訓練資料（2026-02-10 至 2026-03-27，共 46 天）中偵測到 **6 個完整排氣週期**。

---

## 8. CH4 峰值預測模型（離線分析）

### 8.1 遺傳演算法特徵選擇（GA）

**實作位置**：`ch4_peak_analysis.py` → `ga_feature_selection()`

| 參數 | 值 |
|-----|---|
| 染色體編碼 | 長度 11 二進制向量（1 = 選用） |
| 族群大小 | 20 |
| 最大世代數 | 40 |
| 交配率 | 0.7（Single-point crossover） |
| 突變率 | 0.15（Bit-flip） |
| 選擇策略 | Tournament selection（size=3） |
| 精英策略 | 每代保留最佳 1 個個體 |
| 適應度函式 | LOO-CV RMSE（越小越好，取負值轉最大化問題） |
| 評估模型 | Ridge Regression（α = 1.0） |

**搜索空間**：2¹¹ = 2,048 種特徵組合

**收斂結果**：第 5 代達到最佳解，選出 **5/11 個特徵**。

### 8.2 GA 選出特徵（5個）

根據 LOO-CV RMSE 最小化選出：

| 特徵 | 生物意義 |
|-----|---------|
| `phase2_duration_min` | 甲烷菌活躍時間長短影響累積氣量 |
| `phase2_orp_mean` | 活躍期平均氧化還原狀態 |
| `orp_drop_magnitude` | 底物消耗程度的代理指標 |
| `pressure_mean` | 週期內累積壓力 |
| `ph_mean` | CO₂溶解與CH₄轉換的代謝狀態指標（見備注） |

**備注 - ph_mean 的生物意義**：pH 並非過適特徵。其重要性具有明確生化基礎：CO₂溶於水（CO₂ + H₂O → H₂CO₃）導致 pH 下降；嗜氫甲烷菌將 CO₂轉換為 CH₄後，酸性消耗使 pH 回升。因此 pH 均值確實反映代謝進程，是對 CH4 峰值有預測力的生物指標。Random Forest 特徵重要性分析中 ph_mean 排名最高，與生物機制相符。GA 未選 ph_mean 的原因在於小樣本（n=6）LOO-CV 優化偏好泛化更穩健的週期結構特徵，兩種選擇均有其合理性。

### 8.3 模型比較（LOO-CV）

**統計限制**：n=6 個完整週期，LOO-CV 每折僅 5 筆訓練資料。所有結論反映方法論可行性，非最終預測精度指標。建議累積 ≥ 30 個排氣週期後重新評估。

| 模型 | 特徵集 | LOO-CV RMSE |
|-----|-------|------------|
| Ridge Regression | 全部 11 個特徵 | — |
| **Ridge Regression** | **GA 選出 5 個特徵** | **3.13%** ← 主要結果 |
| Random Forest | 全部 11 個特徵 | — |
| Random Forest | GA 選出 5 個特徵 | — |

### 8.4 LOO-CV 逐輪誤差（Ridge + GA 特徵）

RMSE 計算：$\text{RMSE} = \sqrt{\frac{\sum_{i=1}^{6} e_i^2}{6}} = \sqrt{\frac{58.642}{6}} = \sqrt{9.774} = 3.13\%$

| 週期 | 實際 CH4 峰值 | 預測值 | 誤差 | 備注 |
|-----|------------|-------|------|-----|
| C1 | — | — | −0.41% | 正常範圍 |
| C2 | 51.0% | 56.71% | −5.71% | 最大誤差（e²=32.60） |
| C3 | — | — | −0.17% | 正常範圍 |
| C4 | — | — | +1.51% | 正常範圍 |
| C5 | — | — | +3.71% | 正常範圍 |
| C6 | — | — | +3.13% | 正常範圍 |

C2 誤差偏大的可能原因：排氣時機處於週期異常狀態，或該週期資料包含感測器突波干擾。

---

## 9. LSTM 即時預測模型

### 9.1 模型架構（`core/model.py` → `ReactorLSTM`）

```
輸入層：(batch, 30, 6)     ← 30 分鐘滑動視窗，6 個特徵
   │
   ▼
LSTM Layer 1 (hidden=64)
   │
   ▼
LSTM Layer 2 (hidden=64)   ← 雙層 LSTM，batch_first=True
   │
   ▼
Linear(64 → 2)             ← 取最後時間步的隱藏狀態
   │
   ▼
輸出層：(batch, 2)
   ├─ output[0]：反應器壓力 t+5 (kg/cm²)
   └─ output[1]：CH4 濃度 t+5 (%)
```

### 9.2 輸入特徵（6維，`inference.py`）

| 特徵 | 來源 | 說明 |
|-----|-----|------|
| `orp_ema` | 衍生 | ORP EMA(10)，α=2/11 |
| `orp_slope` | 衍生 | (ema[t]−ema[t−5])/5，mV/min |
| `orp_macd` | 衍生 | EMA(5)−EMA(30) |
| `ph` | 感測器原始值 | 溶液 pH |
| `temp` | 感測器原始值 | 反應槽溫度 (°C) |
| `pressure` | 感測器原始值 | 反應器壓力 (kg/cm²) |

### 9.3 訓練設定（`train.py`）

| 超參數 | 值 |
|-------|---|
| 資料切割 | 70% 訓練 / 15% 驗證 / 15% 測試（時序順序切割，禁止 shuffle） |
| 序列長度（SEQ_LEN） | 30 個時間步（= 30 分鐘） |
| 預測距離（predict_ahead） | 5（預測 t+5 時間點） |
| Epochs | 最多 80，Early Stopping patience=10 |
| Batch Size | 128 |
| Optimizer | Adam，lr = 0.001 |
| Loss Function | MSELoss |
| Scaler | MinMaxScaler（僅用訓練集 fit，防止資料洩漏） |

**訓練結果**：
- Best Val Loss：0.0041
- Test Loss：0.0041（泛化差距 < 1%，模型泛化良好）

### 9.4 推論緩衝區（`inference.py`）

| 參數 | 值 | 說明 |
|-----|---|------|
| `sensor_buffer` maxlen | 65 筆 | 環形緩衝區 |
| `MIN_BUF` | 35 筆 | SEQ_LEN(30) + WARMUP(5)，斜率計算所需前置點 |
| `SEQ_LEN` | 30 | LSTM 輸入視窗長度 |
| `WARMUP` | 5 | slope 計算額外前置點數 |

未達 MIN_BUF(35) 筆時，API 回傳狀態 `資料緩衝中 (X/35)`，不進行推論。

### 9.5 輸出後處理

**輸出平滑**：對推論結果施加 EMA（α = 0.5），減少單點抖動：

$$\hat{p}_t^{\text{smooth}} = 0.5 \cdot \hat{p}_t^{\text{raw}} + 0.5 \cdot \hat{p}_{t-1}^{\text{smooth}}$$

**遲滯警報邏輯（Hysteresis）**：

| 狀態 | 觸發條件 |
|-----|---------|
| 危險 (Danger) | 連續 3 次原始預測壓力均 > 2.6 kg/cm² **且**最新值 ≥ 最舊值（確認上升趨勢） |
| 警告 (Warning) | EMA 平滑壓力 > 2.4 kg/cm² **或**近 3 筆預測斜率 > 0.05 |
| 正常 (Normal) | 不符合以上任一條件 |

---

## 10. 邊緣部署架構

### 10.1 通訊架構

```
感測器 (USB Serial)
    │  /dev/ttyUSB0, 9600 bps
    ▼
Jetson Orin Nano
    ├── FastAPI (uvicorn)     port 8000   ← HTTP REST API
    ├── MQTT Broker           port 1883   ← 訊息佇列
    └── MQTT Client (paho)
            ├── SUB: reactor/01/sensors   ← 接收感測資料
            └── PUB: reactor/01/prediction ← 發布預測結果

Vue3 前端 (Web Browser)
    └── HTTP GET/POST → FastAPI port 8000
```

### 10.2 MQTT 設定（`core/mqtt_client.py`）

| 項目 | 值 |
|-----|---|
| Protocol | MQTTv5 (`CallbackAPIVersion.VERSION2`) |
| Broker IP | localhost（Broker 安裝於 Jetson 本機） |
| Port | 1883 |
| Client ID | `Jetson_Backend` |
| 訂閱主題 | `reactor/01/sensors` |
| 發布主題 | `reactor/01/prediction` |
| Keep-alive | 60 秒 |

### 10.3 MQTT 訊息格式

**訂閱（感測資料輸入）**：
```json
{
  "orp": 568.0,
  "ph": 7.08,
  "temp": 30.0,
  "pressure": 2.34
}
```

**發布（預測結果輸出）**：
```json
{
  "device": "Jetson Orin Nano",
  "current_pressure_kg_cm2": 2.34,
  "predicted_pressure_5min": 2.51,
  "predicted_ch4_5min": 48.3,
  "status": "正常 (Normal)",
  "inference_time_ms": 12.3
}
```

### 10.4 FastAPI 應用設定（`main.py`）

| 項目 | 值 |
|-----|---|
| Framework | FastAPI + uvicorn |
| Host | 0.0.0.0 |
| Port | 8000 |
| CORS | allow_origins=["*"]（邊緣部署場景） |
| API prefix | `/api` |
| Startup 順序 | 1. 載入 LSTM 模型 → 2. 啟動 MQTT Client → 3. 啟動 USB Listener |

---

## 11. REST API 規格

### 11.1 端點列表

| 方法 | 路徑 | 功能 |
|-----|------|-----|
| GET | `/api/predict_pressure` | 取得 LSTM 即時預測結果 |
| POST | `/api/upload_sensor` | 上傳單筆感測資料並觸發推論 |
| GET | `/api/records` | 取得所有感測記錄（時序排序） |
| POST | `/api/records` | 新增單筆感測記錄 |
| DELETE | `/api/records` | 清空所有記錄 |
| DELETE | `/api/records/{id}` | 刪除指定記錄 |
| GET | `/api/report/stats` | 取得統計分析資料（用於報表） |
| GET | `/api/analysis` | 取得 ORP 穩態特徵分析 |
| POST | `/api/import_csv` | 批次匯入 CSV 感測記錄 |

### 11.2 `GET /api/predict_pressure` 回應格式

```json
{
  "device": "Jetson Orin Nano",
  "current_pressure_kg_cm2": 2.34,
  "predicted_pressure_5min": 2.51,
  "predicted_ch4_5min": 48.3,
  "status": "正常 (Normal)",
  "inference_time_ms": 12.3,
  "message": "系統穩定運行中"
}
```

| 欄位 | 型別 | 說明 |
|-----|------|------|
| `current_pressure_kg_cm2` | float | 目前實際壓力 |
| `predicted_pressure_5min` | float | EMA 平滑後 t+5 預測壓力 |
| `predicted_ch4_5min` | float | EMA 平滑後 t+5 預測 CH4% |
| `status` | string | 正常 / 警告 / 危險 / 模型未載入 / 資料緩衝中 |
| `inference_time_ms` | float | 推論耗時（毫秒） |

### 11.3 `GET /api/report/stats` 回應格式

```json
{
  "summary": {
    "total_records": 66240,
    "anomaly_count": 312,
    "anomaly_rate": 0.5,
    "orp_mean": 567.3,
    "orp_std": 15.2,
    "pressure_mean": 1.832,
    "pressure_max": 3.15,
    "ch4_mean": 28.4
  },
  "orp_histogram": { "bins": [...], "counts": [...] },
  "pressure_histogram": { "bins": [...], "counts": [...] },
  "correlation": { "labels": ["ORP","pH","溫度","壓力","CH4","CO2"], "matrix": [[...]] },
  "anomaly_by_date": [{ "date": "2026-02-10", "total": 1440, "anomalies": 8 }],
  "gas_daily": [{ "date": "2026-02-10", "avg_ch4": 31.2, "avg_co2": 2.1 }],
  "orp_ph_scatter": [{ "orp": 565.0, "ph": 7.08, "ch4": 48.3 }]
}
```

---

## 12. 前端介面規格

**框架**：Vue 3 + Composition API  
**入口**：`web_frontend/src/App.vue`

### 12.1 MonitorView（即時監控）

**路徑**：`src/views/MonitorView.vue`  
**功能**：即時顯示感測器數值、LSTM 預測結果、ORP 趨勢圖、警報狀態

| 顯示元件 | 資料來源 | 更新頻率 |
|--------|---------|---------|
| 目前壓力 / 壓力 CH4 預測 | `GET /api/predict_pressure` | 每分鐘輪詢 |
| ORP 即時趨勢圖 | `GET /api/records` | 每分鐘輪詢 |
| 警報狀態指示燈 | status 欄位判斷 | 即時 |
| CSV 匯入功能 | `POST /api/import_csv` | 手動觸發 |

### 12.2 ReportView（分析報表）

**路徑**：`src/views/ReportView.vue`  
**功能**：離線資料統計分析、圖表展示

| 圖表類型 | 說明 |
|--------|------|
| ORP 分布直方圖（24 bins） | 感測值分布分析 |
| 壓力分布直方圖（24 bins） | 操作壓力分析 |
| 6×6 相關係數熱力圖 | ORP/pH/溫度/壓力/CH4/CO2 相互關係 |
| 每日異常率長條圖 | 逐日突波事件統計 |
| CH4 / CO2 日均值趨勢折線圖 | 氣體產出長期趨勢 |
| pH-ORP 散點圖（最多 600 點） | 代謝狀態相關性 |

---

## 13. 效能指標

### 13.1 CH4 峰值預測（Ridge + GA，LOO-CV）

| 指標 | 值 |
|-----|---|
| 方法 | Ridge Regression（α=1.0）+ LOO-CV |
| 訓練樣本數 | 6 個完整排氣週期 |
| 選用特徵數 | 5 / 11 |
| LOO-CV RMSE | **3.13%** |
| 最大單輪誤差 | 5.71%（C2 週期） |

### 13.2 LSTM 即時預測

| 指標 | 值 |
|-----|---|
| 輸入維度 | (batch, 30, 6) |
| 輸出維度 | (batch, 2)：壓力 + CH4% |
| Best Val Loss (MSE) | 0.0041 |
| Test Loss (MSE) | 0.0041 |
| 泛化差距 | < 1% |
| 推論平台 | Jetson Orin Nano（CPU 模式） |

### 13.3 訊號處理

| 指標 | 值 |
|-----|---|
| EMA 平滑因子 α | 0.1818（N=10） |
| 突波偵測閾值 | −20 mV/min |
| 最大突波修復時間 | 15 分鐘 |

---

## 14. 已知限制與建議

### 14.1 採樣頻率限制（關鍵）

**問題**：系統採樣頻率為 **1 筆/分鐘**。排氣事件（開閥放氣）通常僅持續數秒，實際 CH4 瞬間峰值可能未被任何一筆記錄所捕捉。

**影響**：CSV 中所記錄的 CH4 峰值為**排氣後的穩定讀數**，而非排氣瞬間的最高濃度值。

**建議**：
- 若需精確量測 CH4 排放峰值，採樣頻率應提升至 ≥ 1 筆/5 秒
- 可另外設置觸發式高頻採樣（在排氣閥動作訊號後啟動）

### 14.2 樣本量限制

**問題**：CH4 峰值預測模型僅使用 6 個完整排氣週期作為訓練資料，LOO-CV 每折僅 5 筆，統計可信度受限。

**影響**：模型泛化能力無法充分驗證，RMSE = 3.13% 反映方法論可行性，非實際部署精度。

**建議**：累積 ≥ 30 個排氣週期後重新訓練，屆時可改用 k-fold CV 取代 LOO-CV。

### 14.3 系統運行假設

| 假設 | 說明 |
|-----|------|
| 恆溫實驗 | 溫度固定 30°C，溫度特徵在 GA/LSTM 中貢獻極低 |
| 單一反應器 | 目前系統僅支援一台反應器（MQTT topic: reactor/01） |
| 記憶體存儲 | sensor_records 存於記憶體，重啟後清空（需重新匯入 CSV） |

---

## 15. 依賴套件清單

### 15.1 後端（`edge_backend/requirements.txt`）

| 套件 | 版本 | 用途 |
|-----|-----|------|
| fastapi | 0.110.0 | REST API 框架 |
| uvicorn | 0.27.1 | ASGI Web Server |
| pydantic | 2.6.3 | 資料驗證 |
| numpy | 1.24.4 | 數值計算 |
| pandas | 2.2.1 | 資料處理 |
| scikit-learn | 1.4.1.post1 | ML 模型（Ridge, RF, Scaler） |
| joblib | 1.3.2 | Scaler 序列化 |
| pyserial | ≥ 3.5 | USB 感測器接收 |
| paho-mqtt | ≥ 2.0.0 | MQTT 客戶端 |
| torch | ≥ 2.0.0 | LSTM 推論（Jetson 使用官方 CUDA 版本） |
| scipy | — | CH4 峰值偵測（find_peaks） |
| matplotlib | — | 離線報表圖表生成 |

### 15.2 前端（`web_frontend/package.json`）

| 套件 | 用途 |
|-----|-----|
| Vue 3 | 前端框架 |
| Vite | 開發建置工具 |

---

## 附錄 A：模型檔案路徑

| 檔案 | 路徑 | 說明 |
|-----|-----|------|
| LSTM 權重 | `edge_backend/core/weights/reactor_lstm_weights.pth` | PyTorch state_dict |
| 特徵 Scaler | `edge_backend/core/weights/scaler_x.pkl` | MinMaxScaler（6維輸入） |
| 目標 Scaler | `edge_backend/core/weights/scaler_y.pkl` | MinMaxScaler（2維輸出） |

**路徑解析機制**：`inference.py` 使用 `__file__` 絕對路徑定位，從任意工作目錄啟動均可正確載入：

```python
_BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEIGHTS_DIR = os.path.join(_BASE_DIR, "core", "weights")
```

## 附錄 B：訓練資料集概況

| 項目 | 值 |
|-----|---|
| 資料期間 | 2026-02-10 至 2026-03-27（46 天） |
| 總筆數 | 約 66,240 筆（46 天 × 1,440 min/day） |
| 排氣事件數 | 6 次 |
| CH4 峰值範圍 | 資料集中可觀測值 |
| 感測器突波率 | 約 0.5%（ORP 突波修復點） |
| 實驗溫度 | 恆溫 30°C |
| CSV 備份 | 逐日輪換，存於 `edge_backend/data/` |
