# Jetson Orin NX 16 GB 重運算節點 — 部署流程

2026-10-08。給實際要在現場把這台機器裝起來的人看的：會用終端機，但不熟這個
專案的程式。照著做即可，每一步為什麼要做也都寫了。

機器是 2026-09-16 下訂的「NX Super 基礎套件 16GB」，交期一個月，約 10 月中到。

---

## 1. 這台在做什麼，以及它不做什麼

```
監控電腦 (Windows, 4 GB)                Jetson Orin NX (Linux, 16 GB)
├─ 記錄程式寫 CSV                        └─ compute_node（常駐、套件熱著）
├─ csv_watcher / API / 前端                   POST /run/<模組>
├─ core 精簡核心（守 60 MB）                  只算，算完回 JSON
└─ module_runner ──── HTTP ───────────→
                 ←─── 結果列 JSON ─────      ⚠ 這台不寫資料庫
```

**兩台並存，不是取代。** 監控電腦繼續收 CSV、出網頁、寫資料庫；Orin 只負責
三個分析模組的運算。

這台**不做**的事，列出來是因為每一條都有人問過：

| 不做 | 為什麼 |
|---|---|
| 不寫資料庫 | 結果回給監控電腦寫。這台就算有 `reactor.db` 也沒人看，真在這裡寫只會變成「結果一直是舊的」而兩邊都不報錯 |
| 不讀 CSV | 記錄程式在監控電腦上，Orin 看不到那個資料夾 |
| 不出網頁 | 沒有 `web_frontend/dist`，也不需要 |
| 目前不用 GPU | 三個模組只用到 numpy/scipy/sklearn/xgboost，沒有一個吃 CUDA。詳見第 2 節 |

### 現在買這台買到的是什麼

說清楚免得驗收時失望：**目前的效益是記憶體與 import 時間，不是 GPU。**

監控電腦只有 4 GB、常駐核心預算 60 MB，所以那台上的模組一律開短命子行程，
每跑一次都要重付 import 的錢（xgboost +119.5 MB、scipy +69.6 MB，外加載入
秒數）。Orin 有 16 GB，套件在啟動時就熱著，之後每次呼叫都是純運算。

GPU 要等到真的有模型要跑（`core/inference.py` 的 LSTM 目前預設關閉）才用得上。

---

## 2. 要不要用 Docker

**現階段：不要。用 venv + systemd。**

理由：

1. **Docker 在 Jetson 上最大的好處是拿到 CUDA 版 PyTorch**（`nvcr.io` 的
   `l4t-pytorch` 映像）。但這三個模組**都用不到 torch**，所以這個好處現在
   等於零。
2. **它消不掉真正的差異。** repo 裡現有的 `edge_backend/Dockerfile` 是
   `python:3.10-slim`、x86 用的，它自己的註解就寫了 Jetson 要換 L4T 基礎
   映像。CUDA 與 aarch64 wheel 的差異 Docker 沒辦法抹平，換句話說「用了
   Docker 就兩邊一致」在這個專案上不成立。
3. **xgboost 在 aarch64 可能要自己編譯**，放進容器只是把這個麻煩搬進去，
   還多一層 swap 與建置快取要顧。
4. **現場要能修。** 出問題時 `journalctl -u reactor-compute -n 50` 跟
   `systemctl restart` 任何人都做得來；多一層容器就多一層要排除的東西。

**什麼時候再回來用 Docker**：等到真的要在 Orin 上跑 CUDA 模型。那時直接用
`nvcr.io/nvidia/l4t-pytorch:<對應 JetPack 版本>` 當基礎映像，不要自己從
`python:3.10-slim` 疊——那條路會裝到沒有 CUDA 的 wheel，而且**不會報錯**。

---

## 3. 到貨後，裝軟體之前

### 3.1 系統與電源

```bash
cat /etc/nv_tegra_release          # 確認 L4T 版本，之後找 torch wheel 要對上
sudo nvpmodel -q                   # 目前電源模式
sudo nvpmodel -m 0                 # 0 = 最大效能
sudo jetson_clocks                 # 時脈拉滿（重開機後失效，見下）
```

`jetson_clocks` 重開機會失效。要固定的話加一個 systemd unit，或接受預設
（這條管線不吃即時性，不設也可以）。

