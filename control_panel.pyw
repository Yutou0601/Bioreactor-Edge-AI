"""
生物甲烷化系統 — 桌面控制台
============================
雙擊即可啟動／更新／監看整套系統，現場不需要開終端機、不需要記指令。

**為什麼是桌面程式而不是做在網頁裡**：網頁前端要靠後端 API 才活得起來，
但「需要按啟動」的時機正好是後端沒在跑的時候——後端死了網頁就打不開，
按鈕也就不存在。故啟動／重啟／更新／健康度必須放在不依賴後端的地方。

**2026-07-22 事故背景**：監控電腦跑 Windows 自動更新洗掉記錄程式，資料靜默
中斷 17.5 小時無人察覺（反應器仍在運轉）。因此本控制台的核心不是「後端活著
嗎」，而是「**資料還有在進來嗎**」——資料新鮮度逾時會整片轉紅告警；另提供
「開機自動啟動」開關，讓機器被強制重開後系統能自己回來。

只用 Python 標準函式庫（tkinter/urllib/subprocess），不需額外安裝套件。
"""

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "edge_backend"
FRONTEND_DIR = ROOT / "web_frontend"
VENV_PY = BACKEND_DIR / "venv" / "Scripts" / "python.exe"
VENV_PYW = BACKEND_DIR / "venv" / "Scripts" / "pythonw.exe"
CONFIG_PATH = ROOT / "control_panel.json"

BACKEND_PORT = 8000

# 前端有兩種跑法，**必須跟後端位置一致**，否則網頁會去打錯的機器：
#   npm run preview :4173 → 用 .env.production，API 寫死 192.168.55.1（Jetson）
#   npm run dev     :5173 → 用 .env.development，API 指向 localhost
# 本機模式若開 preview，網頁會去找 Jetson 而顯示「後端無回應」。
PREVIEW_PORT = 4173      # 正式建置（打 Jetson）
DEV_PORT = 5173          # 開發模式（打 localhost）

# 正式部署時後端跑在 Jetson 上（web_frontend/.env.production 指向 192.168.55.1:8000），
# 本機只跑 CSV 監看與網頁前端。開發模式才用 127.0.0.1。
DEFAULT_BACKEND_HOST = "192.168.55.1"
DEFAULT_SSH_USER = "lee"
DEFAULT_JETSON_DIR = "~/edge_ai_project"

# 感測器記錄程式（把 serial 資料寫成 CSV）。這支若沒在跑＝沒有新 CSV＝資料靜默中斷
# （2026-07-22 事故）。控制台可直接啟動並監看它。路徑與資料夾可於 control_panel.json 覆寫。
DEFAULT_RECORDER = r"C:\Users\BTP\Desktop\data\BTP.SerialHarbor1.1.exe"
DEFAULT_CSV_DIR = r"C:\Users\BTP\Desktop\data"

# ssh 一律加 BatchMode：金鑰沒設好時「立刻失敗」而不是卡在看不見的密碼提示。
# 控制台是隱藏視窗＋接管輸出，互動式提示會無聲卡死，比報錯更難查。
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
            "-o", "StrictHostKeyChecking=accept-new"]
SSH_KEY = Path.home() / ".ssh" / "id_ed25519"

POLL_MS = 3000            # 狀態輪詢間隔
SSH_POLL_MS = 30000       # SSH 檢查間隔（獨立時鐘，逾時較久不可與狀態列同排）
GIT_POLL_EVERY = 20       # 每 N 次輪詢才查一次 git（較慢，不用每次）
CREATE_NO_WINDOW = 0x08000000

AUTOSTART_BAT = "bioreactor_autostart.bat"

# 啟動前的快速相依檢查（import 測試約 0.3 秒，遠快於每次都跑 pip install）
REQUIRED_MODULES = ["fastapi", "uvicorn", "pandas", "numpy", "openpyxl", "paho.mqtt.client"]

# Jetson 上**只**安裝這些新增套件。絕不在 Jetson 跑完整 requirements.txt——
# 那會覆蓋掉 NVIDIA 版的 CUDA torch/onnxruntime（sync_jetson.bat 既有的刻意決定）。
JETSON_SAFE_DEPS = ["openpyxl"]

# 配色（深色系，與網頁前端一致）
C_BG, C_PANEL, C_LINE = "#0d0d0d", "#141a20", "#1e2a34"
C_TEXT, C_DIM = "#e0e0e0", "#6a7a88"
C_OK, C_WARN, C_BAD, C_IDLE = "#4caf82", "#d0a24a", "#e05a5a", "#4a5a68"


def startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def port_open(port: int) -> bool:
    """用 TCP 連線判定服務是否在監聽——不管是誰啟動的都測得到。"""
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


