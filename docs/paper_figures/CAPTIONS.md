# Figure captions (LNCS style)

**Paper**: *Edge-Side Pressure-Only Change-Point Mining Recovers Undocumented Setpoint
Changes and Manual Interventions in a Micro-Pressurized Recirculating Hydrogenotrophic
Biomethanation Reactor*

LNCS 慣例：圖說置於圖下方，以 **Fig. n.** 起始，句首大寫、句末句點，
說明文字為 9 pt。所有圖檔皆為 122 mm（4.80 in）寬向量 PDF，字型 Type 42 內嵌，
且不以顏色承載資訊（灰階印刷可讀）。

---

### Fig. 1 — `fig1_pipeline.pdf`

> **Fig. 1.** System and mining pipeline. The reactor admits gas when headspace pressure
> falls to a trigger threshold and recirculates headspace gas into the liquid for τ
> minutes each hour. Controller-level signals — setpoint, valve state, and pump command —
> are not logged, so the pipeline receives only the pressure trace, sampled once per
> minute and quantized to 0.01 kg cm⁻². Stage 3 (highlighted) reconstructs which derived
> channels carry usable control information and is what removes the controller-access
> assumption of prior attribution work.

### Fig. 2 — `fig2_setpoint_history.pdf`

> **Fig. 2.** Recovered trigger-setpoint history. Light points are individual refill
> events; the step line is the modal setpoint over non-overlapping windows of 15
> refills. Shaded bands mark intervals longer than three days with no refill. The band
> beneath the axis identifies the campaigns: feed is H₂:CO₂ = 4:1 except for the marked
> 1:1 period, and τ denotes the recirculation series. These are separate experiments,
> not one continuous run; the setpoint is nevertheless a control parameter that persists
> across them. After a commissioning period it holds at 0.71 kg/cm² for approximately
> nine months and then moves to 0.92 in mid-July 2026 (dashed line), a reconfiguration
> that appears in no operating record.

⚠ **兩處已修正**：
1. 原圖說寫「陰影＝recording gaps，覆蓋 174/351 天」——**陰影標的是「>3 天沒有補氣」，
   不等於沒有資料**。真正的覆蓋率由原始取樣時戳統計（235/365 天），改由 Fig. 5 呈現。
2. 原圖把整年所有補氣點畫在同一軸上，看起來像單一母體，但其中含 1:1 進氣期與 τ 系列等
   **獨立實驗**。已加條件帶標示。

### Fig. 3 — `fig3_bimodality.pdf`

> **Fig. 3.** Distribution of refill starting pressure before and after the 2026-07-11
> reconfiguration, computed from minute-level refill events without cycle segmentation.
> Percentages give the share of refills in the 0.60–0.80 (blue) and 0.85–1.00 (red)
> clusters. The distribution shifts rather than becoming bimodal: the original threshold
> stops firing, which excludes the alternative explanation that unchanged automatic
> control continued with manual gas additions superimposed.

### Fig. 4 — `fig4_masstransfer.pdf`

> **Fig. 4.** Composition-corrected mass-transfer proxy by recirculation duty cycle.
> Markers give medians and bars give interquartile ranges. Median values order
> monotonically with duty cycle, and low-duty operation separates from high-duty
> operation; within the high-duty group the ranges overlap and the three settings are not
> distinguishable at this sample size.

### Fig. 5 — `fig5_event_timeline.pdf`

> **Fig. 5.** Recovered operating history. Upper panel: detected events per
> month, stacked by class. Lower panel: days on which pressure was logged,
> counted from raw sample timestamps. Classes are distinguished by fill and
> hatch so that the figure remains legible in grayscale. The commissioning
> period (2025-08 to 2025-10) contributes most of the recording artifacts;
> process drift dominates the stable regime; the two persistent
> reconfigurations fall in 2025-10 and 2026-07.

⚠ **第一版是散點時間軸，已作廢**：55 個事件擠在 122 mm、12 個月的軸上，
2026-02 前後的瞬時介入疊成一團三角形，上方的已知事件標籤也互相碰撞。
密度不適合這個版面寬度，改為月度堆疊長條。

---

## 檔案清單

| 檔案 | 產生程式 | 尺寸 |
|---|---|---|
| `fig1_pipeline.pdf` | `edge_backend/fig1_pipeline.py` | 4.80 × 2.80 in |
| `fig2_setpoint_history.pdf` | `edge_backend/paper_figures.py` | 4.80 × 2.50 in |
| `fig3_bimodality.pdf` | `edge_backend/paper_figures.py` | 4.80 × 2.70 in |
| `fig4_masstransfer.pdf` | `edge_backend/paper_figures.py` | 4.80 × 2.15 in |
| `fig5_event_timeline.pdf` | `edge_backend/fig5_event_timeline.py` | 4.80 × 2.60 in |

`.png`（300–400 dpi）僅供校稿，投稿一律用 `.pdf`。

## LNCS 合規檢查

- [x] 寬度 122 mm（單欄文寬）
- [x] 向量 PDF
- [x] 字型內嵌（`pdf.fonttype = 42`）
- [x] 線寬 ≥ 0.5 pt
- [x] 灰階可讀（不以顏色承載資訊；Fig. 3 的藍/紅另以左右位置與百分比數字區分）
- [x] 圖內不含 "Fig. n" 字樣（由 LaTeX `\caption` 產生）
- [ ] 最終尺寸下的可讀性目視確認（列印後檢查）
