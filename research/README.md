# research/ — 論文分析腳本

這裡是**離線研究程式碼**：跑一次、產生一個數字或一張圖、寫進論文。
它不會被部署到監控電腦（`pack.bat` 只打包 `edge_backend/` 與前端 `dist/`）。

上線的程式碼在 [`edge_backend/`](../edge_backend/)。兩邊的界線是：

| | 在哪 | 誰在跑 | 記憶體預算 |
|---|---|---|---|
| 常駐核心 | `edge_backend/` | 監控電腦，一直開著 | 60 MB，只准 numpy |
| 分析模組 | `edge_backend/modules/` | 監控電腦，短命子行程 | 不限，跑完就收回 |
| **研究腳本** | **`research/`** | **開發機，手動** | **不限** |

> ⚠ 一支腳本一旦被 API 端上，它就不再屬於這裡，該搬進 `edge_backend/modules/`。
> `co2_covariate_association` 與 `co2_greybox_identifiability` 就是這樣搬走的。

---

## 目錄規則（不是隨意分類，改動前先讀）

**根層放被別人 import 的共用模組；子資料夾只放零被引用的葉腳本。**

`analyze_three_batches` 一支就被 74 支腳本 import。如果按主題把它塞進某個
子資料夾，其他子資料夾的腳本全部 import 不到。所以：

```
research/
  <共用模組>.py        ← 被 ≥1 支腳本 import。留在根層，誰都找得到
  paths.py             ← 資料位置解析（見下）
  <主題>/
    <葉腳本>.py        ← 沒有人 import 它。可以自由歸類
```

葉腳本開頭有一行 `_sys.path.insert(...)`，把 `research/` 加回搜尋路徑——
搬進子資料夾之後 `sys.path[0]` 只剩該子資料夾，共用模組會找不到。
**新增葉腳本時要照抄那一行**，否則 `from analyze_three_batches import ...`
會在執行時才炸。

## 資料在哪

實驗原始資料在 `research/Testing_data/`（約 115 MB，**不進版控**）。
不要在腳本裡寫死路徑，用解析器：

```python
from paths import testing_data
DATA = os.path.join(testing_data(), '202607至08最新循環研究')
```

`paths.py` 會依序找新位置與舊位置（`edge_backend/Testing_data/`），
找不到就丟例外並列出找過哪裡——**不會靜默回傳空的**。這很重要：靜默失敗
會讓分析跑出「0 個循環」然後照常印出結論。

## 主題

| 資料夾 | 內容 |
|---|---|
| `rb_estimation/` | r_b 估計主線：修正、區間、逐段、逐 k 區間、端點偏誤 |
| `cycles/` | 循環與變點：切段、設定點、設備推論、頭空體積、重置特徵 |
| `co2/` | CO2 分離線：弛豫、漂移分解、泵對照、平衡尾段 |
| `orp_ch4/` | ORP 與甲烷錨點：Nernst、雙時間尺度、活躍度指標、CH4 峰 |
| `ml/` | LSTM 訓練與基準比較、子模型架構評估、外部驗證 |
| `figures/` | 論文與簡報的圖產生器 |
| `dead_ends/` | **已否決的路線** |

### 關於 `dead_ends/`

保留而不刪除，是為了不再撞同一道牆。裡面是**做過、驗證過、不成立**的方法：

- `crossing_rate.py` / `crossing_asym.py` — 位準跨越與速率空間估計量。
  速率空間確實消掉了 P_eq，但簡併原封重現（資料處理不等式）。
- `intercycle_coupling.py` / `intercycle_probe.py` — 跨循環時間不對稱。
  換視窗會讓號誌翻正、安慰劑檢定重現大部分效果。

要重試其中任何一條之前，先把該檔的檔頭讀完——失敗的原因寫在裡面。

---

## 驗收：線上與離線必須一致

`edge_backend/system_test.py` 第 2 組會拿這裡的 `dataset_c`、
`rb_recovery_study`、`simulator_check` 跟核心的 `cycle_estimator` 逐段比對
（曲率、k、r_b）。**跑得動不等於搬對了**——數字必須相同，否則系統與論文
對不上，而且不會有任何錯誤訊息。

改動任何共用常數（`KGRID`、`CURV_MIN`、切段門檻…）之後，兩邊都要改，
並重跑：

```
cd edge_backend && python system_test.py
```