class ControlPanel:
    def __init__(self, root: tk.Tk, autostart: bool = False):
        self.root = root
        self.cfg = load_config()
        self.procs: dict[str, subprocess.Popen] = {}
        self.log_q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
        self.poll_count = 0
        self.git_info = {"commit": "—", "behind": None}
        self.ssh_ok = None          # None=未知 / True=免密碼可用 / False=需設定

        root.title("生物甲烷化系統 — 控制台")
        root.geometry("760x680")
        root.configure(bg=C_BG)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_ui()
        self._drain_log()
        self._poll()
        self._ssh_poll()

        if autostart:
            self.log("以「開機自動啟動」模式啟動，正在自動拉起所有服務…", "info")
            self.root.after(800, self.start_all)

    # ── 連線設定 ────────────────────────────────────────
    @property
    def backend_host(self) -> str:
        return self.cfg.get("backend_host", DEFAULT_BACKEND_HOST)

    @property
    def is_remote(self) -> bool:
        """後端是否跑在 Jetson（正式部署）而非本機（開發）。"""
        return self.backend_host not in ("127.0.0.1", "localhost")

    @property
    def ssh_target(self) -> str:
        return f"{self.cfg.get('ssh_user', DEFAULT_SSH_USER)}@{self.backend_host}"

    @property
    def api_base(self) -> str:
        return f"http://{self.backend_host}:{BACKEND_PORT}/api"

    # 前端跑法跟著後端位置走，確保網頁打的是同一台機器
    @property
    def fe_port(self) -> int:
        return PREVIEW_PORT if self.is_remote else DEV_PORT

    @property
    def fe_mode(self) -> str:
        return "preview" if self.is_remote else "dev"

    @property
    def fe_url(self) -> str:
        return f"http://localhost:{self.fe_port}"

    # ── 感測器記錄程式（SerialHarbor）與 CSV 資料夾 ──
    @property
    def recorder_path(self) -> str:
        return self.cfg.get("recorder_path", DEFAULT_RECORDER)

    @property
    def csv_dir(self) -> str:
        return self.cfg.get("csv_dir") or DEFAULT_CSV_DIR

    def _recorder_running(self) -> bool:
        """用 tasklist 判斷記錄程式（exe）是否在執行——不管是誰啟動的都測得到。"""
        name = os.path.basename(self.recorder_path)
        out = self._run_out(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"])
        return name.lower() in out.lower()

    def _start_recorder(self) -> None:
        """啟動感測器記錄程式（若未在執行）。找不到 exe 時明確報錯、不中斷其他啟動。"""
        if self._recorder_running():
            self.log("記錄程式已在執行中，略過", "info")
            return
        exe = self.recorder_path
        if not os.path.exists(exe):
            self.log(f"找不到記錄程式：{exe}（可於 control_panel.json 設 recorder_path）", "bad")
            return
        try:
            # 於其所在資料夾啟動（多數記錄程式以工作目錄決定 CSV 輸出位置）
            subprocess.Popen([exe], cwd=os.path.dirname(exe) or None)
            self.log(f"已啟動記錄程式：{os.path.basename(exe)}", "ok")
        except Exception as e:
            self.log(f"啟動記錄程式失敗：{e}", "bad")

    def _ssh(self, remote_cmd: str) -> list:
        # 金鑰存在時，強制只用「我們這把」金鑰（-i + IdentitiesOnly），避免 ssh 去試
        # agent 或其他預設金鑰造成時好時壞。金鑰不存在時不加 -i（會正確地失敗＝尚未設定）。
        key_opts = ["-i", str(SSH_KEY), "-o", "IdentitiesOnly=yes"] if SSH_KEY.exists() else []
        return ["ssh", *key_opts, *SSH_OPTS, self.ssh_target, remote_cmd]

    def _ssh_check(self) -> bool:
        """測試免密碼登入是否可用。BatchMode 下若需密碼會直接失敗，不會卡住。"""
        try:
            p = subprocess.run(self._ssh("echo ok"), capture_output=True, text=True,
                               timeout=12, creationflags=CREATE_NO_WINDOW)
            return p.returncode == 0 and "ok" in p.stdout
        except Exception:
            return False

    # ── 介面 ────────────────────────────────────────────
    def _build_ui(self):
        tk.Label(self.root, text="生物甲烷化系統 控制台", bg=C_BG, fg="#6cb6e8",
                 font=("Microsoft JhengHei UI", 15, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self.root, text="啟動 · 更新 · 監看　（現場不需開終端機）", bg=C_BG, fg=C_DIM,
                 font=("Microsoft JhengHei UI", 9)).pack(anchor="w", padx=16, pady=(0, 10))

        # 狀態區
        box = tk.Frame(self.root, bg=C_PANEL, highlightbackground=C_LINE, highlightthickness=1)
        box.pack(fill="x", padx=16)
        self.rows = {}
        for key, label in [("backend", "後端 API"), ("data", "資料記錄"),
                           ("recorder", "記錄程式"), ("ssh", "Jetson 連線"),
                           ("watcher", "CSV 監看"), ("frontend", "網頁前端")]:
            r = tk.Frame(box, bg=C_PANEL)
            r.pack(fill="x", padx=14, pady=(9 if key == "backend" else 3, 3))
            dot = tk.Label(r, text="●", bg=C_PANEL, fg=C_IDLE, font=("Segoe UI", 11))
            dot.pack(side="left")
            tk.Label(r, text=label, bg=C_PANEL, fg=C_TEXT, width=10, anchor="w",
                     font=("Microsoft JhengHei UI", 10)).pack(side="left", padx=(8, 0))
            val = tk.Label(r, text="檢查中…", bg=C_PANEL, fg=C_DIM, anchor="w",
                           font=("Consolas", 10))
            val.pack(side="left", fill="x", expand=True)
            self.rows[key] = (dot, val)

        self.ver_lbl = tk.Label(box, text="版本 —", bg=C_PANEL, fg=C_DIM, anchor="w",
                                font=("Consolas", 9))
        self.ver_lbl.pack(fill="x", padx=14, pady=(4, 10))

        # 按鈕區
        btns = tk.Frame(self.root, bg=C_BG)
        btns.pack(fill="x", padx=16, pady=12)
        self.btn = {}
        specs = [("start", "全部啟動", self.start_all, "#1d6b45"),
                 ("stop", "停止全部", self.stop_all, "#6b2d2d"),
                 ("restart", "重啟後端", self.restart_backend, "#2a4a6b"),
                 ("update", "檢查更新", self.check_update, "#4a3a6b"),
                 ("watch", "啟動記錄+監看", self.start_watch, "#1d5b6b"),
                 ("web", "開啟網頁", self.open_web, "#2a2a2a"),
                 ("csv", "匯入 CSV", self.import_csv, "#2a2a2a"),
                 ("sshkey", "設定 Jetson 免密登入", self.setup_ssh_key, "#5a4a2a"),
                 ("target", "切換後端位置", self.switch_target, "#2a2a2a")]
        for i, (k, text, cmd, color) in enumerate(specs):
            b = tk.Button(btns, text=text, command=cmd, bg=color, fg="#e8e8e8",
                          activebackground=color, relief="flat", bd=0, padx=10, pady=8,
                          font=("Microsoft JhengHei UI", 10, "bold"), cursor="hand2")
            b.grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3)
            self.btn[k] = b
        for c in range(3):
            btns.columnconfigure(c, weight=1)
        self.btn["sshkey"].configure(font=("Microsoft JhengHei UI", 9, "bold"))
        self.btn["target"].configure(font=("Microsoft JhengHei UI", 9))

        # 開機自動啟動
        opt = tk.Frame(self.root, bg=C_BG)
        opt.pack(fill="x", padx=16)
        self.auto_var = tk.BooleanVar(value=self.autostart_enabled())
        tk.Checkbutton(opt, text="開機自動啟動（重開機後自動拉起所有服務）",
                       variable=self.auto_var, command=self.toggle_autostart,
                       bg=C_BG, fg=C_TEXT, selectcolor=C_PANEL, activebackground=C_BG,
                       activeforeground=C_TEXT, font=("Microsoft JhengHei UI", 9),
                       cursor="hand2", bd=0, highlightthickness=0).pack(anchor="w")

        # 日誌
        tk.Label(self.root, text="日誌", bg=C_BG, fg=C_DIM,
                 font=("Microsoft JhengHei UI", 9)).pack(anchor="w", padx=16, pady=(10, 2))
        wrap = tk.Frame(self.root, bg=C_BG)
        wrap.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self.log_box = tk.Text(wrap, bg="#0a0f14", fg="#9aa8b4", bd=0, wrap="word",
                               font=("Consolas", 9), insertbackground=C_TEXT)
        sb = ttk.Scrollbar(wrap, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)
        for tag, col in [("info", "#6a8296"), ("ok", C_OK), ("warn", C_WARN),
                         ("bad", C_BAD), ("cmd", "#7a6ab4")]:
            self.log_box.tag_config(tag, foreground=col)

    # ── 日誌 ────────────────────────────────────────────
    def log(self, text: str, tag: str = "info"):
        self.log_q.put((f"[{datetime.now():%H:%M:%S}] {text}", tag))

    def _drain_log(self):
        try:
            while True:
                text, tag = self.log_q.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", text + "\n", tag)
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(150, self._drain_log)

    # ── 狀態輪詢 ────────────────────────────────────────
    def _poll(self):
        threading.Thread(target=self._poll_worker, daemon=True).start()
        self.root.after(POLL_MS, self._poll)

    def _ssh_poll(self):
        """SSH 檢查獨立一條執行緒與時鐘——它逾時可長達 12 秒，若與健康檢查同排，
        會週期性凍住整個狀態列。"""
        if self.is_remote and not self.busy:
            threading.Thread(target=self._ssh_poll_worker, daemon=True).start()
        self.root.after(SSH_POLL_MS, self._ssh_poll)

    def _ssh_poll_worker(self):
        ok = self._ssh_check()
        self.root.after(0, lambda: setattr(self, "ssh_ok", ok))

    def _poll_worker(self):
        health = None
        try:
            with urllib.request.urlopen(f"{self.api_base}/health", timeout=2.5) as r:
                health = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError:
            health = None                      # 連不上＝後端沒跑（或 Jetson 沒接）
        except Exception:
            health = {}                        # 連得上但回應不對
        fe = port_open(self.fe_port)
        watcher = self._proc_alive("watcher")
        recorder = self._recorder_running()

        self.poll_count += 1
        if self.poll_count % GIT_POLL_EVERY == 1:
            self._refresh_git()
        self.root.after(0, lambda: self._render(health, fe, watcher, recorder))

    def _render(self, health, fe_up, watcher_up, recorder_up=False):
        where = f"Jetson {self.backend_host}" if self.is_remote else "本機"
        # 後端
        if health is None:
            self._row("backend", C_BAD, f"未執行（{where}:{BACKEND_PORT} 連不上）")
        elif not health:
            self._row("backend", C_WARN, f"{where} 有回應但 /health 失敗")
        else:
            self._row("backend", C_OK,
                      f"執行中 {where}:{BACKEND_PORT} · 已運行 {health.get('uptime_min', 0)} 分 · "
                      f"{health.get('record_count', 0)} 筆")

        # 資料記錄（本控制台的重點：後端活著不代表資料有在進來）
        if health is None:
            self._row("data", C_IDLE, "—（後端未執行）")
        elif not health:
            self._row("data", C_IDLE, "—（無法取得健康狀態）")
        elif health.get("last_timestamp") is None:
            self._row("data", C_WARN, "尚無資料（可能需匯入 CSV 或啟動 CSV 監看）")
        elif health.get("data_stale"):
            self._row("data", C_BAD,
                      f"⛔ 已停止進資料 {health['staleness_min']} 分鐘"
                      f"（最後 {health['last_timestamp'][5:16]}）")
        else:
            run = health.get("running_run")
            self._row("data", C_OK,
                      f"正常 · 最後一筆 {health['staleness_min']} 分前"
                      + (f" · 進行中批次 {run}" if run else ""))

        # 記錄程式（SerialHarbor）：寫 CSV 的源頭，沒跑＝資料會靜默中斷
        name = os.path.basename(self.recorder_path)
        if recorder_up:
            self._row("recorder", C_OK, f"執行中 · {name}")
        elif os.path.exists(self.recorder_path):
            self._row("recorder", C_BAD, f"⛔ 未執行（按「啟動記錄+監看」）· {name}")
        else:
            self._row("recorder", C_IDLE, f"—（本機找不到 {name}）")

        # Jetson 連線：免密碼登入是否已設定（決定能不能遠端啟動後端）
        if not self.is_remote:
            self._row("ssh", C_IDLE, "—（後端設為本機，不需 SSH）")
        elif self.ssh_ok is None:
            self._row("ssh", C_IDLE, "檢查中…")
        elif self.ssh_ok:
            self._row("ssh", C_OK, f"免密碼登入正常 · {self.ssh_target}")
        else:
            self._row("ssh", C_WARN,
                      f"需設定免密碼登入（按下方按鈕，只需輸入一次密碼）· {self.ssh_target}")

        self._row("watcher", C_OK if watcher_up else C_IDLE,
                  "執行中" if watcher_up else "未由本控制台啟動")
        self._row("frontend", C_OK if fe_up else C_IDLE,
                  f"執行中 {self.fe_url}（{self.fe_mode}）" if fe_up
                  else f"未執行（本模式應跑 npm run {self.fe_mode}）")

        behind = self.git_info["behind"]
        ver = f"版本 {self.git_info['commit']}"
        if behind is None:
            ver += " · 更新狀態未知"
        elif behind == 0:
            ver += " · 已是最新"
        else:
            ver += f" · ⚠ 落後 origin {behind} 個 commit（可按「檢查更新」）"
        self.ver_lbl.configure(text=ver, fg=C_WARN if behind else C_DIM)

    def _row(self, key, color, text):
        dot, val = self.rows[key]
        dot.configure(fg=color)
        val.configure(text=text, fg=C_TEXT if color in (C_OK, C_BAD) else C_DIM)

    def _refresh_git(self):
        try:
            self.git_info["commit"] = self._run_out(["git", "rev-parse", "--short", "HEAD"]) or "—"
            self._run_out(["git", "fetch", "--quiet"])
            n = self._run_out(["git", "rev-list", "--count", "HEAD..origin/main"])
            self.git_info["behind"] = int(n) if n and n.isdigit() else None
        except Exception:
            pass

    def _run_out(self, cmd) -> str:
        try:
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                               timeout=25, creationflags=CREATE_NO_WINDOW)
            return p.stdout.strip()
        except Exception:
            return ""

    # ── 行程管理 ────────────────────────────────────────
    def _proc_alive(self, key) -> bool:
        p = self.procs.get(key)
        return p is not None and p.poll() is None

    def _spawn(self, key: str, cmd: list, cwd: Path, label: str):
        """啟動子行程並把它的輸出即時串到日誌面板（現場看得到錯誤訊息）。"""
        try:
            p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", bufsize=1, creationflags=CREATE_NO_WINDOW)
        except FileNotFoundError as e:
            self.log(f"{label} 啟動失敗：找不到執行檔（{e}）", "bad")
            return
        self.procs[key] = p
        self.log(f"{label} 已啟動（PID {p.pid}）", "ok")
        threading.Thread(target=self._pump, args=(p, label), daemon=True).start()

    def _pump(self, p: subprocess.Popen, label: str):
        for line in p.stdout:
            line = line.rstrip()
            if line:
                self.log(f"  [{label}] {line}")
        code = p.wait()
        self.log(f"{label} 已結束（代碼 {code}）", "warn" if code else "info")

    def _kill_port(self, port: int):
        """殺掉佔用該埠的行程——涵蓋「不是本控制台啟動」的既有後端。"""
        out = self._run_out(["netstat", "-ano"])
        pids = {ln.split()[-1] for ln in out.splitlines()
                if f":{port} " in ln and "LISTENING" in ln}
        for pid in pids:
            self._run_out(["taskkill", "/F", "/PID", pid])
            self.log(f"已停止佔用 port {port} 的行程 PID {pid}", "info")

    def _guard(self) -> bool:
        if self.busy:
            self.log("上一個作業還在進行中，請稍候…", "warn")
            return False
        return True

    def _task(self, fn):
        """把耗時作業丟到背景執行緒，避免視窗卡住。"""
        self.busy = True
        for b in self.btn.values():
            b.configure(state="disabled")

        def wrapper():
            try:
                fn()
            except Exception as e:
                self.log(f"作業失敗：{e}", "bad")
            finally:
                self.busy = False
                self.root.after(0, lambda: [b.configure(state="normal") for b in self.btn.values()])
        threading.Thread(target=wrapper, daemon=True).start()

    # ── 動作 ────────────────────────────────────────────
    def _check_venv(self) -> bool:
        if VENV_PY.exists():
            return True
        self.log(f"找不到 venv：{VENV_PY}", "bad")
        self.log("請先在 edge_backend 執行：python -m venv venv 並安裝 requirements.txt", "warn")
        return False

    def start_all(self):
        if not self._guard():
            return
        self._task(self._start_all_worker)

    def _missing_modules(self) -> list:
        """用 venv 的 python 試 import，找出缺哪些套件（比每次跑 pip 快得多）。
        所有模組在**同一個** python 行程內檢查——分別開 6 個行程要近 2 秒，
        併成一次約 0.3 秒，才不會拖慢每次啟動。"""
        probe = (
            "import importlib.util as u\n"
            f"mods = {REQUIRED_MODULES!r}\n"
            "print(','.join(m for m in mods if u.find_spec(m) is None))"
        )
        try:
            p = subprocess.run([str(VENV_PY), "-c", probe], capture_output=True,
                               text=True, timeout=60, creationflags=CREATE_NO_WINDOW)
        except Exception:
            return list(REQUIRED_MODULES)      # venv 不存在／叫不動＝全部視為缺
        if p.returncode != 0:
            return list(REQUIRED_MODULES)
        return [m for m in p.stdout.strip().split(",") if m]

    def _ensure_deps(self) -> bool:
        """啟動本機後端前確保套件齊全；缺了才自動安裝。
        僅適用本機 venv——Jetson 另有安全清單，見 JETSON_SAFE_DEPS。"""
        missing = self._missing_modules()
        if not missing:
            return True
        self.log(f"偵測到缺少套件：{', '.join(missing)}，自動安裝中…", "warn")
        ok = self._run_stream([str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"],
                              BACKEND_DIR, "pip")
        if not ok:
            self.log("套件安裝失敗，後端可能無法啟動。請看上方輸出。", "bad")
            return False
        still = self._missing_modules()
        if still:
            self.log(f"安裝後仍缺：{', '.join(still)}", "bad")
            return False
        self.log("套件已補齊。", "ok")
        return True

    def _backend_up(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.api_base}/health", timeout=2.5):
                return True
        except Exception:
            return False

    def _start_backend(self) -> None:
        """啟動後端。正式部署時後端在 Jetson，需 SSH 遠端啟動。"""
        if self._backend_up():
            self.log("後端已在執行中，略過啟動", "info")
            return

        if not self.is_remote:
            if not self._check_venv() or not self._ensure_deps():
                return
            self.log("啟動本機後端…", "cmd")
            self._spawn("backend", [str(VENV_PY), "main.py"], BACKEND_DIR, "後端")
            return

        # ── 遠端（Jetson）──
        if not self._ssh_check():
            self.ssh_ok = False
            self.log("無法免密碼連線 Jetson，不能遠端啟動後端。", "bad")
            self.log("請按「設定 Jetson 免密登入」（只需輸入一次密碼）後再試。", "warn")
            return
        self.ssh_ok = True
        jdir = self.cfg.get("jetson_dir", DEFAULT_JETSON_DIR)
        # 不呼叫 start_backend.sh —— 它結尾有 `read -p "Press Enter"` 會卡住 SSH。
        # 改為釋放埠後用 nohup 背景啟動，SSH 斷線後仍繼續執行。
        remote = (f"cd {jdir}/edge_backend && "
                  "(fuser -k 8000/tcp 2>/dev/null || true) && sleep 1 && "
                  "nohup python3 main.py > /tmp/bioreactor_backend.log 2>&1 & "
                  "sleep 3; echo launched")
        self.log(f"透過 SSH 啟動 Jetson 後端（{self.ssh_target}）…", "cmd")
        if self._run_stream(self._ssh(remote), ROOT, "Jetson"):
            self.log("Jetson 後端啟動指令已送出，等待服務起來…", "info")
        else:
            self.log("Jetson 後端啟動失敗，詳見上方輸出。", "bad")

    def _start_watcher(self) -> None:
        """啟動 CSV 監看（把新 CSV 列轉發到 broker）。資料夾預設 DEFAULT_CSV_DIR。"""
        if self._proc_alive("watcher"):
            self.log("CSV 監看已在執行中，略過", "info")
            return
        if not self._check_venv():
            return
        self.log(f"啟動 CSV 監看：{self.csv_dir} → broker {self.backend_host}", "cmd")
        self._spawn("watcher", [str(VENV_PY), "csv_watcher.py", "--dir", self.csv_dir,
                                "--broker", self.backend_host], BACKEND_DIR, "CSV監看")

    def start_watch(self):
        """按鈕：啟動感測器記錄程式 + CSV 監看（資料鏈：記錄程式寫 CSV → 監看轉發 broker）。"""
        if not self._guard():
            return
        self._task(lambda: (self._start_recorder(), self._start_watcher(),
                            self.log("記錄+監看啟動程序完成。", "ok")))

    def _start_all_worker(self):
        self._start_backend()
        self._start_recorder()
        self._start_watcher()

        if port_open(self.fe_port):
            self.log("網頁前端已在執行中，略過", "info")
        else:
            npm = self._npm()
            if npm:
                self.log("啟動網頁前端…", "cmd")
                # preview 走正式建置（API 打 Jetson）、dev 走開發設定（API 打 localhost）
                self._spawn("frontend", [npm, "run", self.fe_mode], FRONTEND_DIR, "前端")
            else:
                self.log("找不到 npm，略過前端啟動", "warn")
        self.log("啟動程序完成。", "ok")

    def _npm(self):
        import shutil
        return shutil.which("npm") or shutil.which("npm.cmd")

    def stop_all(self):
        if not self._guard():
            return
        extra = ("\n\n注意：Jetson 上的後端**不會**被停止（它正在記錄資料）。\n"
                 "若真要停止 Jetson 後端，請用「重啟後端」或到 Jetson 上操作。"
                 if self.is_remote else "")
        if not messagebox.askyesno("停止全部",
                                   "確定要停止本機的服務嗎？\n"
                                   "（反應器本身不受影響）" + extra):
            return
        self._task(self._stop_all_worker)

    def _stop_all_worker(self):
        for key, label in [("watcher", "CSV監看"), ("frontend", "前端"), ("backend", "後端")]:
            p = self.procs.get(key)
            if p and p.poll() is None:
                p.terminate()
                self.log(f"{label} 已停止", "info")
        if self.is_remote:
            # 刻意不動 Jetson 後端：它正在記錄資料，靜默停掉正是要避免的事故模式
            self.log("Jetson 後端未被停止（仍在記錄資料）。", "info")
        else:
            self._kill_port(BACKEND_PORT)
        self.log("停止完成。", "ok")

    def restart_backend(self):
        if not self._guard():
            return
        self._task(self._restart_backend_worker)

    def _restart_backend_worker(self):
        self.log("重啟後端…", "cmd")
        if self.is_remote:
            if not self._ssh_check():
                self.log("無法免密碼連線 Jetson，請先按「設定 Jetson 免密登入」。", "bad")
                return
            self._run_stream(self._ssh("fuser -k 8000/tcp 2>/dev/null || true"), ROOT, "Jetson")
            self._start_backend()
        else:
            if not self._check_venv():
                return
            p = self.procs.get("backend")
            if p and p.poll() is None:
                p.terminate()
            self._kill_port(BACKEND_PORT)
            self._spawn("backend", [str(VENV_PY), "main.py"], BACKEND_DIR, "後端")
        self.log("後端已重啟。注意：重啟後記憶體資料會清空，需要時請重新匯入 CSV。", "warn")

    def check_update(self):
        if not self._guard():
            return
        self._task(self._update_worker)

    def _update_worker(self):
        self.log("檢查更新中…", "cmd")
        self._refresh_git()
        behind = self.git_info["behind"]

        if behind == 0:
            # 已在最新版不代表「不用做事」：若剛才是手動 git pull 拉的，
            # 前端還沒重建、Jetson 也還沒同步，直接跳過會留下前後端版本不一致。
            if not messagebox.askyesno(
                    "已是最新版本",
                    "程式碼已是最新（可能是剛才手動 git pull 過）。\n\n"
                    "但**前端可能尚未重建、Jetson 可能尚未同步**。\n"
                    "要重新執行「安裝套件 → 重建前端 → 同步 Jetson → 重啟後端」嗎？"):
                self.log("已是最新版本，未執行其他動作。", "ok")
                return
            self.log("已是最新版，仍執行重建與同步…", "info")
        else:
            if behind is None:
                self.log("無法確認遠端狀態（可能沒網路）。", "warn")
            if not messagebox.askyesno(
                    "執行更新",
                    f"遠端有 {behind if behind else '未知數量'} 個新 commit。\n\n"
                    "更新會執行：git pull → 安裝套件 → 重建前端 → 同步 Jetson → 重啟後端。\n"
                    "期間記錄會短暫中斷，且後端記憶體資料會清空（需重新匯入 CSV）。\n\n"
                    "確定要現在更新嗎？"):
                self.log("已取消更新。", "info")
                return

        self.log("執行 git pull（本機）…", "cmd")
        if not self._run_stream(["git", "pull"], ROOT, "git pull"):
            self.log("git pull 失敗，中止更新。", "bad")
            return

        if VENV_PY.exists():
            self.log("安裝本機後端套件…", "cmd")
            self._run_stream([str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"],
                             BACKEND_DIR, "pip")
        else:
            self.log("本機無 venv，略過套件安裝（後端在 Jetson 時屬正常）。", "info")

        npm = self._npm()
        if npm:
            self.log("重建前端…", "cmd")
            self._run_stream([npm, "run", "build"], FRONTEND_DIR, "npm build")
        else:
            self.log("找不到 npm，略過前端重建。", "warn")

        # 後端在 Jetson 時，Jetson 上的程式碼也要更新，否則只有前端換了新版
        if self.is_remote:
            if self._ssh_check():
                jdir = self.cfg.get("jetson_dir", DEFAULT_JETSON_DIR)
                self.log("更新 Jetson 程式碼…", "cmd")
                self._run_stream(self._ssh(f"cd {jdir} && git pull"), ROOT, "Jetson git")
                # 只裝安全清單，不跑完整 requirements.txt——避免覆蓋 NVIDIA CUDA 版
                # 的 torch/onnxruntime（沿用 sync_jetson.bat 的刻意決定）
                self.log(f"安裝 Jetson 新增套件（僅 {', '.join(JETSON_SAFE_DEPS)}）…", "cmd")
                self._run_stream(self._ssh(f"pip3 install {' '.join(JETSON_SAFE_DEPS)}"),
                                 ROOT, "Jetson pip")
            else:
                self.log("無法連線 Jetson，其程式碼未更新！請設定免密登入後重試。", "bad")

        self._restart_backend_worker()
        self._refresh_git()
        self.log("更新完成。", "ok")

    def _run_stream(self, cmd, cwd, label) -> bool:
        try:
            p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", bufsize=1, creationflags=CREATE_NO_WINDOW)
        except FileNotFoundError as e:
            self.log(f"{label} 找不到執行檔：{e}", "bad")
            return False
        for line in p.stdout:
            line = line.rstrip()
            if line:
                self.log(f"  [{label}] {line}")
        return p.wait() == 0

    def open_web(self):
        if not port_open(self.fe_port):
            self.log("網頁前端未執行，請先按「全部啟動」。", "warn")
            return
        webbrowser.open(self.fe_url)
        self.log(f"已開啟 {self.fe_url}（{self.fe_mode} 模式，API → {self.api_base}）", "info")

    def import_csv(self):
        if not self._guard():
            return
        if not self._backend_up():
            self.log("後端未執行，無法匯入。請先啟動後端。", "warn")
            return
        folder = filedialog.askdirectory(title="選擇 CSV 資料夾（BTP_Sensor_log-*.csv）",
                                         initialdir=self.cfg.get("csv_dir") or str(ROOT))
        if not folder:
            return
        self.cfg["csv_dir"] = folder          # 記住，之後「全部啟動」可直接拉起 CSV 監看
        save_config(self.cfg)
        self.log(f"匯入資料夾：{folder} → {self.api_base}", "cmd")
        # 後端可能在 Jetson 上，要把 API 位址一起帶過去（預設是 127.0.0.1）
        self._task(lambda: self._run_stream(
            [str(VENV_PY), "batch_import_csv.py", "--dir", folder, "--api", self.api_base],
            BACKEND_DIR, "匯入"))

    # ── Jetson 免密碼登入 ───────────────────────────────
    def setup_ssh_key(self):
        """一次性設定 SSH 金鑰。設定完成後所有遠端操作都不再需要密碼。

        Windows 內建的 ssh.exe 無法用參數或管線餵密碼（它直接讀終端機），
        故不可能把密碼寫死在程式裡自動登入；金鑰是唯一能無人值守運作的方式，
        也避免把密碼存在檔案中。安裝公鑰那一步需要輸入密碼，僅此一次。
        """
        if not self.is_remote:
            self.log("目前後端設為本機，不需要 SSH 金鑰。", "info")
            return
        if not messagebox.askyesno(
                "設定 Jetson 免密登入",
                f"將對 {self.ssh_target} 設定 SSH 金鑰登入。\n\n"
                "步驟：\n"
                "1. 若尚無金鑰，會自動產生（不設通行碼）\n"
                "2. 開啟一個命令視窗安裝公鑰到 Jetson\n"
                "   → 該視窗會要求輸入 Jetson 密碼，**只需要這一次**\n\n"
                "完成後控制台即可自動啟動／重啟 Jetson 後端。\n"
                "要繼續嗎？"):
            return
        self._task(self._setup_ssh_key_worker)

    def _setup_ssh_key_worker(self):
        if not SSH_KEY.exists():
            self.log("產生 SSH 金鑰…", "cmd")
            SSH_KEY.parent.mkdir(parents=True, exist_ok=True)
            if not self._run_stream(
                    ["ssh-keygen", "-t", "ed25519", "-f", str(SSH_KEY), "-N", "", "-q"],
                    ROOT, "ssh-keygen"):
                self.log("金鑰產生失敗。", "bad")
                return
            self.log(f"已產生金鑰：{SSH_KEY}", "ok")
        else:
            self.log(f"已有金鑰，沿用：{SSH_KEY}", "info")

        pub = Path(str(SSH_KEY) + ".pub")
        if not pub.exists():
            self.log(f"找不到公鑰 {pub}", "bad")
            return

        # 安裝公鑰採 ssh-copy-id 標準做法：公鑰用管線 pipe 進遠端 cat，命令不含公鑰內容。
        # bat 內容一律**純 ASCII**（先前中文在 .bat 出過事），並用 CREATE_NEW_CONSOLE 直接
        # 開新主控台跑 cmd /k（不經 start，避免 start 標題引號那類坑）；/k 讓視窗**永遠留著**，
        # 不管哪一步失敗都看得到錯誤訊息（這正是使用者要的）。
        remote = ("umask 077 && mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && "
                  "sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys")
        bat = ROOT / "_install_pubkey.bat"
        bat.write_text(
            "@echo off\r\n"
            "echo Installing public key to Jetson. Enter the password when prompted.\r\n"
            "echo Target: " + self.ssh_target + "\r\n"
            "echo.\r\n"
            f'type "{pub}" | ssh -o StrictHostKeyChecking=accept-new {self.ssh_target} "{remote}"\r\n'
            "echo.\r\n"
            "if %ERRORLEVEL%==0 (echo [OK] key installed.) else (echo [FAIL] errorlevel %ERRORLEVEL%)\r\n"
            "echo ==== Press any key to close this window ====\r\n"
            "pause >nul\r\n",
            encoding="ascii")
        self.log("已開新視窗安裝公鑰——請在該視窗輸入 Jetson 密碼（只需這一次），"
                 "完成或失敗都會停在視窗顯示訊息。", "warn")
        CREATE_NEW_CONSOLE = 0x00000010
        try:
            # 乾淨的 argv list（Python 自動處理 bat 路徑引號）；新主控台 + /k 保證視窗留著。
            p = subprocess.Popen(["cmd", "/k", str(bat)], creationflags=CREATE_NEW_CONSOLE)
            p.wait(timeout=600)
        except Exception:
            pass          # 使用者可能沒關視窗；成功與否一律以 _ssh_check 為準
        finally:
            try:
                bat.unlink()
            except Exception:
                pass

        if self._ssh_check():
            self.ssh_ok = True
            self.log("免密碼登入設定成功，之後不再需要輸入密碼。", "ok")
        else:
            self.ssh_ok = False
            self.log("仍無法免密碼登入。請確認密碼是否正確、Jetson 是否連線（USB-C 或網路）。", "bad")

    def switch_target(self):
        """在「Jetson（正式）」與「本機（開發）」之間切換後端位置。"""
        to_local = self.is_remote
        target = "本機 127.0.0.1" if to_local else f"Jetson {DEFAULT_BACKEND_HOST}"
        if not messagebox.askyesno("切換後端位置",
                                   f"要把後端位置切換成「{target}」嗎？\n\n"
                                   "正式部署時後端跑在 Jetson 上（前端正式版也是打 Jetson）；\n"
                                   "本機模式僅供開發測試使用。"):
            return
        self.cfg["backend_host"] = "127.0.0.1" if to_local else DEFAULT_BACKEND_HOST
        save_config(self.cfg)
        self.ssh_ok = None
        self.log(f"後端位置已切換為 {target}。", "ok")

    # ── 開機自動啟動 ────────────────────────────────────
    def autostart_enabled(self) -> bool:
        return (startup_dir() / AUTOSTART_BAT).exists()

    def toggle_autostart(self):
        path = startup_dir() / AUTOSTART_BAT
        try:
            if self.auto_var.get():
                pyw = VENV_PYW if VENV_PYW.exists() else Path(sys.executable).with_name("pythonw.exe")
                # 用 .bat 而非捷徑：純文字、看得懂、要取消直接刪檔即可
                path.write_text(
                    "@echo off\r\n"
                    f'cd /d "{ROOT}"\r\n'
                    f'start "" "{pyw}" "{Path(__file__).resolve()}" --autostart\r\n',
                    encoding="utf-8")
                self.log(f"已設定開機自動啟動：{path}", "ok")
                self.log("下次開機（含 Windows 更新後重開）會自動拉起所有服務。", "info")
            else:
                path.unlink(missing_ok=True)
                self.log("已取消開機自動啟動。", "info")
        except Exception as e:
            self.log(f"設定開機自動啟動失敗：{e}", "bad")
            self.auto_var.set(self.autostart_enabled())

    # ── 關閉 ────────────────────────────────────────────
    def on_close(self):
        alive = [k for k in ("backend", "watcher", "frontend") if self._proc_alive(k)]
        if alive and not messagebox.askyesno(
                "關閉控制台",
                "關閉控制台會一併停止由它啟動的服務（後端／CSV監看／前端），\n"
                "資料記錄將中斷。\n\n確定要關閉嗎？\n\n"
                "（若只是想收起視窗、讓記錄繼續，請改為最小化。）"):
            return
        for k in alive:
            try:
                self.procs[k].terminate()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    ControlPanel(root, autostart="--autostart" in sys.argv)
    root.mainloop()
