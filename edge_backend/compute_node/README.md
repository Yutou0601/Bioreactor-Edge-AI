# 重運算節點（Jetson Orin NX 16 GB）

## 這台在做什麼

監控電腦是 4 GB 的 Windows 機器，常駐核心只有 60 MB 預算，所以那台上的分析
模組一律開**短命子行程**——跑完記憶體還給作業系統，代價是每次都要重付
import 的錢（xgboost +119.5 MB、scipy +69.6 MB，外加載入時間）。

Orin 有 16 GB，這個取捨不成立了。這台把三個模組的分析程式在啟動時就全部
載入並熱著，之後每次呼叫都是純運算。

```
監控電腦 (Windows, 4 GB)                Jetson Orin NX (Linux, 16 GB)
├─ 記錄程式寫 CSV                        └─ compute_node（本目錄）
├─ csv_watcher / API / 前端                   常駐、套件熱著、吃得到 GPU
├─ core 精簡核心（仍守 60 MB）
└─ module_runner ──── HTTP ───────────→ POST /run/<name>
                 ←─── 結果列 JSON ─────
```

## 安裝

```bash
git clone <repo> && cd Bioreactor-Edge-AI/edge_backend
python3 -m venv venv && . venv/bin/activate
pip install -r requirements-compute.txt        # ⚠ 不是 requirements.txt
cp .env.example .env && $EDITOR .env           # REACTOR_PROFILE=compute
python -m compute_node.server
```

啟動訊息會印出暖機耗時、RSS、以及 GPU 狀態。三個模組都要是 `✓`。

### torch 要另外裝

**不要 `pip install torch`。** PyPI 的 aarch64 wheel 沒有 CUDA，裝起來是純
CPU 版而且不會報錯——GPU 就這樣安靜地沒被用到。要用 NVIDIA 為該版 JetPack
發布的 wheel，或 `nvcr.io` 的 `l4t-pytorch` 容器。裝完驗：

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

印出 `True` 才算裝對。

目前三個分析模組**都用不到 torch**（只有 `core/inference.py` 的 LSTM 要，
而那支預設關閉），所以 torch 沒裝好不會擋住這台上線。

## 監控電腦那邊要設什麼

`.env` 加一行，指到這台：

```
REACTOR_COMPUTE_URL=http://<orin 的 IP>:8100
```

留空就是照舊在本機跑子行程——單機部署、開發筆電、Orin 還沒到之前都留空。

要確認目前走哪條路：`GET /api/modules` 的 `backend` 欄位。

## 連不到會怎樣

**模組會失敗**，紀錄裡寫「連不到重運算節點 …。模組沒有跑。」，不會靜默
退回本機跑。這是故意的——靜默退回的話，這台 16 GB 的機器可以壞掉好幾個月
而沒有人發現（torch 曾經就是這樣藏了好幾個月）。

## 端點

| 端點 | 用途 |
|---|---|
| `GET /health` | 角色、RSS、熱著的套件版本、GPU、各模組狀態 |
| `GET /modules` | 這台跑得動哪些模組 |
| `POST /run/{name}` | body `{"input": …}` → `{"ok", "row", "seconds", "log"}` |

## 加新模組要注意的

`run.py` 必須提供 **`compute_row(input) -> dict`**：純運算、回一列 dict、
**不碰資料庫**。本機模式由 `main()` 拿去寫 SQLite，遠端模式由這台呼叫後把
dict 回傳給監控電腦寫。只有 `main()` 的模組只能在監控電腦上用子行程跑。

結果表的欄位要同時寫在兩個地方：`run.py` 的 `SCHEMA` 與 `module.json` 的
`result_columns`。`system_test` 第 14 項會比對，漂掉就紅。

⚠ **每個模組的分析檔都叫 `analysis.py`。** 常駐 import 時，第二個之後的
`import analysis` 會拿到 `sys.modules` 裡第一個的快取——子行程模式沒這個
問題，是搬成常駐才冒出來的。一律用 `run_one()` 呼叫，它裡面的
`_swap_analysis()` 會處理；不要直接抓 `_loaded[name]['run'].compute_row()`。
（寫測試時第一版就這樣踩過，當場 ImportError；如果兩個模組的函式名剛好
對得上，就會變成不報錯但算錯。）
