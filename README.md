# 基於邊緣運算之 ORP 動態分析為基礎的生物甲烷化即時監控與峰值預測系統

<div align="center">

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.8+-green.svg)
![Platform](https://img.shields.io/badge/Platform-Jetson%20Orin%20Nano-orange.svg)
![Framework](https://img.shields.io/badge/Frontend-Vue3-brightgreen.svg)

**財團法人金屬工業研究發展中心 × 國立高雄科技大學**

本系統為經濟部產發署 115 年度「半導體創新技術與產業應用驅動智匯菁英計畫」之實務專題成果，
由財團法人金屬工業研究發展中心（系統處光電技術組）指導，國立高雄科技大學學生執行完成。

</div>

---

## 📋 目錄

- [專案簡介](#-專案簡介)
- [計畫背景](#-計畫背景)
- [系統架構](#-系統架構)
- [核心演算法](#-核心演算法)
- [技術規格](#-技術規格)
- [安裝與部署](#-安裝與部署)
- [使用說明](#-使用說明)
- [實驗成果](#-實驗成果)
- [專案結構](#-專案結構)
- [致謝](#-致謝)

---

## 📖 專案簡介

本系統建構於洪政源博士所開發的**微正壓循環生物甲烷化控制系統**之上，作為其智慧感測延伸層，針對氧化還原電位（ORP, Oxidation-Reduction Potential）訊號進行即時動態分析，實現以下三個核心功能：

1. **即時 ORP 訊號去雜訊**：在 Jetson 邊緣裝置上每分鐘完成突波排除與雙軌濾波
2. **自適應生物三相位偵測**：自動識別底物利用期（Phase 1）、活躍產甲烷期（Phase 2）、底物耗盡期（Phase 3）
3. **CH₄ 峰值預測**：結合 LSTM 即時監控與遺傳演算法（GA）+ Ridge Regression 的 per-cycle 峰值預測

生物甲烷化核心反應式：

```
CO₂ + 4H₂ → CH₄ + 2H₂O
```

實驗驗證可於 7 天內達到 **70% CH₄** 濃度。

---

## 🏛️ 計畫背景

| 項目 | 內容 |
|------|------|
| **主辦單位** | 財團法人工業技術研究院 電子與光電系統研究所 產業發展推動組 |
| **實務能力執行單位** | 財團法人金屬工業研究發展中心 / 系統處光電技術組 |
| **執行計畫** | 半導體設備與製程能力暨邊緣智慧實務能力發展 |
| **指導單位** | 財團法人金屬工業研究發展中心 |
| **指導老師** | 洪政源 博士 |
| **執行學校** | 國立高雄科技大學 |
| **執行學生** | 李承育（三年級） |
| **計畫年度** | 經濟部產發署 115 年度 |

---

## 🏗️ 系統架構

系統分為四個層次，形成完整的端到端 Pipeline：

```
┌─────────────────────────────────────────────────────────┐
│                     感測器端 Sensor                      │
│   ORP 感測器 → Raw Data (1 min/筆) → USB/Type-C 傳輸    │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│             邊緣運算端 Jetson Orin Nano                   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │              第一階段：資料前處理                  │   │
│  │  通訊協議解析 → 突波排除 → 雙軌濾波平滑化         │   │
│  │         ┌──────────┐    ┌──────────────┐         │   │
│  │         │  EMA     │    │Savitzky-Golay│         │   │
│  │         │ (即時)   │    │  (歷史報表)  │         │   │
│  │         └────┬─────┘    └──────┬───────┘         │   │
│  └──────────────┼─────────────────┼─────────────────┘   │
│                 │                 │                      │
│  ┌──────────────▼─────────────────▼─────────────────┐   │
│  │             第二階段：特徵分析與預測               │   │
│  │                                                   │   │
│  │  自適應生物相位偵測 (Phase 1 / 2 / 3)             │   │
│  │              │                                   │   │
│  │  週期特徵工程 (11 個候選特徵)                     │   │
│  │              │                                   │   │
│  │  GA 特徵選取 (選出 5/11)                         │   │
│  │              │                                   │   │
│  │  ┌───────────┴───────────┐                       │   │
│  │  │  Ridge CH₄ 峰值預測  │  LSTM 即時監控 (+5min) │   │
│  │  │  LOO-CV RMSE = 3.13% │  壓力 / CH₄ 預測      │   │
│  │  └───────────────────────┘                       │   │
│  └──────────────────────┬────────────────────────────┘   │
│                         │ MQTT Broker                    │
└─────────────────────────┼───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                   前端呈現層 Vue3                         │
│  ┌─────────────────────┐  ┌──────────────────────────┐  │
│  │    MonitorView      │  │      ReportView           │  │
│  │  即時監控           │  │  歷史分析                 │  │
│  │  LSTM 壓力/CH₄ 預測 │  │  ORP 訊號 / 統計報表     │  │
│  └─────────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 🧠 核心演算法

### 1. 訊號處理層：EMA 與 Savitzky-Golay

#### 指數移動平均（EMA）— 用於即時監控

ORP 感測器受液體攪動與氣泡通過影響，原始訊號含有瞬間突波。EMA 為因果濾波器，記憶體開銷 O(1)，適合邊緣裝置即時運算。

```
ema[t] = α · x[t] + (1 - α) · ema[t-1]
α = 2 / (N + 1)，N = 10
```

突波偵測機制：若 `|x[t] - ema[t-1]| > θ`，以線性插值取代，防止突波污染 EMA。

同步計算衍生特徵：
- `slope[t]`：ORP 一階微分，反映變化速率
- `MACD[t]`：EMA(10) − EMA(60)，捕捉短期相對長期的動能變化

#### Savitzky-Golay 濾波器（W=11, d=2）— 用於歷史報表

最小平方目標函數：

```
min Σ[τ=-5 to 5] [x[t+τ] - (a₀ + a₁τ + a₂τ²)]²
```

視窗中心點平滑輸出：`p(0) = a₀`，無相位滯後，保留峰值形狀。

---

### 2. 狀態層：自適應生物三相位偵測

以當前週期斜率統計量 μ、σ 作為動態閾值，取代固定常數，適應不同批次實驗條件（初始壓力 0.896～1.5 kg/cm²）。

| 相位 | 觸發條件 | 生物意義 |
|------|----------|----------|
| Phase 1 | slope < μ − k·σ | 嗜氫甲烷菌消耗 H₂/CO₂，建立還原環境，ORP 急降 |
| Phase 2 | μ − k·σ ≤ slope ≤ μ + k·σ | 產甲烷活躍期，CH₄ 濃度持續上升 |
| Phase 3 | slope > μ + k·σ | 底物耗盡，ORP 回升，接近最佳排氣時機 |

演算流程：

```
原始 ORP 序列
    │
    ▼
Step 1: EMA(10) 計算 slope[t]
    │
    ▼
Step 2: 60 min 滾動平均（宏觀平滑）
    │
    ▼
Step 3: 計算自適應閾值 μ ± k·σ（k = 1.5）
    │
    ▼
Step 4: 初始相位標記 Phase 1 / 2 / 3
    │
    ▼
Step 5: 30 min Debounce（防假切換）
    │
    ▼
輸出相位標籤序列
```

---

### 3. 預測層：LSTM 即時監控

雙層 LSTM 架構，預測未來 +5 分鐘的壓力與 CH₄ 濃度：

```
輸入張量 (batch, 30, 6)
特徵：EMA, Slope, MACD, pH, 溫度, 壓力
    │
    ▼
LSTM Layer 1（Hidden Size: 64）
輸出全部 30 步隱藏狀態
    │
    ▼
LSTM Layer 2（Hidden Size: 64）
只取最後步 h[29]（Many-to-One）
    │
    ▼
Linear Layer（64 → 2）
    │
    ▼
輸出：[壓力(t+5), CH₄%(t+5)]
```

| 參數 | 數值 |
|------|------|
| 總參數量 | 51,330 |
| Val Loss | ~0.0041 |
| Test Loss | ~0.0041 |
| 泛化差距 | 0.1%（無 overfitting） |
| 推論耗時 | 75.8 ms |

---

### 4. 預測層：GA + Ridge CH₄ 峰值預測

#### 特徵選擇：遺傳演算法（GA）

搜索空間 2¹¹ = 2048 種特徵子集，以 LOO-CV RMSE 作為適應度函數：

```
初始族群（20 個 11-bit 染色體）
    │
    ▼
適應度評估（Ridge LOO-CV RMSE）
    │
    ▼
終止條件（40 代）─── 是 ──→ 輸出最佳特徵子集
    │ 否
    ▼
遺傳演化操作
  - 錦標賽選擇
  - 單點交配
  - 位元翻轉突變
  - 精英保留
    │
    └──→ 回到適應度評估
```

實際收斂於第 **5 代**，選出 5/11 特徵：

| 特徵名稱 | 生物意義 |
|----------|----------|
| `cycle_length_min` | 排氣週期總長（分鐘），反映菌群整體消耗速率 |
| `phase2_duration_min` | Phase 2 持續時長，產甲烷活躍期長度 |
| `phase2_fraction` | Phase 2 佔週期比例，越高代表產氣越穩定 |
| `phase3_onset_fraction` | Phase 3 起始相對時間，越晚代表菌群越活躍 |
| `pressure_mean` | 週期內平均壓力，越高代表累積氣體越多 |

#### 迴歸模型：Ridge Regression + LOO-CV

在 n=6 小樣本下，LOO-CV 是統計上最可靠的驗證策略：

| 輪次 | 測試週期 | 實際 CH₄ | 預測 CH₄ | 誤差 |
|------|----------|----------|----------|------|
| 第 1 輪 | C1 | 66.2% | 65.81% | −0.41% |
| 第 2 輪 | C2 | 65.2% | 59.45% | −5.71% |
| 第 3 輪 | C3 | 52.8% | 52.60% | −0.17% |
| 第 4 輪 | C4 | 51.9% | 53.42% | +1.51% |
| 第 5 輪 | C5 | 33.9% | 37.58% | +3.71% |
| 第 6 輪 | C6 | 48.1% | 51.28% | +3.13% |
| **平均** | — | — | — | **RMSE ≈ 3.13%** |

---

## ⚙️ 技術規格

### 硬體需求

| 元件 | 規格 |
|------|------|
| 邊緣運算平台 | NVIDIA Jetson Orin Nano |
| ORP 感測器 | 電化學 ORP 感測器，採樣頻率 1 min/筆 |
| 氣體感測器 | CH₄ / CO₂ 濃度感測器 |
| 壓力感測器 | 反應器壓力感測器 |
| 傳輸介面 | USB / Type-C |

### 軟體依賴

#### 後端（Jetson 端）

```
Python >= 3.8
torch >= 1.10.0          # LSTM 模型推論
numpy >= 1.21.0          # 數值運算
pandas >= 1.3.0          # 資料處理
scipy >= 1.7.0           # Savitzky-Golay 濾波器
scikit-learn >= 0.24.0   # Ridge Regression
paho-mqtt >= 1.6.0       # MQTT 通訊
pyserial >= 3.5          # 感測器串列通訊
```

#### 前端（Vue3）

```
vue >= 3.0.0
vite >= 4.0.0
mqtt.js >= 4.3.0         # MQTT 訂閱
echarts >= 5.0.0         # 圖表渲染
axios >= 1.0.0           # HTTP 請求
```

---

## 🚀 安裝與部署

### Step 1：Clone 專案

```bash
git clone https://github.com/your-repo/biomethanation-edge-monitor.git
cd biomethanation-edge-monitor
```

### Step 2：安裝後端依賴

```bash
cd backend
pip install -r requirements.txt
```

### Step 3：安裝並啟動 MQTT Broker

```bash
# 以 Mosquitto 為例
sudo apt-get install mosquitto mosquitto-clients
sudo systemctl start mosquitto
sudo systemctl enable mosquitto
```

### Step 4：設定感測器串列埠

編輯 `backend/config.yaml`：

```yaml
sensor:
  port: /dev/ttyUSB0       # 依實際串列埠調整
  baudrate: 9600
  sampling_interval: 60    # 秒

mqtt:
  broker: localhost
  port: 1883
  topics:
    orp: sensor/orp
    ch4: sensor/ch4
    pressure: sensor/pressure
    prediction: model/prediction
    phase: model/phase

ema:
  N: 10                    # EMA 視窗大小

phase_detection:
  k: 1.5                   # 自適應閾值靈敏度係數
  debounce_min: 30         # 防抖動視窗（分鐘）

savitzky_golay:
  window_length: 11
  polyorder: 2

lstm:
  model_path: models/lstm_model.pt
  lookback: 30             # 過去 30 分鐘
  predict_ahead: 5         # 預測未來 5 分鐘

ridge:
  model_path: models/ridge_model.pkl
  ga_features: models/ga_selected_features.json
```

### Step 5：啟動後端 Pipeline

```bash
cd backend
python main.py
```

### Step 6：安裝並啟動前端

```bash
cd frontend
npm install
npm run dev
```

前端預設開啟於 `http://localhost:5173`

### Step 7：（選用）載入預訓練模型

如需使用已訓練好的 LSTM 與 Ridge 模型：

```bash
cd backend
python scripts/load_pretrained.py --lstm models/lstm_model.pt --ridge models/ridge_model.pkl
```

如需重新訓練：

```bash
# 訓練 LSTM
python scripts/train_lstm.py --data data/historical_orp.csv

# 執行 GA 特徵選擇並訓練 Ridge
python scripts/train_ridge_ga.py --data data/cycle_features.csv
```

---

## 📊 使用說明

### MonitorView（即時監控）

開啟前端後，預設進入 MonitorView，提供以下資訊：

- **即時 ORP 曲線**：原始訊號、去突波資料、EMA、S-G 四條曲線疊加顯示
- **生物相位標記**：Phase 1（紅）/ Phase 2（綠）/ Phase 3（橘）即時色塊
- **LSTM 預測儀表板**：即時壓力、預測 +5min 壓力、預測 +5min CH₄%、推論耗時
- **反應狀態摘要**：自動生成文字描述（穩態 / 急降 / 回升），並顯示基準漂移率

### ReportView（歷史分析）

點擊上方 Tab 切換至 ReportView，提供以下功能：

- **ORP 歷史曲線**：可選擇任意時間範圍，支援 S-G 無滯後平滑顯示
- **ORP 分佈直方圖**：EMA 平滑後的訊號分佈統計
- **反應器壓力分佈**：標記超過安全閾值的高壓事件
- **特徵相關係數熱力圖**：ORP、pH、溫度、壓力、CH₄、CO₂ 的 Pearson 相關矩陣
- **每日突波統計**：正常筆數 vs. 突波筆數的每日對比

### CH₄ 峰值預測

每個排氣週期結束後，系統自動執行 GA 特徵提取與 Ridge 預測，結果顯示於：

```
MonitorView → 週期摘要面板 → 本週期預測 CH₄ 峰值：XX.X%
```

---

## 📈 實驗成果

### 訊號處理效果

| 指標 | 結果 |
|------|------|
| 突波排除率 | 接近 100%（一階差分閾值法） |
| EMA 推論耗時 | < 1 ms/筆（O(1) 遞迴計算） |
| S-G 批次處理速度 | 8,862 筆資料 < 1 秒 |

### 相位偵測效果

| 指標 | 結果 |
|------|------|
| 適用壓力範圍 | 0.896 ～ 1.5 kg/cm² |
| Debounce 窗口 | 30 min（防假切換） |
| Phase 1 平均偵測延遲 | < 5 min |

### CH₄ 峰值預測效果

| 模型 | LOO-CV RMSE | 備註 |
|------|-------------|------|
| **Ridge + GA（本研究）** | **3.13%** | 5/11 特徵，5 代收斂 |
| Random Forest | 10.17% | n=6 小樣本 overfitting |

### LSTM 即時監控效果

| 指標 | 數值 |
|------|------|
| Val Loss | ~0.0041 |
| Test Loss | ~0.0041 |
| 泛化差距 | 0.1% |
| 推論耗時（Jetson Orin Nano） | 75.8 ms |

---

## 📁 專案結構

```
biomethanation-edge-monitor/
│
├── backend/
│   ├── main.py                      # 主程式入口
│   ├── config.yaml                  # 系統設定檔
│   ├── requirements.txt
│   │
│   ├── pipeline/
│   │   ├── sensor_reader.py         # 感測器資料讀取
│   │   ├── spike_remover.py         # 突波排除模組
│   │   ├── ema_filter.py            # EMA 濾波器
│   │   └── sg_filter.py             # Savitzky-Golay 濾波器
│   │
│   ├── phase_detection/
│   │   ├── adaptive_phase.py        # 自適應相位偵測
│   │   └── macd_calculator.py       # MACD 計算
│   │
│   ├── prediction/
│   │   ├── lstm_monitor.py          # LSTM 即時監控
│   │   ├── ga_feature_selector.py   # GA 特徵選擇
│   │   ├── ridge_predictor.py       # Ridge CH₄ 峰值預測
│   │   └── loo_cv.py                # LOO-CV 驗證工具
│   │
│   ├── mqtt/
│   │   └── publisher.py             # MQTT 發布模組
│   │
│   ├── models/
│   │   ├── lstm_model.pt            # 預訓練 LSTM 模型
│   │   ├── ridge_model.pkl          # 預訓練 Ridge 模型
│   │   └── ga_selected_features.json # GA 選出之特徵子集
│   │
│   └── scripts/
│       ├── train_lstm.py            # LSTM 訓練腳本
│       ├── train_ridge_ga.py        # Ridge + GA 訓練腳本
│       └── load_pretrained.py       # 載入預訓練模型
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js
│       ├── App.vue
│       ├── views/
│       │   ├── MonitorView.vue      # 即時監控視圖
│       │   └── ReportView.vue       # 歷史分析視圖
│       ├── components/
│       │   ├── ORPChart.vue         # ORP 訊號圖表
│       │   ├── PhaseIndicator.vue   # 相位指示器
│       │   ├── LSTMDashboard.vue    # LSTM 預測儀表板
│       │   ├── CorrelationHeatmap.vue # 特徵相關熱力圖
│       │   └── SpikeStats.vue       # 每日突波統計
│       └── utils/
│           └── mqtt_client.js       # MQTT 訂閱工具
│
├── data/
│   ├── historical_orp.csv           # 歷史 ORP 資料（範例）
│   └── cycle_features.csv           # 週期特徵資料（範例）
│
├── docs/
│   └── 簡報_李承育_115年邊緣智慧實務人才成果發表.pdf
│
└── README.md
```

---

## 🙏 致謝

本研究得以完成，特別感謝以下單位與人員的支持與指導：

- **財團法人金屬工業研究發展中心**（系統處光電技術組）提供實務執行環境、設備支援與技術指導
- **指導老師 洪政源 博士** 提供微正壓循環控制系統的硬體基礎，以及全程的研究方向指引
- **財團法人工業技術研究院** 電子與光電系統研究所 主辦本次實務人才培育計畫
- **經濟部產業發展署** 115 年度「半導體創新技術與產業應用驅動智匯菁英計畫」之經費支持

---

## 📄 授權

本專案採用 MIT License，詳見 [LICENSE](LICENSE) 文件。

學術引用請註明：

```
李承育（2026）。基於邊緣運算之ORP動態分析為基礎的生物甲烷化即時監控與峰值預測系統。
經濟部產發署115年度半導體創新技術與產業應用驅動智匯菁英計畫實務專題成果。
財團法人金屬工業研究發展中心 / 國立高雄科技大學。
```

---

<div align="center">

**財團法人金屬工業研究發展中心 指導**

**國立高雄科技大學 李承育 製作**

*經濟部產發署 115 年度 半導體創新技術與產業應用驅動智匯菁英計畫*

</div>
