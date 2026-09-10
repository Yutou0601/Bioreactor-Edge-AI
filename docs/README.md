# docs/ — 文件索引

2026-09-10 從 74 個平鋪檔案整理成主題子資料夾。找不到某份舊文件時，
先看下面的對照表，不要以為它被刪了。

| 資料夾 | 放什麼 | 幾份 |
|---|---|---|
| [`system/`](system/) | 系統架構、部署、技術規格 | 12 |
| [`paper/`](paper/) | ICEA 2026 論文：草稿、骨架、中譯、書目、待辦 | 16 |
| [`analysis/`](analysis/) | 研究分析報告與證據鏈 | 8 |
| [`experiments/`](experiments/) | 實驗設計、排程、參數與 DOE 表 | 9 |
| [`reports/`](reports/) | 日報、週報、彙整待辦 | 10 |
| [`decks/`](decks/) | 簡報大綱、逐頁稿與 .pptx 成品 | 13 |
| [`build/`](build/) | 產生上面那些文件與簡報的 .py | 12 |
| `figures/`、`paper_figures/`、`analysis_charts/`、`analysis_charts_3batch/` | 圖表與資料檔 | — |
| `20260820/`、`20260823/` | 當日打包的成果（原樣保留） | — |

## 先讀哪一份

- **要動系統** → [`system/系統重構架構_2026-08-31.md`](system/系統重構架構_2026-08-31.md)
  這是目前的架構依據，程式碼裡有多處註解直接引用它的章節。
- **要部署** → [`system/開發與部署流程.md`](system/開發與部署流程.md)
- **要寫論文** → [`paper/ICEA2026_paper_v2_FULL.md`](paper/ICEA2026_paper_v2_FULL.md)
  以及 [`paper/ICEA2026_references_verified.md`](paper/ICEA2026_references_verified.md)（書目已逐筆 DOI 查證）
- **要重跑分析** → [`../research/README.md`](../research/README.md)

## build/ 的路徑約定

`build/` 底下的產生器把 `HERE` 指到 **`docs/`**（不是 `docs/build/`），
輸出寫進對應的子資料夾：簡報進 `decks/`、週報進 `reports/`。

> ⚠ 2026-09-10 這些腳本從 `docs/` 搬到 `docs/build/` 時，`HERE` 是跟著
> `__file__` 走的，不修就會把產出物全部丟進 `build/` 裡。新增產生器時
> 照抄現有的 `HERE` 寫法。

## 引用其他文件時

文件之間用**相對路徑**連結（例如從 `paper/` 指到 `analysis/` 要寫
`../analysis/xxx.md`）；程式碼註解裡引用文件則寫完整的 `docs/<子資料夾>/<檔名>`。

兩種寫法都可以用連結檢查器驗證——搬動任何文件之後都應該跑一次，
死連結不會報錯也不會有人發現，只會在某天有人點下去時安靜地 404。
