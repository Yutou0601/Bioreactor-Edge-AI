
# -*- coding: utf-8 -*-
"""一鍵啟動與看板。取代 control_panel.pyw（那支是為 Jetson 拓樸建的）。

Jetson 退場後只剩一台機器、一個服務、一個埠：

    uvicorn main:app --port 8000
        /api/*   後端
        /        前端 dist/（StaticFiles）

不需要 npm、不需要 SSH、不需要 MQTT broker。

⚠ 但「把服務拉起來」不是這支程式最重要的工作。最重要的是**盯著資料有
  沒有斷**。2026-07-22 發生過一次事故：感測器記錄程式沒在跑，於是沒有
  新的 CSV，資料靜默中斷——服務一切正常、網頁也打得開，只是再也沒有新
  資料進來。所以面板上「資料新鮮度」擺在第一張卡，權重高於服務狀態。

⚠ 兩個實測踩過的坑，改動時不要退回去：
  1 不可用 stderr=PIPE 接 uvicorn。它會持續寫存取紀錄，沒人讀就把緩衝
    塞滿、行程卡死；症狀是「按了啟動，等 25 秒埠還是不通，也沒有任何
    錯誤訊息」。要導向檔案。
  2 不可 start 完就開瀏覽器。服務要幾秒才起得來，搶先開只會讓使用者
    看到連線失敗，然後以為系統壞了。要等埠真的通。
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from tkinter import filedialog, messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, 'edge_backend')
CONFIG = os.path.join(ROOT, 'launcher.json')
LOGFILE = os.path.join(BACKEND, 'server.log')
PORT = 8000
URL = 'http://localhost:%d' % PORT

# 感測器記錄程式：把序列埠資料寫成 CSV。它沒在跑就沒有新資料。
DEFAULT_RECORDER = r'C:\Users\BTP\Desktop\data\BTP.SerialHarbor1.1.exe'
DEFAULT_CSV_DIR = r'C:\Users\BTP\Desktop\data'
STALE_MIN = 15                      # 超過幾分鐘沒有新資料就示警

AUTOSTART_BAT = 'BTP_monitor.bat'
REQUIRED = ('fastapi', 'uvicorn', 'numpy', 'pydantic')

C_BG, C_CARD, C_FG, C_DIM = '#141414', '#1c1c1c', '#e6e6e6', '#8a8a8a'
C_OK, C_BAD, C_WARN = '#3fa96a', '#c0504d', '#c9a227'
FONT = 'Microsoft JhengHei UI'


CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# 開發機才有 .git 與前端原始碼；現場只有解壓出來的程式。
# 用這個決定要不要顯示「開發」那一排按鈕。
IS_DEV = (os.path.isdir(os.path.join(ROOT, '.git'))
          and os.path.isfile(os.path.join(ROOT, 'web_frontend', 'package.json')))


def version_label():
    """顯示目前跑的是哪一版。

    ⚠ 這很重要：現場回報問題時，第一個要問的就是「你那台是哪一版」。
      沒有這行就得請人去翻資料夾。
      pack 安裝的機器有 VERSION.txt；git 安裝的機器用 git describe。
    """
    vf = os.path.join(ROOT, 'VERSION.txt')
    if os.path.isfile(vf):
        try:
            with open(vf, encoding='utf-8', errors='replace') as fh:
                first = fh.readline().strip()
            if first:
                return '· ' + first
        except OSError:
            pass
    try:
        out = subprocess.run(['git', 'describe', '--tags', '--always'],
                             cwd=ROOT, capture_output=True, timeout=4,
                             creationflags=CREATE_NO_WINDOW)
        tag = out.stdout.decode('utf-8', 'replace').strip()
        if tag:
            return '· ' + tag
    except (OSError, subprocess.SubprocessError):
        pass
    return ''


def env_csv_dir():
    """後端實際會讀的資料夾——從 edge_backend/.env 讀，與後端同一個來源。

    ⚠ 面板以前用自己的 launcher.json 存 csv_dir，後端用 .env 的
      REACTOR_DATA_DIR。兩邊可以指到不同資料夾，而且沒有任何地方會發現——
      面板顯示「資料正常」而後端讀的是空資料夾。這正是 selfcheck 要防的
      那類錯誤，所以面板改成讀同一份設定。
    """
    path = os.path.join(BACKEND, '.env')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if line.startswith('REACTOR_DATA_DIR') and '=' in line:
                    return line.partition('=')[2].strip().strip('"\'') or None
    except OSError:
        pass
    return None


def load_cfg():
    try:
        with open(CONFIG, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_cfg(cfg):
    try:
        with open(CONFIG, 'w', encoding='utf-8') as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def find_python(windowless=False):
    """優先用專案 venv——系統 python 未必裝了 fastapi。"""
    name = 'pythonw.exe' if windowless else 'python.exe'
    for c in (os.path.join(BACKEND, 'venv', 'Scripts', name),
              os.path.join(BACKEND, 'venv', 'bin', 'python')):
        if os.path.exists(c):
            return c
    return sys.executable


def port_open(port, host='127.0.0.1', timeout=0.4):
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def api(path, method='GET', timeout=6):
    req = urllib.request.Request(URL + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def newest_csv_age_min(folder):
    """資料夾裡最新 CSV 距今幾分鐘。找不到回 None。

    ⚠ 直接看檔案時間，不透過後端。記錄程式與後端是兩條獨立的鏈，
      後端活著不代表有新資料進來——2026-07-22 的事故正是如此。
    """
    if not folder or not os.path.isdir(folder):
        return None
    newest = None
    try:
        for f in os.listdir(folder):
            if not f.lower().endswith('.csv'):
                continue
            m = os.path.getmtime(os.path.join(folder, f))
            if newest is None or m > newest:
                newest = m
    except OSError:
        return None
    if newest is None:
        return None
    return (time.time() - newest) / 60.0


def process_running(exe_name):
    """用 tasklist 查行程。比記 PID 可靠——使用者可能自己開過那支程式。"""
    if sys.platform != 'win32' or not exe_name:
        return None
    try:
        out = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq ' + exe_name, '/NH'],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return exe_name.lower() in (out.stdout or '').lower()
    except Exception:                             # noqa: BLE001
        return None


def startup_dir():
    return os.path.join(os.environ.get('APPDATA', ''), 'Microsoft',
                        'Windows', 'Start Menu', 'Programs', 'Startup')


class Launcher:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self.cfg = load_cfg()

        root.title('生物反應器監測系統')
        root.configure(bg=C_BG)
        # 多了維護／開發兩排按鈕，視窗要跟著長高，否則下方記錄區被擠掉。
        # 開發機多一排，所以高度看 IS_DEV。
        root.geometry('540x%d' % (700 if IS_DEV else 660))
        root.minsize(500, 600)

        tk.Label(root, text='生物反應器監測系統', bg=C_BG, fg=C_FG,
                 font=(FONT, 15, 'bold')).pack(pady=(16, 1))
        tk.Label(root, text='前後端同機 · 一個服務 · 埠 %d　%s'
                 % (PORT, version_label()),
                 bg=C_BG, fg=C_DIM, font=(FONT, 9)).pack()

        # ── 三張狀態卡：資料新鮮度擺第一 ──────────────────
        cards = tk.Frame(root, bg=C_BG)
        cards.pack(fill='x', padx=18, pady=(14, 6))
        self.card = {}
        for i, (key, title) in enumerate((('data', '資料新鮮度'),
                                          ('rec', '記錄程式'),
                                          ('svc', '後端服務'))):
            f = tk.Frame(cards, bg=C_CARD)
            f.grid(row=0, column=i, sticky='ew', padx=3)
            cards.columnconfigure(i, weight=1)
            tk.Label(f, text=title, bg=C_CARD, fg=C_DIM,
                     font=(FONT, 8)).pack(pady=(8, 0))
            v = tk.Label(f, text='—', bg=C_CARD, fg=C_DIM,
                         font=(FONT, 11, 'bold'))
            v.pack(pady=(1, 8))
            self.card[key] = v

        self.info = tk.Label(root, text='', bg=C_BG, fg=C_DIM,
                             font=(FONT, 9), wraplength=470, justify='left')
        self.info.pack(padx=18, pady=(2, 4))

        self.big = tk.Button(root, text='啟 動', command=self.toggle,
                             bg='#1d6b45', fg='#f0f0f0', relief='flat', bd=0,
                             activebackground='#1d6b45', cursor='hand2',
                             font=(FONT, 13, 'bold'))
        self.big.pack(fill='x', padx=24, pady=(8, 6), ipady=10)

        # ── 按鈕分三排，依「誰會按」分：日常／維護／開發 ────────
        # 研究員每天只碰第一排。第三排只在開發機（有 .git 與 npm）出現，
        # 免得現場有人按到「打包」然後等五分鐘不知道在幹嘛。
        self._btn_row('日常', (('開啟網頁', self.open_web),
                               ('匯入 CSV 資料夾', self.import_csv),
                               ('設定路徑', self.configure_paths)))
        self._btn_row('維護', (('自我檢查', self.do_selfcheck),
                               ('更新', self.do_update),
                               ('記錄檔', self.open_log)))
        if IS_DEV:
            self._btn_row('開發', (('系統測試', self.do_systest),
                                   ('建置前端', self.do_build),
                                   ('打包', self.do_pack)))

        opt = tk.Frame(root, bg=C_BG)
        opt.pack(fill='x', padx=24, pady=(8, 0))
        self.auto = tk.BooleanVar(value=self.autostart_on())
        tk.Checkbutton(opt, text='開機自動啟動', variable=self.auto,
                       command=self.toggle_autostart, bg=C_BG, fg=C_DIM,
                       selectcolor=C_CARD, activebackground=C_BG,
                       activeforeground=C_FG, relief='flat', bd=0,
                       font=(FONT, 9)).pack(anchor='w')

        self.log = tk.Text(root, height=10, bg='#0e0e0e', fg='#9a9a9a',
                           relief='flat', bd=0, wrap='word',
                           font=('Consolas', 8))
        self.log.pack(fill='both', expand=True, padx=20, pady=(10, 14))
        self.log.configure(state='disabled')

        self.check_deps()
        self.tick()
        root.protocol('WM_DELETE_WINDOW', self.on_close)

    def _btn_row(self, label, items):
        """一排按鈕，左邊掛一個分類標籤。"""
        row = tk.Frame(self.root, bg=C_BG)
        row.pack(fill='x', padx=24, pady=(4, 0))
        tk.Label(row, text=label, bg=C_BG, fg='#5a5a5a',
                 font=(FONT, 8), width=4, anchor='w').pack(side='left')
        for text, cmd in items:
            tk.Button(row, text=text, command=cmd, bg='#242424', fg=C_FG,
                      relief='flat', bd=0, activebackground='#2e2e2e',
                      cursor='hand2', font=(FONT, 9)
                      ).pack(side='left', expand=True, fill='x', padx=3,
                             ipady=6)

    # ── 外部工作（自我檢查／更新／測試／打包）─────────────────
    def run_task(self, title, argv, cwd=None, after=None):
        """在背景執行緒跑一支指令，輸出即時流進下方的記錄區。

        ⚠ 一定要開執行緒。這些工作動輒數十秒到數分鐘（系統測試要跑完
          207 段估計、打包要下載 wheel），在主執行緒跑會讓整個視窗凍住，
          使用者會以為當掉然後強制關閉。

        ⚠ 這裡可以用 stdout=PIPE，與檔頭那條「不可用 PIPE 接 uvicorn」
          不衝突：差別在於**有沒有人在讀**。uvicorn 是長駐且沒人讀，緩衝
          會塞爆；這裡是短命工作而且我們持續 readline，不會塞住。
        """
        if getattr(self, '_task', None) and self._task.is_alive():
            messagebox.showinfo('請稍候', '還有一個工作在跑，等它結束。')
            return
        self.say('── %s ──' % title)

        def work():
            try:
                p = subprocess.Popen(
                    argv, cwd=cwd or ROOT, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
                for raw in iter(p.stdout.readline, b''):
                    line = raw.decode('utf-8', 'replace').rstrip()
                    if line:
                        self.root.after(0, self.say, '  ' + line)
                p.stdout.close()
                rc = p.wait()
                self.root.after(0, self.say,
                                '── %s %s ──' % (title,
                                                 '完成' if rc == 0 else
                                                 '失敗（離開碼 %d）' % rc))
                if after:
                    self.root.after(0, after, rc)
            except Exception as e:                        # noqa: BLE001
                self.root.after(0, self.say, '  ★ %s: %s' % (type(e).__name__, e))

        self._task = threading.Thread(target=work, daemon=True)
        self._task.start()

    def do_selfcheck(self):
        """裝好了沒。這是現場最常按的維護鍵。"""
        self.run_task('自我檢查',
                      [find_python(), os.path.join(BACKEND, 'selfcheck.py')])

    def do_update(self):
        """從 GitHub 更新。⚠ 要先停服務——執行中的檔案在 Windows 上鎖住。"""
        if self.proc or port_open(PORT):
            if not messagebox.askyesno(
                    '需要先停止服務',
                    '更新前要先停止後端（Windows 會鎖住執行中的檔案）。\n\n'
                    '現在停止並更新嗎？'):
                return
            self.stop()
        if not messagebox.askyesno(
                '更新', '會從 GitHub 拉取最新版本。\n\n'
                        '⚠ 需要網路。現場資料（資料庫、批次、.env）不會被動到。\n\n'
                        '繼續？'):
            return
        self.run_task('更新', ['git', 'pull', '--ff-only', 'origin', 'main'],
                      after=self._after_update)

    def _after_update(self, rc):
        if rc != 0:
            self.say('  更新失敗，維持原版本。可能是沒有網路。')
            return
        self.say('  更新完成，正在裝相依並自我檢查…')
        self.run_task('相依與檢查',
                      [find_python(), '-m', 'pip', 'install', '-q', '-r',
                       os.path.join(BACKEND, 'requirements.txt')],
                      after=lambda _rc: self.do_selfcheck())

    def open_log(self):
        """開伺服器記錄檔。出問題時第一個要看的東西。"""
        if not os.path.isfile(LOGFILE):
            messagebox.showinfo('沒有記錄檔',
                                '還沒有 server.log —— 服務從未啟動過。')
            return
        os.startfile(LOGFILE)                             # noqa: S606

    def do_systest(self):
        self.run_task('系統測試（要幾分鐘）',
                      [find_python(), 'system_test.py'], cwd=BACKEND)

    def do_build(self):
        self.run_task('建置前端',
                      ['cmd', '/c', 'npm', 'run', 'build'],
                      cwd=os.path.join(ROOT, 'web_frontend'))

    def do_pack(self):
        from tkinter import simpledialog
        v = simpledialog.askstring('打包', '版本號（例如 v1.3.0）：',
                                   parent=self.root)
        if not v:
            return
        self.run_task('打包 %s' % v, ['cmd', '/c', 'pack.bat', v])

    # ── 設定 ────────────────────────────────────────────────
    @property
    def recorder(self):
        return self.cfg.get('recorder_path', DEFAULT_RECORDER)

    @property
    def csv_dir(self):
        # 後端的 .env 優先——兩邊必須看同一個資料夾，
        # 否則面板會顯示「資料正常」而後端讀的是別的地方。
        return (env_csv_dir()
                or self.cfg.get('csv_dir', DEFAULT_CSV_DIR))

    # ── 介面 ────────────────────────────────────────────────
    def say(self, msg):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S  ') + msg + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def check_deps(self):
        py = find_python()
        code = ('import importlib.util;'
                'print(",".join(m for m in %r'
                ' if importlib.util.find_spec(m) is None))' % (REQUIRED,))
        try:
            out = subprocess.run([py, '-c', code], capture_output=True,
                                 text=True, timeout=30,
                                 creationflags=getattr(
                                     subprocess, 'CREATE_NO_WINDOW', 0))
            missing = [m for m in (out.stdout or '').strip().split(',') if m]
        except Exception:                         # noqa: BLE001
            missing = []
        if missing:
            self.say('★ 缺少套件：%s。請先 pip install。' % ', '.join(missing))
        else:
            self.say('環境檢查通過。按「啟動」把服務拉起來。')

    # ── 啟停 ────────────────────────────────────────────────
    def toggle(self):
        if port_open(PORT):
            self.stop()
        else:
            self.start()

    def start(self):
        if not os.path.isdir(BACKEND):
            messagebox.showerror('找不到後端', BACKEND)
            return
        py = find_python()
        self.say('啟動後端（%s）…' % os.path.basename(py))
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) \
            if sys.platform == 'win32' else 0
        try:
            # ⚠ 導向檔案，不可用 PIPE：uvicorn 持續寫 log，沒人讀會卡死。
            fh = open(LOGFILE, 'w', encoding='utf-8', errors='replace')
            self.proc = subprocess.Popen(
                [py, '-m', 'uvicorn', 'main:app',
                 '--host', '0.0.0.0', '--port', str(PORT)],
                cwd=BACKEND, creationflags=flags,
                stdout=fh, stderr=subprocess.STDOUT)
        except OSError as e:
            messagebox.showerror('啟動失敗', str(e))
            return
        self.start_recorder()
        threading.Thread(target=self._await_ready, daemon=True).start()

    def start_recorder(self):
        """記錄程式沒在跑＝沒有新 CSV＝資料靜默中斷（2026-07-22 事故）。"""
        exe = self.recorder
        if not os.path.exists(exe):
            self.say('⚠ 找不到記錄程式：%s（可用「設定路徑」指定）' % exe)
            return
        if process_running(os.path.basename(exe)):
            self.say('記錄程式已在執行中。')
            return
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe) or None)
            self.say('已啟動記錄程式。')
        except OSError as e:
            self.say('★ 記錄程式啟動失敗：%s' % e)

    def _await_ready(self):
        """⚠ 等埠真的通了才開瀏覽器。"""
        for _ in range(60):
            if port_open(PORT):
                self.root.after(0, self.say, '服務就緒，開啟瀏覽器。')
                self.root.after(0, self.open_web)
                return
            if self.proc and self.proc.poll() is not None:
                tail = ''
                try:
                    with open(LOGFILE, encoding='utf-8',
                              errors='replace') as fh:
                        tail = fh.read()[-500:]
                except OSError:
                    pass
                self.root.after(0, self.say, '★ 後端結束了。' + tail)
                return
            time.sleep(0.5)
        self.root.after(0, self.say,
                        '★ 等待逾時：埠 %d 一直沒通，請看 %s。'
                        % (PORT, os.path.basename(LOGFILE)))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.say('已停止後端。（記錄程式不動——停掉它資料就斷了）')
        elif port_open(PORT):
            self.say('埠 %d 的服務不是本面板啟動的，請手動關閉。' % PORT)
        self.proc = None

    # ── 動作 ────────────────────────────────────────────────
    def open_web(self):
        if not port_open(PORT):
            self.say('服務尚未啟動。')
            return
        webbrowser.open(URL + '/rate')

    def import_csv(self):
        if not port_open(PORT):
            self.say('請先啟動服務。')
            return
        folder = filedialog.askdirectory(
            title='選一個期間的資料夾（整個資料夾，不是單一檔案）',
            initialdir=self.csv_dir if os.path.isdir(self.csv_dir)
            else os.path.join(BACKEND, 'Testing_data'))
        if not folder:
            return
        # ⚠ 必須整個資料夾送出。循環中位長約 10 小時、大多跨過午夜，
        #   逐檔匯入會把跨日的一段攔腰砍斷，時長與振幅都會錯。
        self.say('匯入 %s …' % os.path.basename(folder))
        threading.Thread(target=self._do_import, args=(folder,),
                         daemon=True).start()

    def _do_import(self, folder):
        try:
            r = api('/api/ingest_folder?folder='
                    + urllib.parse.quote(folder, safe=''),
                    method='POST', timeout=900)
            self.root.after(0, self.say,
                            '完成：切出 %s 段，通過預篩 %s 段，新寫入 %s 筆。'
                            % (r.get('segments'), r.get('screened'),
                               r.get('inserted')))
        except urllib.error.HTTPError as e:
            self.root.after(0, self.say, '★ 匯入失敗 HTTP %d' % e.code)
        except Exception as e:                    # noqa: BLE001
            self.root.after(0, self.say, '★ 匯入失敗：%s' % e)

    def configure_paths(self):
        exe = filedialog.askopenfilename(
            title='選擇感測器記錄程式（.exe）',
            filetypes=[('執行檔', '*.exe'), ('全部', '*.*')])
        if exe:
            self.cfg['recorder_path'] = exe
        d = filedialog.askdirectory(title='選擇記錄程式寫出 CSV 的資料夾',
                                    initialdir=self.csv_dir)
        if d:
            self.cfg['csv_dir'] = d
        if exe or d:
            save_cfg(self.cfg)
            self.say('路徑已儲存至 launcher.json。')

    # ── 開機自動啟動 ────────────────────────────────────────
    def autostart_on(self):
        return os.path.exists(os.path.join(startup_dir(), AUTOSTART_BAT))

    def toggle_autostart(self):
        path = os.path.join(startup_dir(), AUTOSTART_BAT)
        try:
            if self.auto.get():
                pyw = find_python(windowless=True)
                # 用 .bat 而非捷徑：純文字、看得懂、要取消直接刪檔即可。
                # ⚠ 內容保持 ASCII——cmd.exe 用系統 ANSI 讀 .bat。
                with open(path, 'w', encoding='ascii', errors='replace') as f:
                    f.write('@echo off\r\ncd /d "%s"\r\nstart "" "%s" "%s"\r\n'
                            % (ROOT, pyw, os.path.abspath(__file__)))
                self.say('已設定開機自動啟動：%s' % path)
            else:
                if os.path.exists(path):
                    os.remove(path)
                self.say('已取消開機自動啟動。')
        except OSError as e:
            self.say('★ 設定失敗：%s' % e)
            self.auto.set(self.autostart_on())

    # ── 狀態輪詢 ────────────────────────────────────────────
    def tick(self):
        # 資料新鮮度擺第一：服務活著不代表有新資料進來
        age = newest_csv_age_min(self.csv_dir)
        if age is None:
            self.card['data'].configure(text='查無 CSV', fg=C_WARN)
        elif age > STALE_MIN:
            self.card['data'].configure(text='停了 %.0f 分' % age, fg=C_BAD)
        else:
            self.card['data'].configure(text='%.0f 分前' % age, fg=C_OK)

        run = process_running(os.path.basename(self.recorder))
        if run is None:
            self.card['rec'].configure(text='查不到', fg=C_DIM)
        else:
            self.card['rec'].configure(text='執行中' if run else '未執行',
                                       fg=C_OK if run else C_BAD)

        up = port_open(PORT)
        self.card['svc'].configure(text='執行中' if up else '未啟動',
                                   fg=C_OK if up else C_DIM)
        self.big.configure(text='停 止' if up else '啟 動',
                           bg='#6b2d2d' if up else '#1d6b45',
                           activebackground='#6b2d2d' if up else '#1d6b45')

        detail = ''
        if up:
            try:
                d = api('/api/rate', timeout=3)
                detail = ('循環 %d 段（通過預篩 %d）　中位 r_b %.5f'
                          % (d['n_cycles'], d['n_screened'],
                             d.get('median_rb') or 0)) \
                    if d.get('n_screened') else '尚無循環資料，請匯入 CSV。'
            except Exception:                     # noqa: BLE001
                detail = 'API 尚未回應'
        if age is not None and age > STALE_MIN:
            detail = ('⚠ 已 %.0f 分鐘沒有新資料，檢查記錄程式與感測器接線。'
                      % age) + ('　' + detail if detail else '')
        self.info.configure(
            text=detail,
            fg=C_BAD if (age is not None and age > STALE_MIN) else C_DIM)
        self.root.after(3000, self.tick)

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if messagebox.askyesno('關閉', '要一併停止後端服務嗎？'):
                self.stop()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
