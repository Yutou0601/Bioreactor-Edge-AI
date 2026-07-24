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

API_BASE = "http://127.0.0.1:8000/api"
BACKEND_PORT = 8000
PREVIEW_PORT = 4173
PREVIEW_URL = f"http://localhost:{PREVIEW_PORT}"

POLL_MS = 3000            # 狀態輪詢間隔
GIT_POLL_EVERY = 20       # 每 N 次輪詢才查一次 git（較慢，不用每次）
CREATE_NO_WINDOW = 0x08000000

AUTOSTART_BAT = "bioreactor_autostart.bat"

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

        root.title("生物甲烷化系統 — 控制台")
        root.geometry("760x620")
        root.configure(bg=C_BG)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_ui()
        self._drain_log()
        self._poll()

        if autostart:
            self.log("以「開機自動啟動」模式啟動，正在自動拉起所有服務…", "info")
            self.root.after(800, self.start_all)

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
                 ("web", "開啟網頁", self.open_web, "#2a2a2a"),
                 ("csv", "匯入 CSV", self.import_csv, "#2a2a2a")]
        for i, (k, text, cmd, color) in enumerate(specs):
            b = tk.Button(btns, text=text, command=cmd, bg=color, fg="#e8e8e8",
                          activebackground=color, relief="flat", bd=0, padx=10, pady=8,
                          font=("Microsoft JhengHei UI", 10, "bold"), cursor="hand2")
            b.grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3)
            self.btn[k] = b
        for c in range(3):
            btns.columnconfigure(c, weight=1)

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

    def _poll_worker(self):
        health = None
        if port_open(BACKEND_PORT):
            try:
                with urllib.request.urlopen(f"{API_BASE}/health", timeout=2) as r:
                    health = json.loads(r.read().decode("utf-8"))
            except Exception:
                health = {}
        fe = port_open(PREVIEW_PORT)
        watcher = self._proc_alive("watcher")

        self.poll_count += 1
        if self.poll_count % GIT_POLL_EVERY == 1:
            self._refresh_git()
        self.root.after(0, lambda: self._render(health, fe, watcher))

    def _render(self, health, fe_up, watcher_up):
        # 後端
        if health is None:
            self._row("backend", C_BAD, "未執行")
        elif not health:
            self._row("backend", C_WARN, f"port {BACKEND_PORT} 有回應但 /health 失敗")
        else:
            self._row("backend", C_OK,
                      f"執行中 :{BACKEND_PORT} · 已運行 {health.get('uptime_min', 0)} 分 · "
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

        self._row("watcher", C_OK if watcher_up else C_IDLE,
                  "執行中" if watcher_up else "未由本控制台啟動")
        self._row("frontend", C_OK if fe_up else C_IDLE,
                  f"執行中 {PREVIEW_URL}" if fe_up else "未執行")

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

    def _start_all_worker(self):
        if not self._check_venv():
            return
        if port_open(BACKEND_PORT):
            self.log("後端已在執行中，略過啟動", "info")
        else:
            self.log("啟動後端…", "cmd")
            self._spawn("backend", [str(VENV_PY), "main.py"], BACKEND_DIR, "後端")

        data_dir = self.cfg.get("csv_dir")
        if not data_dir:
            self.log("尚未設定 CSV 監看資料夾，略過 CSV 監看（可按「匯入 CSV」選定後記住）", "warn")
        elif self._proc_alive("watcher"):
            self.log("CSV 監看已在執行中，略過", "info")
        else:
            self.log(f"啟動 CSV 監看：{data_dir}", "cmd")
            self._spawn("watcher", [str(VENV_PY), "csv_watcher.py", "--dir", data_dir],
                        BACKEND_DIR, "CSV監看")

        if port_open(PREVIEW_PORT):
            self.log("網頁前端已在執行中，略過", "info")
        else:
            npm = self._npm()
            if npm:
                self.log("啟動網頁前端…", "cmd")
                self._spawn("frontend", [npm, "run", "preview"], FRONTEND_DIR, "前端")
            else:
                self.log("找不到 npm，略過前端啟動", "warn")
        self.log("啟動程序完成。", "ok")

    def _npm(self):
        import shutil
        return shutil.which("npm") or shutil.which("npm.cmd")

    def stop_all(self):
        if not self._guard():
            return
        if not messagebox.askyesno("停止全部", "確定要停止後端、CSV 監看與前端嗎？\n"
                                               "（反應器本身不受影響，僅停止本電腦的記錄與介面）"):
            return
        self._task(self._stop_all_worker)

    def _stop_all_worker(self):
        for key, label in [("watcher", "CSV監看"), ("frontend", "前端"), ("backend", "後端")]:
            p = self.procs.get(key)
            if p and p.poll() is None:
                p.terminate()
                self.log(f"{label} 已停止", "info")
        self._kill_port(BACKEND_PORT)
        self.log("全部停止完成。", "ok")

    def restart_backend(self):
        if not self._guard():
            return
        self._task(self._restart_backend_worker)

    def _restart_backend_worker(self):
        if not self._check_venv():
            return
        self.log("重啟後端…", "cmd")
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
            self.log("已是最新版本，無需更新。", "ok")
            return
        if behind is None:
            self.log("無法確認遠端狀態（可能沒網路）。仍可手動執行更新。", "warn")

        if not messagebox.askyesno(
                "執行更新",
                f"遠端有 {behind if behind else '未知數量'} 個新 commit。\n\n"
                "更新會執行：git pull → 安裝套件 → 重建前端 → 重啟後端。\n"
                "期間記錄會短暫中斷，且後端記憶體資料會清空（需重新匯入 CSV）。\n\n"
                "確定要現在更新嗎？"):
            self.log("已取消更新。", "info")
            return

        for label, cmd, cwd in [
            ("git pull", ["git", "pull"], ROOT),
            ("安裝後端套件", [str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND_DIR),
        ]:
            self.log(f"執行 {label}…", "cmd")
            if not self._run_stream(cmd, cwd, label):
                self.log(f"{label} 失敗，中止更新。", "bad")
                return

        npm = self._npm()
        if npm:
            self.log("重建前端…", "cmd")
            self._run_stream([npm, "run", "build"], FRONTEND_DIR, "npm build")
        else:
            self.log("找不到 npm，略過前端重建。", "warn")

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
        if not port_open(PREVIEW_PORT):
            self.log("網頁前端未執行，請先按「全部啟動」。", "warn")
            return
        webbrowser.open(PREVIEW_URL)
        self.log(f"已開啟 {PREVIEW_URL}", "info")

    def import_csv(self):
        if not self._guard():
            return
        if not port_open(BACKEND_PORT):
            self.log("後端未執行，無法匯入。請先啟動後端。", "warn")
            return
        folder = filedialog.askdirectory(title="選擇 CSV 資料夾（BTP_Sensor_log-*.csv）",
                                         initialdir=self.cfg.get("csv_dir") or str(ROOT))
        if not folder:
            return
        self.cfg["csv_dir"] = folder          # 記住，之後「全部啟動」可直接拉起 CSV 監看
        save_config(self.cfg)
        self.log(f"匯入資料夾：{folder}", "cmd")
        self._task(lambda: self._run_stream(
            [str(VENV_PY), "batch_import_csv.py", "--dir", folder], BACKEND_DIR, "匯入"))

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
