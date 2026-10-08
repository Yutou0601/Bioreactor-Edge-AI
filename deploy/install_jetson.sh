#!/usr/bin/env bash
# ===================================================================
#  INSTALL (Jetson Orin NX 16 GB)  --  重運算節點
#
#  對應 Windows 監控電腦的 deploy/install.bat。順序一樣，理由也一樣：
#
#      系統套件 -> venv -> 相依 -> .env -> 自檢 -> 啟動
#
#  自檢不過就**不啟動**。啟動一台設定錯的機器比不啟動更糟：服務會起來、
#  /health 會回 200，但模組要嘛沒載入、要嘛算錯，而監控電腦那邊只會看到
#  結果一直是舊的。
#
#  用法（在 Orin 上，repo 已經 clone 好）：
#      bash deploy/install_jetson.sh
#
#  可重複執行。你自己的 .env 不會被覆蓋。
# ===================================================================
set -u

cd "$(dirname "$0")/.." || exit 1
REPO="$PWD"
BE="$REPO/edge_backend"

say()  { printf '  %s\n' "$*"; }
fail() { printf '\n  [!] %s\n\n' "$*" >&2; exit 1; }

echo
echo "============================================================"
echo "  Bioreactor -- 重運算節點安裝（Jetson Orin NX）"
echo "============================================================"
say "repo: $REPO"
echo

# ---- 0  這台真的是 Jetson 嗎 ---------------------------------------
# 不是的話下面的 CUDA / nvpmodel 步驟都不適用，先講清楚再繼續。
if [ -f /etc/nv_tegra_release ]; then
  say "L4T: $(head -1 /etc/nv_tegra_release)"
else
  say "[!] 找不到 /etc/nv_tegra_release —— 這台不是 Jetson。"
  say "    腳本會繼續（x86 Linux 也跑得起來），但 CUDA 相關步驟請略過。"
fi
say "架構: $(uname -m)   核心: $(uname -r)"
echo

# ---- 1  系統套件 ----------------------------------------------------
# cmake / build-essential：xgboost 若 aarch64 沒有預編譯 wheel 會改成
#   從原始碼編譯，缺了這兩個會在編譯第一步就失敗。
# psmisc：start_backend.sh 用 fuser 清埠。
# libopenblas-dev：numpy/scipy 在 aarch64 上沒有它會慢很多。
say "安裝系統套件（需要 sudo）..."
sudo apt-get update -qq || fail "apt update 失敗，先確認網路。"
sudo apt-get install -y -qq \
  python3-venv python3-dev build-essential cmake \
  psmisc libopenblas-dev curl \
  || fail "apt install 失敗。"
say "系統套件 OK"
echo

# ---- 2  swap ---------------------------------------------------------
# ⚠ xgboost 從原始碼編譯很吃記憶體。swap 不夠時 OOM killer 會把編譯行程
#   砍掉，而訊息往往只有一個 "Killed"，完全看不出是記憶體問題。
SWAP_GB=$(awk '/SwapTotal/ {printf "%.1f", $2/1048576}' /proc/meminfo)
say "swap: ${SWAP_GB} GB"
if awk "BEGIN{exit !(${SWAP_GB} < 4.0)}"; then
  say "[!] swap 小於 4 GB。若稍後 xgboost 要自己編譯，很可能被 OOM killer 砍掉。"
  say "    要加的話："
  say "      sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile"
  say "      sudo mkswap /swapfile && sudo swapon /swapfile"
  say "      echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab"
fi
echo

# ---- 3  venv --------------------------------------------------------
# ⚠ 一定要 --system-site-packages。
#   NVIDIA 給 Jetson 的 CUDA 版 torch 是裝在**系統** site-packages 的；
#   普通的 venv 看不到它，於是有人會在 venv 裡 pip install torch，
#   裝到 PyPI 的 aarch64 wheel——那個沒有 CUDA，而且不會報錯。
#   （compute_node/README.md 寫 `python3 -m venv venv`，少了這個旗標；
#     start_backend.sh 的註解則說 Jetson 上通常直接用系統 python3。
#     兩邊說法不一致，這裡統一成 --system-site-packages，兩個需求都滿足。）
if [ ! -x "$BE/venv/bin/python" ]; then
  say "建立 venv（--system-site-packages）..."
  python3 -m venv --system-site-packages "$BE/venv" || fail "venv 建立失敗。"
