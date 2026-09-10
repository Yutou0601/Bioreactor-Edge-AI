# ICEA 2026 投稿檔

**Edge-Side Pressure-Only Change-Point Mining Recovers Undocumented Setpoint Changes and
Manual Interventions in a Micro-Pressurized Recirculating Hydrogenotrophic Biomethanation
Reactor**

Cheng-Yu Li¹, Chun-Hao Chen¹, Cheng-Yuan Hung², Yen-Jie Huang²
¹ 高科大資工　² 金屬中心光電組

---

## 檔案

| 檔案 | 說明 |
|---|---|
| `main.tex` | 論文本體（LNCS） |
| `refs.bib` | 12 筆參考文獻，**全部經 Crossref 逐筆查證** |
| `lint_tex.py` | 靜態檢查（本機無 LaTeX 工具鏈時的替代驗證） |
| `../docs/paper_figures/*.pdf` | 四張圖，向量 |

## 編譯

```
pdflatex main
bibtex   main
pdflatex main
pdflatex main
```

**需要 Springer LNCS 作者套件**（`llncs.cls`、`splncs04.bst`），
自 <https://www.springer.com/gp/computer-science/lncs/conference-proceedings-guidelines>
下載後與 `main.tex` 放同一層。

⚠ **本機未安裝 pdflatex/bibtex，因此本稿從未被實際編譯過。**
第一次編譯必然會有需要微調的地方（圖片浮動位置、表格寬度、斷行）。
在有工具鏈的機器上編譯前，先跑：

```
python lint_tex.py
```

它會檢查環境配對、數學界定符、大括號、表格欄數、`\ref`／`\cite` 對應，
以及 bib 是否有未被引用的條目。**它不能取代真正的編譯。**

## 送印前必填

- [ ] `\email{<corresponding author e-mail>}` — 填第一作者信箱
- [ ] 確認專利 TW I923176 是否需要權利註記
- [ ] 排版後確認未超過 LNCS 10 頁

不需要的：**經費致謝**（無外部經費，非必填）、**ORCID**（LNCS 非必填）。

## 刻意不使用的套件

`siunitx` —— 單位改以 `\pu`、`\ratu`、`\dc`、`\degC` 四個 `\newcommand` 處理。
原因：本機無法編譯驗證，而 siunitx v2/v3 的單位語法有差異
（`\squared` vs `\square`、`\day` 非內建），在不能測試的情況下屬於不必要的風險。

## 數據來源對照

論文中每個數字都可回溯到 `edge_backend/` 的程式：

| 論文位置 | 程式 |
|---|---|
| §4.1 切分門檻敏感度（Table 1） | `analyze_three_batches.py` + 稽核腳本 |
| §4.3 控制／反應面切分（Table 2） | `control_plane_partition.py` |
| §4.4–4.5 校準與類型學 | `typology_validation.py`、`three_class_typology.py` |
| §5.1 覆蓋率、空窗 | `changepoint_forensics.py` |
| §5.2 設定點史（Table 4）、雙峰（Table 5） | `trigger_setpoint_tracker.py`、`refill_kinetics.py` |
| §5.3 手動排氣 18 次 | `three_class_typology.py` |
| §5.4 已知事件驗證 | `typology_validation.py`、`three_class_typology.py` |
| §5.5 質傳（Table 6） | `analyze_three_batches.py` |
| §6 邊緣成本 | `edge_benchmark.py`、`band_information.py` |
| Fig. 1 | `fig1_pipeline.py` |
| Fig. 2–4 | `paper_figures.py` |

數字稽核記錄（含七處已修正的錯誤）見
`../docs/paper/ICEA2026_paper_v2_FULL.md` 檔末的「Numeric audit」。