### 3.2 固定 IP（★ 不做的話遲早會斷）

監控電腦的 `.env` 裡要寫 Orin 的位址。IP 一變，模組就全部開始失敗。

在路由器上用 MAC 綁定，或在 Orin 上設靜態 IP。設完記下來，第 5 節要用。

### 3.3 時間要對

```bash
timedatectl set-timezone Asia/Taipei
timedatectl                         # 確認 NTP 有同步
```

結果列會帶時間戳，兩台的時鐘差太多會讓排程與紀錄對不起來。

---

## 4. 安裝

把 repo 放到 Orin 上（git clone 或 scp 整包），然後：

```bash
cd Bioreactor-Edge-AI
bash deploy/install_jetson.sh
```

這支腳本可以重複執行，**不會覆蓋你的 `.env`**。它做的事依序是：

| 步驟 | 內容 | 為什麼 |
|---|---|---|
| 0 | 確認是不是 Jetson | 不是的話 CUDA/nvpmodel 步驟不適用，先講出來 |
| 1 | apt 裝 `python3-venv python3-dev build-essential cmake psmisc libopenblas-dev` | cmake/build-essential 給 xgboost 編譯用；psmisc 給 `start_backend.sh` 的 `fuser`；openblas 不裝 numpy/scipy 在 aarch64 會慢很多 |
| 2 | 檢查 swap | xgboost 編譯很吃記憶體，swap 不夠會被 OOM killer 砍掉，而訊息往往只有一個 `Killed` |
| 3 | 建 venv **`--system-site-packages`** | 見下方說明 |
| 4 | `pip install -r requirements-compute.txt` | ⚠ 不是 `requirements.txt`，那是給 4 GB 監控電腦的精簡清單 |
| 5 | 由範本建 `.env` 並寫入 `REACTOR_PROFILE=compute` | 「忘了改」會默默當成 monitor；拼錯則會被 `config.profile()` 當場擋下 |
| 6 | 跑 `selfcheck.py` | **不過就不啟動**。啟動一台設定錯的機器比不啟動更糟 |
| 7 | 裝並啟用 systemd 服務 | 開機自啟、當掉自動重開 |
| 8 | 實際打 `/health` | 不是「服務有起來」，是「真的回得了話」 |

### 為什麼 venv 一定要 `--system-site-packages`

NVIDIA 給 Jetson 的 CUDA 版 torch 裝在**系統** site-packages。普通 venv 看不到
它，於是有人會在 venv 裡 `pip install torch`——裝到 PyPI 的 aarch64 wheel，
**那個沒有 CUDA，而且不會報任何錯**。GPU 就這樣安靜地沒被用到。

> repo 裡兩份既有說明對這點不一致：`compute_node/README.md` 寫
> `python3 -m venv venv`（少了旗標），`start_backend.sh` 的註解則說 Jetson 上
> 通常直接用系統 python3。本流程統一成 `--system-site-packages`，兩個需求
> 都能滿足。

### 將來真的要裝 torch 的話

