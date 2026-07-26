# 基於邊緣運算之生物反應器即時 ORP 變化分析系統
## 技術規格與方法說明文件

**硬體平台**：NVIDIA Jetson Orin Nano  
**推論框架**：PyTorch 2.x（CUDA 加速）  
**後端框架**：FastAPI + Uvicorn  
**前端框架**：Vue 3 + ECharts 5  
**資料規模**：62,640 筆感測器記錄（2026-02-10 ～ 2026-03-27）

---

## 目錄

1. [系統架構概述](#1-系統架構概述)
2. [感測器資料格式](#2-感測器資料格式)
3. [訊號前處理管線](#3-訊號前處理管線)
4. [ORP 穩態與漂移分析](#4-orp-穩態與漂移分析)
5. [AI 壓力預測模型](#5-ai-壓力預測模型)
6. [特徵工程（推論端）](#6-特徵工程推論端)
7. [模型訓練流程](#7-模型訓練流程)
8. [三級告警系統](#8-三級告警系統)
9. [資料流與系統整合](#9-資料流與系統整合)
10. [REST API 端點規格](#10-rest-api-端點規格)
11. [前端視覺化方法](#11-前端視覺化方法)
12. [訓練結果與評估](#12-訓練結果與評估)
13. [已知限制與未來工作](#13-已知限制與未來工作)

---

## 1. 系統架構概述

本系統為運行於 Jetson Orin Nano 之邊緣 AI 系統，針對生物反應器的氧化還原電位（ORP, Oxidation-Reduction Potential）進行即時監控，並以 LSTM 神經網路預測未來 5 分鐘之反應器壓力與甲烷濃度，以提早警示操作人員進行干預。

```
[感測器 / USB]
      │ 逐筆串列資料（每分鐘 1 筆）
      ▼
[訊號前處理]  ──  突波偵測 → 線性內插 → EMA 平滑
      │
      ▼
[in-memory 資料倉儲]  sensor_records[]
      │
      ├── [特徵分析器]  → 穩態判定 / 漂移率  →  REST API /api/analysis
      │
      └── [LSTM 推論引擎]  sensor_buffer (deque, maxlen=65)
                │
                ▼
          特徵工程（6 維 × 30 步）
                │
                ▼
          MinMaxScaler 歸一化
                │
                ▼
          ReactorLSTM（2 層, hidden=64）
                │
                ▼
          Inverse Transform → 輸出平滑 → 遲滯告警
                │
                ▼
          REST /api/predict_pressure  +  MQTT reactor/01/prediction
```

---

## 2. 感測器資料格式

### 2.1 CSV 原始格式

每行 14+ 欄，逗號分隔：

| 欄位索引 | 內容 | 單位 |
|---|---|---|
| 0–2 | 年、月、日 | — |
| 3–5 | 時、分、秒 | — |
| 6 | 保留欄（`_`） | — |
| 7 | ORP | mV |
| 8 | 反應器壓力 | kg/cm² |
| 9 | 酸鹼值 (pH) | — |
| 10 | 溫度 | °C |
| 11 | 混合槽壓力 | kg/cm² |
| 12 | CO₂ 濃度 | % |
| 13 | CH₄ 濃度 | % |

**範例**：
```
2026,2,10,15,3,34,_,568,2.34,7.08,30.0,1.07,3.5,51.02
```

### 2.2 正常操作範圍

| 參數 | 正常範圍 | 說明 |
|---|---|---|
| ORP | 480 ～ 650 mV | 穩態判定依據 |
| 反應器壓力 | ≤ 2.6 kg/cm² | 超過視為危險閾值 |
| pH | 6.5 ～ 8.5 | 一般厭氧消化適宜範圍 |
| 溫度 | 25 ～ 40 °C | 中溫厭氧消化範圍 |

---

## 3. 訊號前處理管線

> **實作位置**：`edge_backend/core/signal_processor.py`（`ORPSignalProcessor`）

每一筆原始 ORP 資料依序通過以下三個處理步驟，最終輸出四個衍生欄位：`orp_raw`、`orp_cleaned`、`orp`（EMA）、`is_anomaly`。

### 3.1 一階差分突波偵測（First-order Difference Threshold）

定義相鄰兩筆之間的差分：

$$\Delta x_t = x_t - x_{t-1}$$

**判定規則**：若 $\Delta x_t < \theta_{\text{drop}}$，則判定為突波開始，設定：

$$\text{is\_anomaly}_t = \text{True}, \quad \theta_{\text{drop}} = -20 \text{ mV/min}$$

突波起始值記錄為 $x_{\text{start}}$，後續資料進入緩衝區，直到滿足以下任一結束條件：

| 結束條件 | 說明 |
|---|---|
| $x_t \geq 0.90 \cdot x_{\text{start}}$ 且 $\Delta x_t > 0$ | ORP 回升至起始值的 90% |
| 緩衝長度 $\geq T_{\max}$ | 超過最大突波時間窗（$T_{\max} = 15$ 分鐘） |

**設計依據**：單純的固定閾值（hard threshold）容易因長時間緩降而誤判。本方法透過一階差分捕捉「瞬間大幅下降」，再以回升比例判斷恢復，能有效區分突波事件與緩慢的生理性 ORP 降低。

### 3.2 線性內插重建（Linear Interpolation Repair）

突波結束後，對緩衝區中共 $N$ 筆被標記的資料點，以突波前的最後正常值 $x_{\text{start}}$ 和突波結束後的第一筆恢復值 $x_{\text{end}}$ 進行線性插補：

$$\hat{x}(i) = x_{\text{start}} + \frac{x_{\text{end}} - x_{\text{start}}}{N} \cdot i, \quad i = 1, 2, \ldots, N$$

其中 $\hat{x}(i)$ 為第 $i$ 筆突波資料的清理後值（`orp_cleaned`），$x_{\text{start}}$ 和 $x_{\text{end}}$ 均取自突波邊界的正常值。

**說明**：$i=1$ 為緩衝區第一筆，$i=N$ 為最後一筆（即結束點 $x_{\text{end}}$ 本身），因此插補結果在端點處連續。

### 3.3 指數移動平均（EMA，Exponential Moving Average）

對清理後的 $\hat{x}$ 序列進行 EMA 平滑，輸出 `orp`（即 `orp_ema`）：

$$y_t = \alpha \cdot \hat{x}_t + (1 - \alpha) \cdot y_{t-1}$$

其中平滑因子由視窗大小 $N = 10$ 決定：

$$\alpha = \frac{2}{N + 1} = \frac{2}{11} \approx 0.1818$$

初始值：$y_0 = \hat{x}_0$（第一筆資料直接初始化）。

**說明**：EMA 相對於簡單移動平均（SMA）的優點在於對近期資料賦予更高的權重，能更快響應趨勢變化，同時仍具備平滑效果。

### 3.4 前端附加處理（Savitzky-Golay 濾波）

> **實作位置**：`web_frontend/src/views/MonitorView.vue`（`applySGFilter()`）

前端在渲染 ORP 趨勢圖時，對 `orp_cleaned` 序列額外施加 Savitzky-Golay（SG）濾波作為第三條曲線展示，公式如下：

$$\hat{x}_{\text{SG}}(t) = \sum_{k=-M}^{M} c_k \cdot \hat{x}(t+k)$$

本實作採用視窗長度 $W = 11$（$M = 5$）、多項式階數 $d = 2$，係數來自標準 SG 係數表（normalization = 429）：

$$\mathbf{c} = \frac{1}{429} \left[-36, 9, 44, 69, 84, 89, 84, 69, 44, 9, -36\right]$$

邊界（$t < M$ 或 $t \geq n - M$）直接保留原始清理值，不做濾波。

---

## 4. ORP 穩態與漂移分析

> **實作位置**：`edge_backend/core/feature_extractor.py`（`ORPFeatureExtractor`）

### 4.1 穩態判定（Steady-State Detection）

以末尾 $W_s = \min(30, n)$ 筆 EMA 值計算樣本標準差（Bessel 修正）：

$$\bar{y} = \frac{1}{W_s} \sum_{t=1}^{W_s} y_t$$

$$\sigma = \sqrt{\frac{1}{W_s - 1} \sum_{t=1}^{W_s} (y_t - \bar{y})^2}$$

**穩態條件**（需同時滿足）：

$$\sigma < \sigma_{\text{th}} = 5.0 \text{ mV} \quad \text{且} \quad \bar{y} \in [480.0, 650.0] \text{ mV}$$

### 4.2 基準漂移率（Baseline Drift Rate）

對最近 $W_d = \min(120, n)$ 筆 EMA 值進行最小平方線性迴歸（OLS），設時間索引 $t_i = i$（每筆間隔 1 分鐘），求斜率 $\hat{\beta}_1$：

$$\hat{\beta}_1 = \frac{\sum_{i=0}^{n-1}(t_i - \bar{t})(y_i - \bar{y})}{\sum_{i=0}^{n-1}(t_i - \bar{t})^2}$$

其中 $\bar{t} = (n-1)/2$。將結果由 mV/min 換算為 mV/hr：

$$\text{drift\_rate} = \hat{\beta}_1 \times 60 \quad (\text{mV/hr})$$

**判讀標準**：

| 條件 | 描述 |
|---|---|
| $\|\text{drift\_rate}\| \leq 0.05 \cdot 60$ | 持平（Steady） |
| $\text{drift\_rate} > 0.05 \cdot 60$ | 上升漂移（Rising） |
| $\text{drift\_rate} < -0.05 \cdot 60$ | 下降漂移（Falling） |

---

## 5. AI 壓力預測模型

> **實作位置**：`edge_backend/core/model.py`、`core/inference.py`

### 5.1 模型架構（ReactorLSTM）

採用兩層堆疊 LSTM，最終接一個全連接層輸出雙目標：

```
輸入: (batch, 30, 6)
  │
  ▼
LSTM Layer 1: input_size=6, hidden_size=64, batch_first=True
  │
LSTM Layer 2: hidden_size=64
  │
取最後時間步輸出: (batch, 64)
  │
  ▼
Linear: 64 → 2
  │
  ▼
輸出: (batch, 2)  →  [壓力預測, CH4 預測]
```

**參數量估算**：

LSTM 每層參數量 $= 4 \times (d_h \times (d_{\text{in}} + d_h) + d_h)$

- Layer 1：$4 \times (64 \times (6 + 64) + 64) = 4 \times (64 \times 70 + 64) = 18,176$
- Layer 2：$4 \times (64 \times (64 + 64) + 64) = 4 \times (64 \times 128 + 64) = 33,024$
- FC：$64 \times 2 + 2 = 130$
- **總計：約 51,330 個可訓練參數**

### 5.2 輸入特徵規格

| 序號 | 特徵名稱 | 說明 | 計算方式 |
|---|---|---|---|
| 1 | `orp_ema` | ORP 的 EMA(10) | $\alpha_{10} = 2/11$ |
| 2 | `orp_slope` | ORP 斜率（mV/min） | $(ema_{10}[t] - ema_{10}[t-5]) / 5$ |
| 3 | `orp_macd` | ORP 的 MACD | $ema_5[t] - ema_{30}[t]$ |
| 4 | `ph` | 酸鹼值 | 原始值 |
| 5 | `temp` | 溫度（°C） | 原始值 |
| 6 | `pressure` | 反應器壓力（kg/cm²） | 原始值（作為 context 特徵） |

**輸入視窗長度**：SEQ_LEN = 30 個時間步（30 分鐘）  
**前置暖機需求**：WARMUP = 5（slope 計算需要前 5 筆，故最小緩衝 MIN_BUF = 35）

### 5.3 資料歸一化

使用 MinMaxScaler，分別對特徵矩陣 $X$ 和目標矩陣 $Y$ 進行線性縮放至 $[0, 1]$：

$$X'_{ij} = \frac{X_{ij} - X^{\min}_j}{X^{\max}_j - X^{\min}_j}$$

$$Y'_{ij} = \frac{Y_{ij} - Y^{\min}_j}{Y^{\max}_j - Y^{\min}_j}$$

**關鍵約束**：Scaler 僅在訓練集（前 70% 資料）上呼叫 `fit()`，驗證集與測試集僅呼叫 `transform()`，確保無資料洩漏（Data Leakage Prevention）。

### 5.4 預測目標

模型預測從當前時間步起算的第 +5 個時間步（+5 分鐘）之值：

$$\hat{y}_{t + 5} = f_{\text{LSTM}}(X_{t-29:t})$$

其中 $X_{t-29:t}$ 為過去 30 筆（含當前）的 6 維特徵矩陣，輸出維度為 2：

$$\hat{y} = \left[\hat{P}_{t+5},\ \widehat{\text{CH}_4}_{t+5}\right]$$

---

## 6. 特徵工程（推論端）

> **實作位置**：`edge_backend/core/inference.py`（`_extract_features()`）

推論時，從原始感測器緩衝區（`sensor_buffer`，deque maxlen=65）中取最近 35 筆，以在線方式計算特徵矩陣，步驟如下：

### 6.1 EMA 序列計算

分別以三種視窗計算 ORP 的指數移動平均：

$$\text{ema}_{10}[t] = \frac{2}{11} \cdot x_t + \frac{9}{11} \cdot \text{ema}_{10}[t-1]$$

$$\text{ema}_{5}[t] = \frac{2}{6} \cdot x_t + \frac{4}{6} \cdot \text{ema}_{5}[t-1]$$

$$\text{ema}_{30}[t] = \frac{2}{31} \cdot x_t + \frac{29}{31} \cdot \text{ema}_{30}[t-1]$$

### 6.2 斜率特徵

以 $\text{ema}_{10}$ 計算 5 步後向差分斜率（單位：mV/min）：

$$\text{slope}[t] = \frac{\text{ema}_{10}[t] - \text{ema}_{10}[t-5]}{5}, \quad t \geq 5$$

$$\text{slope}[t] = 0, \quad t < 5 \quad \text{（暖機補零）}$$

### 6.3 MACD 特徵

$$\text{MACD}[t] = \text{ema}_{5}[t] - \text{ema}_{30}[t]$$

MACD 為正值表示短期均線在長期均線之上（動能偏強），MACD 為負值則反之，提供模型動能方向的輔助訊號。

### 6.4 特徵矩陣組裝

取緩衝區最後 SEQ_LEN = 30 個時間步，組裝形狀為 $(30, 6)$ 的輸入矩陣，欄位順序為：

$$\mathbf{X} = \left[\text{ema}_{10},\ \text{slope},\ \text{MACD},\ \text{pH},\ T,\ P\right]_{30 \times 6}$$

---

## 7. 模型訓練流程

> **實作位置**：`edge_backend/train.py`

### 7.1 資料切割策略

時間序列資料的切割必須保持時間順序，不得隨機打亂（否則未來資訊洩漏至訓練集）：

| 子集 | 比例 | 筆數（序列） |
|---|---|---|
| 訓練集（Train） | 70% | 43,823 |
| 驗證集（Val） | 15% | 9,391 |
| 測試集（Test） | 15% | 9,391 |

**滑動視窗序列生成**（`create_sequences()`）：

$$X_i = \text{data}[i : i + 30], \quad y_i = \text{data}[i + 30 + 5]$$

即以第 $i$ 至 $i+29$ 共 30 筆預測第 $i+35$ 筆（+5 分鐘後），序列總數：

$$N_{\text{seq}} = N_{\text{total}} - 30 - 5 = 62{,}640 - 35 = 62{,}605$$

### 7.2 損失函數

均方誤差（MSE）於歸一化空間計算：

$$\mathcal{L} = \frac{1}{B} \sum_{b=1}^{B} \left\| \hat{y}_b - y_b \right\|^2_2$$

其中 $B = 128$（批次大小，BATCH_SIZE），$\hat{y}_b$ 和 $y_b$ 均為 MinMaxScaler 歸一化後的 2 維向量。

### 7.3 優化器設定

| 超參數 | 值 |
|---|---|
| 優化器 | Adam |
| 學習率 $\eta$ | $1 \times 10^{-3}$ |
| 批次大小 $B$ | 128 |
| 最大 Epoch | 80 |
| Dropout | 無（模型設計不含） |

### 7.4 Early Stopping

監控驗證集損失 $\mathcal{L}_{\text{val}}$，若連續 patience = 10 輪無改善則停止訓練，並還原至最佳驗證損失對應的權重：

```
patience_count = 0
best_val_loss  = ∞

for each epoch:
    if L_val < best_val_loss:
        best_val_loss   = L_val
        best_state_dict = model.state_dict()  # 深複製
        patience_count  = 0
    else:
        patience_count += 1
        if patience_count >= 10:
            STOP → restore best_state_dict
```

### 7.5 訓練結果

| 指標 | 數值 |
|---|---|
| 實際訓練輪數 | 13 輪 |
| 最佳驗證損失 $\mathcal{L}_{\text{val}}^*$ | 0.0041 |
| 測試集損失 $\mathcal{L}_{\text{test}}$ | 0.0041 |
| 泛化差距 $= \|\mathcal{L}_{\text{test}} - \mathcal{L}_{\text{val}}^*\| / \mathcal{L}_{\text{val}}^*$ | 0.1% |
| 結論 | 模型泛化良好（差距 < 20%） |

---

## 8. 三級告警系統

> **實作位置**：`edge_backend/core/inference.py`（`get_pressure_prediction()`）

### 8.1 輸出平滑（Output EMA）

模型原始輸出為每次推論的瞬時預測值，容易因輸入雜訊產生抖動，以遞推 EMA 進行後平滑：

$$P_{\text{smooth}}^{(t)} = \alpha_{\text{out}} \cdot \hat{P}^{(t)} + (1 - \alpha_{\text{out}}) \cdot P_{\text{smooth}}^{(t-1)}, \quad \alpha_{\text{out}} = 0.5$$

$$\widehat{\text{CH}_4}_{\text{smooth}}^{(t)} = \alpha_{\text{out}} \cdot \widehat{\text{CH}_4}^{(t)} + (1 - \alpha_{\text{out}}) \cdot \widehat{\text{CH}_4}_{\text{smooth}}^{(t-1)}$$

初始化：$P_{\text{smooth}}^{(0)} = \hat{P}^{(0)}$（第一次推論直接採用）。

### 8.2 遲滯告警邏輯（Hysteresis Alert）

維護一個長度為 3 的原始預測壓力歷史佇列 $H = [h_1, h_2, h_3]$（最舊至最新），採用以下三級判定：

#### 危險（Danger）— 需同時滿足 3 個條件

$$\text{is\_danger} = \left[|H| = 3\right] \land \left[\forall h \in H: h > 2.6\right] \land \left[h_3 \geq h_1\right]$$

其中：
- $|H| = 3$：需累積足夠歷史（避免初期誤報）
- $\forall h > 2.6$：連續 3 次預測均超過危險閾值 2.6 kg/cm²
- $h_3 \geq h_1$：趨勢持續上升（防止偶發超標的一次性誤觸發）

#### 警告（Warning）— 滿足任一條件

$$\text{is\_warning} = \left[P_{\text{smooth}} > 2.4\right] \lor \left[\frac{h_3 - h_1}{|H|} > 0.05\right]$$

其中第二個條件為近 3 次預測的平均斜率超過 0.05 kg/cm² / 步。

#### 正常（Normal）

以上兩個條件皆不成立時輸出正常狀態。

### 8.3 設計分析

| 設計元素 | 目的 |
|---|---|
| 輸出 EMA（α=0.5） | 降低單點雜訊影響，避免壓力預測值在閾值附近劇烈震盪 |
| 連續 3 次超閾值 | 避免偶發異常觸發危險告警（遲滯寬度約 3 分鐘） |
| 趨勢確認（h₃ ≥ h₁） | 排除「已在高位但開始回落」的情況，僅對持續惡化告警 |
| 警告閾值 2.4 < 危險閾值 2.6 | 提供緩衝區間（0.2 kg/cm²），讓操作員有足夠時間介入 |

---

## 9. 資料流與系統整合

### 9.1 三條輸入通道

| 通道 | 入口 | 資料流向 |
|---|---|---|
| USB 即時感測器 | `/dev/ttyUSB0` 9600 baud | `usb_receiver.py` → 訊號處理 → `sensor_records[]` |
| CSV 批次匯入 | `POST /api/import_csv` | 逐行解析 → 訊號處理 → `sensor_records[]` + `sensor_buffer` 預熱 |
| HTTP 手動輸入 | `POST /api/records` | 直接 append，不經訊號處理 |

### 9.2 LSTM Buffer 預熱機制

CSV 匯入完成後，自動將最後 34 筆（`parsed_rows[-35:-1]`）直接 append 至 `sensor_buffer`，並以最後 1 筆呼叫正式推論介面，觸發首次預測：

```python
# sensor_buffer 預熱（前 34 筆）
for row in parsed_rows[-35:-1]:
    sensor_buffer.append([row['orp_raw'], row['ph'], row['temp'], row['pressure']])

# 第 35 筆觸發正式推論（同時更新 latest_actual_pressure）
pred = get_pressure_prediction({
    'orp': last['orp_raw'], 'ph': last['ph'],
    'temp': last['temp'],   'pressure': last['pressure']
})
```

此設計確保 CSV 匯入完成後，前端立即可取得推論結果，而非等待下一筆感測資料。

### 9.3 HTTP Fallback 機制

`GET /api/predict_pressure` 在回應前會先檢查 buffer 是否足夠，若不足且 `sensor_records` 已有 ≥ 35 筆歷史資料，則自動從歷史資料補齊：

```python
if len(sensor_buffer) < 35 and len(sensor_records) >= 35:
    sorted_recs = sorted(sensor_records, key=lambda r: r['timestamp'])
    for r in sorted_recs[-35:]:
        sensor_buffer.append([r.get('orp_raw') or r['orp'], r['ph'],
                               r['temp'], r.get('pressure', 0.0)])
```

### 9.4 MQTT 整合

- **Broker 地址**：`192.168.55.1:1883`（TCP）/ port 9001（WebSocket）
- **發布主題**：`reactor/01/prediction`
- **訂閱主題**：前端透過 WebSocket 訂閱，payload 為 JSON
- **MQTT 重連策略**：前端設定 `reconnectPeriod: 15000`（15 秒），避免連線失敗時每秒重試洗刷狀態欄

---

## 10. REST API 端點規格

基底 URL：`http://192.168.55.1:8000/api`

| 方法 | 路徑 | 功能 | 備注 |
|---|---|---|---|
| `GET` | `/records` | 取全部記錄（依 timestamp 排序） | 回傳 JSON 陣列 |
| `POST` | `/records` | 新增單筆記錄 | Body: `SensorRecord` |
| `DELETE` | `/records/{id}` | 刪除單筆 | — |
| `DELETE` | `/records` | 清空全部 | — |
| `POST` | `/upload_sensor` | 接收感測器數據並即時推論 | Body: `SensorDataPayload` |
| `POST` | `/import_csv` | CSV 批次匯入（含訊號前處理） | multipart/form-data |
| `GET` | `/predict_pressure` | 取最新 LSTM 推論結果 | HTTP fallback |
| `GET` | `/analysis` | 穩態判定 + 漂移率分析 | — |
| `GET` | `/report/stats` | 統計分析（直方圖、相關係數等） | 需 ≥ 10 筆 |
| `GET` | `/health` | 存活 + 資料新鮮度（控制台輪詢） | 記錄中斷偵測 |
| `GET` | `/phase` | 生物三相位偵測序列 | — |
| `GET` | `/ch4_prediction` | CH4 峰值即時預測 + 特徵歸因 | XGBoost/SHAP，退回 GA+Ridge；含外插防護 |
| `GET` | `/covariate_analysis` | 共變數關聯（平緩化生物 vs 物理） | 叢集穩健標準誤 |
| `GET` | `/greybox_analysis` | 灰箱可分離度就緒指標 | 暫態時給分離比例 |
| `*` | `/experiment/*` | 實驗批次管理（plan/runs/start/vent/cycles/live/export） | 見批次管理章 |

### `/api/predict_pressure` 回傳格式

```json
{
  "device": "Jetson Orin Nano",
  "current_pressure_kg_cm2": 2.34,
  "predicted_pressure_5min": 2.41,
  "predicted_ch4_5min": 51.2,
  "status": "警告 (Warning)",
  "inference_time_ms": 12.3,
  "message": "壓力上升趨勢，請留意！"
}
```

### `/api/report/stats` 回傳格式

```json
{
  "summary": {
    "total_records": 62640,
    "anomaly_count": 312,
    "anomaly_rate": 0.5,
    "orp_mean": 565.3,
    "orp_std": 18.7,
    "pressure_mean": 2.28,
    "pressure_max": 2.61,
    "ch4_mean": 48.3
  },
  "orp_histogram":      { "bins": [...], "counts": [...] },
  "pressure_histogram": { "bins": [...], "counts": [...] },
  "correlation": {
    "labels": ["ORP", "pH", "溫度", "壓力", "CH4", "CO2"],
    "matrix": [[1.0, ...], ...]
  },
  "anomaly_by_date": [ { "date": "2026-02-10", "total": 1440, "anomalies": 8 }, ... ],
  "gas_daily":       [ { "date": "2026-02-10", "avg_ch4": 48.2, "avg_co2": 3.4 }, ... ],
  "orp_ph_scatter":  [ { "orp": 568.1, "ph": 7.08, "ch4": 51.0 }, ... ]
}
```

---

## 11. 前端視覺化方法

### 11.1 ORP 訊號分析圖（即時監控頁）

ECharts 折線圖，同時呈現四條曲線：

| 系列名 | 資料來源 | 用途 |
|---|---|---|
| 原始 ORP | `orp_raw` | 真實感測器輸出 |
| 去突波後 | `orp_cleaned` | 線性插補修復後 |
| SG 濾波 | 前端計算（W=11, d=2） | 高頻雜訊進一步壓制 |
| EMA 平滑 | `orp`（= `orp_ema`） | LSTM 實際使用的特徵 |

突波區間以半透明紅色 `markArea` 標注（`rgba(231,76,60,0.07)`）。

**互動點選分析**：點選圖表任意資料點後，前端以該點為中心，取前後各 ±15 分鐘（最多 30 筆）的 `orp` 值，在瀏覽器端計算局部穩態分析：

$$\sigma_{\text{local}} = \sqrt{\frac{1}{n-1} \sum_{i=1}^{n}(y_i - \bar{y})^2}$$

$$\beta_{\text{local}} = \frac{\sum(t_i - \bar{t})(y_i - \bar{y})}{\sum(t_i - \bar{t})^2} \times 60 \text{ (mV/hr)}$$

### 11.2 研究分析頁（`/report`）

| 圖表 | 方法 | 資料 |
|---|---|---|
| ORP 分布直方圖 | 24 bins 等寬直方圖 | `orp_histogram` |
| 壓力分布直方圖 | 24 bins，≥2.6 染紅 | `pressure_histogram` |
| 特徵相關係數熱力圖 | Pearson r（6×6） | `correlation.matrix` |
| 每日突波統計 | 分組長條圖 + dataZoom | `anomaly_by_date` |
| CH4/CO2 日均值趨勢 | 雙折線 + 面積填充 | `gas_daily` |
| pH–ORP 狀態空間散點圖 | 散點（最多 600 點），顏色映射 CH4 | `orp_ph_scatter` |

相關係數矩陣計算（後端 NumPy）：

$$r_{XY} = \frac{\sum_{i=1}^{n}(X_i - \bar{X})(Y_i - \bar{Y})}{\sqrt{\sum_{i=1}^{n}(X_i - \bar{X})^2} \cdot \sqrt{\sum_{i=1}^{n}(Y_i - \bar{Y})^2}}$$

全常數欄位（方差為零）的相關係數以 0.0 填補（避免 NaN 傳至前端）。

散點圖最多取 600 點以避免前端過載：

$$\text{step} = \max\!\left(1, \left\lfloor \frac{n}{600} \right\rfloor\right)$$

---

## 12. 訓練結果與評估

### 12.1 訓練收斂過程

| Epoch | Train Loss | Val Loss | 狀態 |
|---|---|---|---|
| 1 | 0.0111 | 0.0065 | ★ 最佳 |
| 5 | 0.0027 | 0.0058 | (2/10) |
| 10 | 0.0014 | 0.0102 | (7/10) |
| 13 | — | — | Early Stop 觸發 |

### 12.2 最終評估

| 指標 | 值 |
|---|---|
| 最佳 Validation Loss（MSE，歸一化空間） | 0.0041 |
| Test Loss（MSE，歸一化空間） | 0.0041 |
| 泛化差距 | 0.1% |
| 訓練資料量（序列數） | 43,823 |
| 驗證資料量（序列數） | 9,391 |
| 測試資料量（序列數） | 9,391 |

### 12.3 泛化差距定義

$$\text{Gap} = \frac{|\mathcal{L}_{\text{test}} - \mathcal{L}_{\text{val}}^*|}{\mathcal{L}_{\text{val}}^*} \times 100\%$$

本次 Gap = 0.1%，遠低於告警門限 20%，表明模型未發生過擬合（Overfitting）。

---

## 13. 已知限制與未來工作

> **文件成稿後新增子系統（摘要）**：本報告原聚焦壓力 LSTM 與訊號處理；其後新增
> (a) **實驗批次管理**（`core/experiment_store.py`：循環偵測、記錄中斷排除、進氣前 ORP
> 共變數、斜率平緩化、兩層報表）；(b) **CH4 即時預測**升級 XGBoost+TreeSHAP（退回 GA+Ridge，
> 含外插防護）；(c) **CO2 分離研究**（`co2_greybox_identifiability.py` 證明穩態結構性不可分離、
> `co2_covariate_association.py` 判平緩化成因，皆有前端端點）；(d) **桌面控制台** `control_panel.pyw`。
> 詳見 TECHNICAL_SPEC.md §13.5 與各 docs/。

### 13.1 目前限制

| 項目 | 說明 | 影響程度 |
|---|---|---|
| 記憶體內資料儲存 | 重啟服務後 `sensor_records[]` 清空 | 高：需重新匯入歷史 CSV |
| 單一 USB 路徑 | `usb_receiver.py` 固定 `/dev/ttyUSB0` | 中：不同設備需手動修改 |
| 模型無熱重載 | 重新訓練後需重啟後端 | 低：訓練頻率不高 |
| 輪詢間隔 | 前端目前 5 秒（開發用），正式部署應為 60 秒 | 低：已知設定 |
| 推論歸一化空間 MSE | 模型評估在歸一化空間，原始單位的 RMSE 未計算 | 中：應換算為 kg/cm² 與 % 以便物理解釋 |
| CH4/CO2 為參考級訊號 | 僅排氣瞬間有效，其餘 99.98% 為管路拖尾 | 高：不得作為分離證據 |
| CO2 分離穩態不可辨識 | 穩態下溶解通量≡生物通量，結構性分不開（與演算法無關） | 高：需暫態實驗，見暫態分離協定 |
| CH4 峰值樣本量 | 完整週期 <30，樹模型小樣本高變異 | 中：XGBoost 用於歸因非預測，已據實標明 |

### 13.2 建議後續工作

1. **持久化儲存**：以 SQLite 或 InfluxDB 替換記憶體內 list，重啟不丟資料
2. **原始單位評估**：在 `train.py` 加入反歸一化後的 RMSE / MAE 計算，以 kg/cm² 和 % 報告預測誤差
3. **Dropout 正則化**：模型目前無 Dropout，資料量增大後建議加入（通常 $p = 0.2$）
4. **多步預測**：目前僅預測 +5min，可擴展為輸出序列（Seq2Seq），預測接下來 5～30 min 的趨勢
5. **模型版本管理**：紀錄每次重訓練的資料日期範圍、Loss 及告警閾值調整歷史
