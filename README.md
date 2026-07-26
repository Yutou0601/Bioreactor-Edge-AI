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
- [CO2 溶解／生物消耗分離研究](#-co2-溶解生物消耗分離研究)
- [實驗執行與運維](#-實驗執行與運維)
- [技術規格](#-技術規格)
- [安裝與部署](#-安裝與部署)
- [使用說明](#-使用說明)
- [實驗成果](#-實驗成果)
- [專案結構](#-專案結構)
- [致謝](#-致謝)

---

## 📖 專案簡介

本系統建構於洪政源博士所開發的**微正壓循環生物甲烷化控制系統**之上，作為其智慧感測延伸層，針對氧化還原電位（ORP, Oxidation-Reduction Potential）訊號進行即時動態分析，並延伸為完整的**實驗執行、監看與研究分析平台**：

**即時監控與預測（前端呈現）**

1. **即時 ORP 訊號去雜訊**：在 Jetson 邊緣裝置上每分鐘完成突波排除與雙軌濾波
2. **自適應生物三相位偵測**：自動識別底物利用期（Phase 1）、活躍產甲烷期（Phase 2）、底物耗盡期（Phase 3）
3. **CH₄ 峰值預測與特徵歸因**：per-cycle 峰值預測（Ridge + 外插防護），特徵歸因採
   **XGBoost + TreeSHAP**（未安裝時自動退回 GA + Ridge）

**實驗執行與資料完整性**

4. **實驗批次管理 + 即時面板**：洗管線→進氣→循環→自動補氣→排氣的批次生命週期管理，
   自動偵測補氣循環、逐循環計算下降速率與斜率平緩化，並附**記錄健康度告警**
   （最後一筆資料距今多久、記錄中斷偵測——防止監控電腦靜默中斷）
5. **桌面控制台**：啟動／更新／健康度監看，現場不需開終端機

**研究分析（離線工具）**

6. **CO2 溶解／生物消耗分離**：以灰箱機理模型 + 可辨識性分析，回答「壓力下降中多少是
   物理溶解、多少是菌種消耗」，與「斜率平緩化是生物還是物理」

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

### 4. 預測層：CH₄ 峰值即時預測 + 特徵歸因

即時對「進行中的循環」預測排氣時的 CH₄ 峰值，並歸因哪些訊號在解釋它。
**設計上刻意誠實**——CH₄ 為參考級訊號（僅排氣瞬間有效，其餘 99.98% 為管路拖尾）、
歷史完整循環樣本極少，故一律附帶 `n_train`／`LOO-CV RMSE`／可靠度，並在下列情況
**不給預測值只說明原因**：

- **外插防護**：部分特徵隨循環進行才增長，進行中的循環等同外插。實測循環進度 4% 時
  預測值可達 703%（CH₄ 物理上不可能 >100%）；落在合理值域外一律不顯示。
- **進度門檻**：循環進度 <85% 不給預測值。
- **樣本門檻**：完整循環 <30 標為「參考級」。

#### 特徵歸因：XGBoost + TreeSHAP（未安裝時退回 GA + Ridge）

依前沿文獻（樹模型 + SHAP 為 anaerobic digestion 甲烷預測主流），特徵歸因採
**XGBoost + 內建 TreeSHAP**（`pred_contribs`，不需另裝 shap 套件）。部署考量：後端在
Jetson（ARM／資源受限），不強制安裝 xgboost——**裝了就用、沒裝自動退回 GA + Ridge**。

> **誠實標示**：n≈9–27 循環的小樣本下，樹模型高變異、LOO-CV RMSE 會**比 Ridge 高**
> （實測 5.3 vs 1.7）。XGBoost 的價值在**歸因更乾淨**（TreeSHAP 處理非線性），
> 不是這種樣本量的預測精度。前端面板與說明均據實標明此限制。

**退回路徑——特徵選擇：遺傳演算法（GA）**

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

## 🔬 CO2 溶解／生物消耗分離研究

本專案的核心科學問題：反應槽壓力下降量到的是**兩個機制的總和**——

- **物理溶解**：CO2 溶入液相（依亨利定律，趨近飽和即變慢）
- **生物消耗**：嗜氫甲烷菌消耗溶解態 CO2

歷史資料上 12 種分離方法均未通過決定性檢定。本專案不迴避這個結果，而是用機理模型
**釐清「為什麼難」**，並提供兩條難度不同、皆可執行的分析線。

### 關鍵結論：分離的困難是「結構性」的，與演算法無關

以兩狀態機理模型（物理項 kLa·驅動力 + 生物項 Monod）＋合成資料＋profile likelihood
做可辨識性測試（`co2_greybox_identifiability.py`）：

- **穩態下兩通量相等**（溶解通量 ≡ 生物消耗通量，是同一個數），從壓力下降無從分辨。
  物理速率 kLa 在穩態資料下信賴區間 **±160%**，含**暫態**的資料下收斂到 **±0%**。
- 因此分離的槓桿是**暫態**（液相遠離飽和、兩通量暫時解耦），不是更複雜的模型——
  **換 LSTM／PINN／更新的演算法都不會改變這個結構限制**。這是實驗設計問題。

### 兩條分析線

| | 關聯分析 | 機理分離 |
|---|---|---|
| 回答 | 平緩化**是不是**生物造成 | 溶解 vs 消耗**各多少** |
| 程式 | `co2_covariate_association.py` | `co2_greybox_identifiability.py` |
| 難度 | 中，**現有 9 批次即可** | 難，**需暫態段** |
| 統計 | 批次分群叢集穩健標準誤（處理偽重複） | profile likelihood + 殘差法 |
| 驗證 | 合成資料雙向驗證（生物/物理各判對） | 可辨識性已量化 |

對應的實驗設計調整（詳見 `docs/實驗設計_暫態分離協定_2026-07-26.md`）：補入純物理對照段、
換液後暫態窗口、打亂 n 順序 + 每日參考水準。

兩條分析線皆在前端提供「點按鈕即分析」：**共變數關聯**判讀平緩化成因；**灰箱機理**
給「可分離度就緒指標」——穩態資料回報「尚不可分離（需暫態）」，偵測到暫態循環
（下降速率遠快於穩態）時，以殘差法給出物理溶解／生物消耗佔比。

---

## 🧪 實驗執行與運維

### 實驗批次管理 + 即時面板

前端 `ExperimentView` 管理完整批次生命週期（已規劃→進行中→已完成），自動偵測補氣
循環並逐循環計算下降速率、斜率平緩化、進氣前 ORP（菌群成熟度共變數）。**資料完整性
是第一級指標**：

- **記錄健康度告警**：最後一筆資料距今多久、逾時轉紅——直接針對 2026-07-22 監控電腦
  自動更新導致資料靜默中斷 17.5 小時的事故設計。
- **記錄中斷偵測**：跨斷點的循環自動標記、排除於建模之外，避免產生假的「產甲烷」訊號。
- **兩層報表匯出**：批次彙整（含離散度 IQR）與每循環特徵（餵模型用）。
- **共變數關聯分析（點按鈕即分析）**：對當前每循環資料即時跑「進氣前 ORP → 下降速率／
  平緩化」回歸（批次分群叢集穩健標準誤處理偽重複），直接判讀**平緩化是生物還是物理**。

### 桌面控制台（`control_panel.pyw`）

純 Python 標準函式庫（tkinter），雙擊即開，現場不需開終端機：啟動／停止／重啟後端
（本機或遠端 Jetson via SSH 金鑰）、檢查更新、資料新鮮度監看、開機自動啟動。
後端死掉時網頁打不開，故這些功能刻意放在不依賴後端的桌面程式。

### 開發測試伺服器（`dev_test_server.py`）

在筆電上重現整套系統（真實後端 + 合成感測資料），不需 Jetson／MQTT／真實 CSV，
可模擬記錄中斷、時鐘不同步、排氣峰值等情境驗證前後端。

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
fastapi / uvicorn        # API 服務
torch                    # LSTM 壓力預測（Jetson 請用官方 CUDA 版）
numpy / pandas / scipy   # 數值/資料/Savitzky-Golay 濾波、統計
openpyxl                 # 報表匯出
paho-mqtt                # MQTT 通訊
pyserial                 # 感測器串列通訊
xgboost                  # 選配：CH4 特徵歸因（TreeSHAP）；未裝自動退回 GA+Ridge
```

> **可辨識性與關聯分析（`co2_*.py`）刻意只用 numpy + scipy**，不依賴 sklearn——
> 實測 sklearn 的編譯 DLL 在部分機器會被系統 Application Control 政策擋住無法載入；
> Ridge 以純 numpy 閉式解實作。

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
Bioreactor-Edge-AI/
│
├── control_panel.pyw                # 桌面控制台（啟動/更新/健康度監看，tkinter）
├── 控制台.bat                        # 控制台啟動器（避開 .pyw 關聯失效）
├── dev_test_server.py               # 開發測試伺服器（真實後端+合成資料，不需 Jetson）
├── start_all.bat / sync_jetson.bat  # 舊版一鍵啟動/同步（保留為後備）
│
├── edge_backend/
│   ├── main.py                      # FastAPI 入口
│   ├── requirements.txt
│   │
│   ├── api/
│   │   ├── routes.py                # 所有 API 端點（含 /ch4_prediction /phase
│   │   │                            #   /covariate_analysis /experiment/* /health）
│   │   └── schemas.py
│   │
│   ├── core/                        # 即時後端核心（部署到 Jetson）
│   │   ├── data_store.py            # 共用記憶體感測資料倉儲
│   │   ├── signal_processor.py      # 突波排除 + EMA/SG 濾波
│   │   ├── feature_extractor.py     # 穩態/相位特徵萃取
│   │   ├── inference.py / model.py  # LSTM 壓力預測
│   │   ├── ch4_realtime.py          # CH4 峰值預測 + XGBoost/SHAP 歸因（退回 GA+Ridge）
│   │   ├── experiment_store.py      # 實驗批次資料模型（循環偵測/斷點/共變數）
│   │   ├── experiment_report.py     # 兩層報表匯出（批次彙整/每循環）
│   │   └── mqtt_client.py
│   │
│   ├── co2_greybox_identifiability.py  # 機理分離：決定性測試(離線) + 前端可分離度指標
│   ├── co2_covariate_association.py    # 【離線+API】共變數關聯分析（平緩化成因）
│   ├── co2_separation_analysis.py      # 【離線】分離分析工具集
│   ├── co2_relaxation_analysis.py      # 【離線】弛豫振盪器分析（含證偽死路）
│   ├── ch4_peak_analysis.py            # 【離線】CH4 峰值 cycle/minute-level 分析
│   ├── batch_import_csv.py / csv_watcher.py / usb_receiver.py  # 資料匯入/監看/接收
│   └── sensor_simulator.py / train.py / export_onnx.py
│
├── web_frontend/                    # Vue3 + Vite（部署到監控電腦）
│   └── src/views/
│       ├── MonitorView.vue          # 即時監控（ORP/相位/LSTM）
│       ├── ReportView.vue           # 歷史分析
│       └── ExperimentView.vue       # 實驗批次管理 + 即時面板 + CH4 預測
│                                    #   + 特徵歸因 + 共變數關聯分析（點按鈕即分析）
│
├── docs/                            # 日報、實驗設計、技術備忘、證據鏈、簡報
│
└── README.md
```

> 標【離線】者為研究分析工具，吃實驗完整資料、輸出統計結論。其中兩支另在前端
> 提供「點一下即分析」：`co2_covariate_association.py`（`/covariate_analysis`，平緩化
> 成因）與 `co2_greybox_identifiability.py`（`/greybox_analysis`，可分離度就緒指標）。

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