```bash
# 不要 pip install torch。用 NVIDIA 為你那版 JetPack 發布的 wheel。
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

印出 `True` 才算裝對。印 `False` 代表裝到 CPU 版，要重裝。

---

## 5. 監控電腦那邊要改什麼

`edge_backend/.env` 加一行，指到 Orin：

```
REACTOR_COMPUTE_URL=http://<Orin 的固定 IP>:8100
```

然後重啟監控電腦的後端。

**留空 = 照舊在本機開子行程跑**（單機部署、開發筆電、Orin 還沒到之前，
都留空就好）。

⚠ 設了之後若連不到 Orin，模組會**失敗**並在紀錄裡寫「連不到重運算節點」，
**不會**靜默退回本機跑。這是故意的——靜默退回的話，那台 16 GB 的機器可以
壞掉好幾個月而沒有人發現。

---

## 6. 驗收清單

照順序做完，每一項都要親眼看到才算數。

```bash
# ── 在 Orin 上 ────────────────────────────────────────────
systemctl status reactor-compute          # active (running)
curl -s localhost:8100/health | python3 -m json.tool
```

`/health` 要看到：

- `"role": "compute"` ← 不是 `monitor`
- `"modules"` 三個全是 `"ready"`，沒有錯誤字串
- `"warm_packages"` 裡 numpy/pandas/scipy/sklearn 都有版本號（不是 `null`）
- `"rss_mb"` 幾百 MB 是正常的——**這台就是要胖**

```bash
# ── 在監控電腦上 ──────────────────────────────────────────
python edge_backend\selfcheck.py          # 「重運算節點」那項要是 OK
curl http://127.0.0.1:8000/api/modules    # 看 backend 欄位
```

**`backend` 欄位是唯一能分辨「真的在用 Orin」還是「其實在本機跑」的地方。**
網頁上兩者看起來完全一樣。

最後跑一個模組，確認結果真的寫進監控電腦的資料庫（不是 Orin 的）。

---

## 7. 日常維運

```bash
systemctl restart reactor-compute          # 重啟
journalctl -u reactor-compute -n 50        # 看最近 50 行
journalctl -u reactor-compute -f           # 跟著看
systemctl disable --now reactor-compute    # 停用（會退回監控電腦本機跑嗎？不會，模組會失敗）
```

### 更新程式

```bash
cd Bioreactor-Edge-AI && git pull
bash deploy/install_jetson.sh              # 重跑即可，.env 不會被動到
```

⚠ 更新後要確認 `/health` 的 `modules` 仍然三個都 `ready`。模組的結果欄位
同時寫在 `run.py` 的 `SCHEMA` 與 `module.json` 的 `result_columns`，兩邊漂掉
`system_test` 第 14 項會紅。

---

## 8. 疑難排解

| 症狀 | 多半是 | 怎麼確認 |
|---|---|---|
| 監控電腦說「連不到重運算節點」 | IP 變了，或防火牆 | 在監控電腦上 `curl http://<IP>:8100/health` |
| `/health` 的 `modules` 有錯誤字串 | 相依沒裝全 | `journalctl -u reactor-compute -n 80` 看暖機時的 traceback |
| `warm_packages` 的 xgboost 是 `null` | aarch64 編譯失敗 | ch4_attribution 會退回 GA+Ridge，**能跑但結果較差**。不是致命的，但要知道 |
| 結果一直是舊的 | 模組其實沒跑，或在本機跑 | `GET /api/modules` 的 `backend` 欄位 |
| `torch.cuda.is_available()` 是 `False` | 裝到 PyPI 的 CPU wheel | 重裝 NVIDIA 的 wheel，見第 4 節 |
| 編 xgboost 編到一半只印 `Killed` | swap 不夠被 OOM killer 砍 | `free -h`，加 swap 後重試 |
| 服務一直重啟 | 暖機就失敗 | `journalctl` 看；`Restart=always` 會讓它每 5 秒重試一次 |

---

## 9. 已知限制與還沒做的

- **`compute_node` 沒有任何認證**，而且綁 `0.0.0.0`。同網段任何人都能
  `POST /run/<模組>`。目前靠區網隔離。要收緊的話在 Orin 上：

  ```bash
  sudo ufw allow from <監控電腦的IP> to any port 8100
  sudo ufw enable
  ```

- **GPU 目前完全沒用到。** 不是壞了，是三個模組都不需要。
- **沒有離線安裝包。** 監控電腦那套 `install.bat` 會帶 wheels，Jetson 這邊
  目前假設裝機時有網路。aarch64 的 wheel 要另外收，還沒做。
- **`edge_backend/Dockerfile` 是 x86 用的**，不要拿它在 Orin 上 build。
- **開發筆電連不到 broker 是預期的**，不是這次部署的問題。

---

## 相關檔案

| 檔案 | 用途 |
|---|---|
| `deploy/install_jetson.sh` | 本流程第 4 節的腳本 |
| `edge_backend/selfcheck.py` | 現場自檢，依 `REACTOR_PROFILE` 分流 |
| `edge_backend/compute_node/README.md` | 節點本身的設計說明與端點表 |
| `edge_backend/requirements-compute.txt` | 這台專用的相依清單 |
| `edge_backend/.env.example` | 設定範本，含兩台分工的說明 |
| `deploy/install.bat` | 監控電腦那台的對應腳本 |