else
  say "venv 已存在。"
fi
PY="$BE/venv/bin/python"
"$PY" -m pip install -q --upgrade pip setuptools wheel || fail "pip 升級失敗。"
say "python: $("$PY" -V)"
echo

# ---- 4  相依 --------------------------------------------------------
# ⚠ requirements-compute.txt，不是 requirements.txt。
#   後者是給 4 GB 監控電腦的精簡清單。
say "安裝相依（requirements-compute.txt）..."
if ! "$PY" -m pip install -q -r "$BE/requirements-compute.txt"; then
  say "[!] 整批安裝失敗——最常見的原因是 xgboost 在 aarch64 要自己編譯。"
  say "    改成先裝其餘的，xgboost 單獨處理："
  grep -v '^xgboost' "$BE/requirements-compute.txt" > /tmp/req-noxgb.txt
  "$PY" -m pip install -q -r /tmp/req-noxgb.txt || fail "相依安裝失敗。"
  say "    其餘相依 OK。xgboost 請自行補裝："
  say "      $PY -m pip install xgboost        # 會編譯，可能要十幾分鐘"
  say "    沒有 xgboost 也能上線：ch4_attribution 會退回 GA+Ridge。"
else
  say "相依 OK"
fi
echo

# ---- 5  站台設定 ----------------------------------------------------
if [ -f "$BE/.env" ]; then
  say ".env 已存在——你的設定不會被覆蓋。"
else
  cp "$BE/.env.example" "$BE/.env"
  # 這台是 compute。直接寫進去，不要讓人手動改而漏掉——
  # 拼錯會被 config.profile() 擋下，但「忘了改」會默默當成 monitor。
  sed -i 's/^REACTOR_PROFILE=.*/REACTOR_PROFILE=compute/' "$BE/.env"
  say "已由範本建立 .env，並設成 REACTOR_PROFILE=compute"
  say "*** compute 這台不需要 REACTOR_DATA_DIR，也不要設 REACTOR_COMPUTE_URL ***"
fi
echo

# ---- 6  自檢 --------------------------------------------------------
echo "------------------------------------------------------------"
( cd "$BE" && "$PY" selfcheck.py )
rc=$?
echo "------------------------------------------------------------"
if [ $rc -ne 0 ]; then
  echo
  fail "自檢不通過，服務沒有啟動。請先修掉上面標星號的項目，再跑一次本腳本。"
fi
echo

# ---- 7  開機自啟（systemd）------------------------------------------
say "安裝 systemd 服務..."
UNIT=/etc/systemd/system/reactor-compute.service
sudo tee "$UNIT" >/dev/null <<UNITEOF
[Unit]
Description=Bioreactor compute node (Jetson Orin NX)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BE
ExecStart=$PY -m compute_node.server
# 連不到或當掉就重開。模組端已經是「連不到就失敗、不靜默退回」，
# 所以這裡重開失敗的服務是安全的——不會讓錯的結果混進資料庫。
Restart=always
RestartSec=5
# Orin 有 16 GB，但還是給個上限，免得哪天記憶體洩漏把整台拖垮。
MemoryMax=12G
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNITEOF
sudo systemctl daemon-reload
sudo systemctl enable --now reactor-compute.service || fail "systemd 啟動失敗。"
sleep 3
say "服務狀態："
systemctl --no-pager --lines=0 status reactor-compute.service || true
echo

# ---- 8  實際打一下 ---------------------------------------------------
PORT=$(grep -E '^REACTOR_COMPUTE_PORT=' "$BE/.env" 2>/dev/null | cut -d= -f2)
PORT=${PORT:-8100}
say "確認 /health（埠 $PORT）..."
if curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health"; then
  echo
  echo
  say "完成。監控電腦那台的 edge_backend/.env 要加這一行："
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  say "    REACTOR_COMPUTE_URL=http://${IP:-<這台的IP>}:$PORT"
  say "改完重啟監控電腦的後端，用 GET /api/modules 的 backend 欄位確認。"
else
  echo
  fail "服務起來了但 /health 打不通。看紀錄：journalctl -u reactor-compute -n 50"
fi
echo
