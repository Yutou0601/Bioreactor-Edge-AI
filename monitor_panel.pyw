
# -*- coding: utf-8 -*-
"""監控電腦的主控台（架構 B）。

架構 B 下監控電腦不跑後端，所以這支不「啟動服務」，它只做一件事：
**看資料鏈哪一節斷了**，並給出那一節的修法。

    設備 ─COM4─▶ 記錄程式 ─▶ CSV ─▶ 上傳程式 ─USB─▶ Jetson ─▶ 網頁
                  ①           ②        ③          ④         ⑤

面板由左到右四張卡就是 ①～④，下面一行字指出**第一個**出問題的環節。
只報第一個，是因為後面的全是它的連帶結果（記錄程式停了，CSV 當然不會更新，
Jetson 當然會落後）——一次列一排紅燈，現場的人不知道先修哪個。

⚠ 2026-07-22 事故：記錄程式沒在跑，資料靜默中斷 17.5 小時，網頁一切正常只是
  沒有新資料。所以「CSV 多久沒更新」與「Jetson 落後多少」用的都是**資料本身的
  時間戳**，不是「服務活著沒」：
    · CSV：最新檔案最後一行的時間
    · Jetson：/api/ingest/status 裡本站台的 last_ts（也是從 CSV 來的時間）
  兩者相減＝落後幾分鐘，與兩台機器的時鐘準不準無關。

⚠ 只用標準函式庫＋tkinter（監控電腦 4 GB，見 core/sample_store.py 開頭）。
⚠ 網路檢查放背景執行緒：USB 拔掉時一次 HTTP 逾時要 2 秒，在主執行緒做視窗會卡。
  但背景執行緒**不可碰 tk**，連 root.after 都不行（Tk 不是執行緒安全的，實測丟
  「main thread is not in main loop」）。結果一律丟進 queue，由主執行緒的 pump() 取出來畫。
⚠ 絕不打開 COM 埠；「啟動記錄程式」只是執行廠商的 exe，由它自己開 COM4。

舊的 launcher.pyw（架構 A：整套後端跑在這台）保留作 Jetson 故障時的單機備援，
由本面板的「單機備援」按鈕叫出。
"""
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, 'edge_backend')
sys.path.insert(0, BACKEND)
from core import config                                   # noqa: E402  只用標準庫

UPLOADER = os.path.join(BACKEND, 'monitor_uploader.py')
UPLOAD_LOG = os.path.join(BACKEND, 'uploader.log')
LAUNCHER_CFG = os.path.join(ROOT, 'launcher.json')        # 與舊面板共用記錄程式路徑
DEFAULT_RECORDER = r'C:\Users\BTP\Desktop\data\BTP.SerialHarbor1.1.exe'
INSTANCE_PORT = 47811                                     # 與 monitor_uploader.py 相同
LNK_NAME = 'Bioreactor uploader.lnk'

STALE_MIN = 15            # CSV 超過幾分鐘沒更新就示警（記錄程式一分鐘寫一行）
LAG_WARN_MIN = 5          # Jetson 落後 CSV 幾分鐘示警（上傳每 20 秒一輪）
POLL_MS = 5000

C_BG, C_CARD, C_FG, C_DIM = '#141414', '#1c1c1c', '#e6e6e6', '#8a8a8a'
C_OK, C_BAD, C_WARN = '#3fa96a', '#c0504d', '#c9a227'
FONT = 'Microsoft JhengHei UI'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DETACHED = getattr(subprocess, 'DETACHED_PROCESS', 0)


# ══════════════════════════════════════════════════════════
# 狀態收集（背景執行緒呼叫；不碰任何 tk 物件）
# ══════════════════════════════════════════════════════════
def load_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def csv_status(folder):
    """最新 CSV 的（檔案修改距今分鐘, 最後一行的資料時間）。"""
    if not folder or not os.path.isdir(folder):
        return None, None
    try:
        files = sorted(f for f in os.listdir(folder)
                       if f.startswith('BTP_Sensor_log-') and f.lower().endswith('.csv'))
    except OSError:
        return None, None
    if not files:
        return None, None
    path = os.path.join(folder, files[-1])
    try:
        age = (time.time() - os.path.getmtime(path)) / 60.0
        with open(path, 'rb') as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 4096))
            tail = fh.read().decode('utf-8', 'replace')
    except OSError:
        return None, None
    last_ts = None
    for line in reversed([ln for ln in tail.splitlines() if ln.strip()]):
        p = line.lstrip('\ufeff').split(',')
        try:
            last_ts = datetime(int(p[0]), int(p[1]), int(p[2]),
                               int(p[3]), int(p[4]), int(float(p[5])))
            break
        except (ValueError, IndexError):
            continue                       # 寫到一半的末行或表頭，往前找
    return age, last_ts


def process_running(exe_name):
    if sys.platform != 'win32' or not exe_name:
        return None
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ' + exe_name, '/NH'],
                             capture_output=True, text=True, timeout=8,
                             creationflags=NO_WINDOW)
        return exe_name.lower() in (out.stdout or '').lower()
    except Exception:                                   # noqa: BLE001
        return None


def uploader_running():
    """上傳程式持有 127.0.0.1:47811 的鎖（只 bind 不 listen）。綁得上＝沒在跑。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', INSTANCE_PORT))
        return False
    except OSError:
        return True
    finally:
        s.close()


def last_log_line(path):
    try:
        with open(path, 'rb') as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 2048))
            lines = fh.read().decode('utf-8', 'replace').splitlines()
        return lines[-1] if lines else ''
    except OSError:
        return ''


def jetson_status(url, station):
    """回傳 (連得到?, 本站台 last_ts 或 None, 錯誤字串)。"""
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/api/ingest/status', timeout=2.5) as r:
            d = json.loads(r.read().decode('utf-8'))
    except Exception as e:                              # noqa: BLE001
        return False, None, '%s' % type(e).__name__
    for s in d.get('stations', []):
        if s.get('station') == station and s.get('last_ts'):
            try:
                return True, datetime.fromisoformat(s['last_ts']), ''
            except ValueError:
                pass
    return True, None, '尚未收到本站台資料'


def startup_dir():
    return os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows',
                        'Start Menu', 'Programs', 'Startup')


def find_pythonw():
    for c in (os.path.join(BACKEND, 'venv', 'Scripts', 'pythonw.exe'),
              os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')):
        if os.path.exists(c):
            return c
    return sys.executable


def find_python():
    for c in (os.path.join(BACKEND, 'venv', 'Scripts', 'python.exe'),
              os.path.join(os.path.dirname(sys.executable), 'python.exe')):
        if os.path.exists(c):
            return c
    return sys.executable


# ══════════════════════════════════════════════════════════
class Panel:
    def __init__(self, root):
        self.root = root
        cfg = config.load()
        self.data_dir = cfg.get('REACTOR_DATA_DIR')
        self.url = cfg.get('REACTOR_UPLOAD_URL') or 'http://192.168.55.1:8000'
        self.station = cfg.get('REACTOR_STATION') or 'BTP-1'
        self.recorder = load_json(LAUNCHER_CFG).get('recorder_path', DEFAULT_RECORDER)
        self.st = {}
        self.q = queue.Queue()             # 背景執行緒 → 主執行緒的唯一通道
        self._busy = False
        self._last_proc_check = 0.0

        root.title('生物反應器監測系統 · 監控電腦')
        root.configure(bg=C_BG)
        root.geometry('600x640')
        root.minsize(540, 560)

        tk.Label(root, text='生物反應器監測系統', bg=C_BG, fg=C_FG,
                 font=(FONT, 15, 'bold')).pack(pady=(16, 1))
        tk.Label(root, text='監控電腦 · 資料送往 %s · 站台 %s' % (self.url, self.station),
                 bg=C_BG, fg=C_DIM, font=(FONT, 9)).pack()

        # ── 四張卡＝資料鏈的四節，由左到右照資料流動的順序 ──────
        cards = tk.Frame(root, bg=C_BG)
        cards.pack(fill='x', padx=16, pady=(14, 4))
        self.card, self.sub = {}, {}
        for i, (key, title) in enumerate((('rec', '① 記錄程式'), ('csv', '② CSV 資料'),
                                          ('up', '③ 上傳程式'), ('jet', '④ Jetson'))):
            f = tk.Frame(cards, bg=C_CARD)
            f.grid(row=0, column=i, sticky='ew', padx=3)
            cards.columnconfigure(i, weight=1)
            tk.Label(f, text=title, bg=C_CARD, fg=C_DIM, font=(FONT, 8)).pack(pady=(8, 0))
            v = tk.Label(f, text='—', bg=C_CARD, fg=C_DIM, font=(FONT, 11, 'bold'))
            v.pack()
            s = tk.Label(f, text='', bg=C_CARD, fg=C_DIM, font=(FONT, 8))
            s.pack(pady=(0, 8))
            self.card[key], self.sub[key] = v, s

        self.diag = tk.Label(root, text='檢查中…', bg=C_BG, fg=C_DIM, font=(FONT, 10),
                             wraplength=540, justify='left')
        self.diag.pack(padx=18, pady=(8, 4), anchor='w')

        tk.Button(root, text='開啟監控網頁', command=self.open_web, bg='#1d6b45', fg='#f0f0f0',
                  relief='flat', bd=0, activebackground='#1d6b45', cursor='hand2',
                  font=(FONT, 13, 'bold')).pack(fill='x', padx=24, pady=(8, 6), ipady=9)

        self.btn_up = None
        self._row('日常', (('啟動記錄程式', self.start_recorder),
                           ('啟動上傳', self.toggle_uploader),
                           ('對帳', self.reconcile)))
        self._row('維護', (('上傳紀錄', self.open_log),
                           ('編輯設定', self.edit_env),
                           ('記錄程式路徑', self.pick_recorder)))
        self._row('備援', (('單機備援模式（Jetson 故障時）', self.fallback),))

        opt = tk.Frame(root, bg=C_BG)
        opt.pack(fill='x', padx=24, pady=(8, 0))
        self.auto = tk.BooleanVar(value=self.autostart_on())
        tk.Checkbutton(opt, text='開機自動上傳（登入後在背景執行，不開視窗）', variable=self.auto,
                       command=self.toggle_autostart, bg=C_BG, fg=C_DIM, selectcolor=C_CARD,
                       activebackground=C_BG, activeforeground=C_FG, relief='flat', bd=0,
                       font=(FONT, 9)).pack(anchor='w')

        self.log = tk.Text(root, height=9, bg='#0e0e0e', fg='#9a9a9a', relief='flat', bd=0,
                           wrap='word', font=('Consolas', 8))
        self.log.pack(fill='both', expand=True, padx=20, pady=(10, 14))
        self.log.configure(state='disabled')

        self.say('資料夾：%s' % self.data_dir)
        self.pump()
        self.poll()

    def _row(self, label, items):
        row = tk.Frame(self.root, bg=C_BG)
        row.pack(fill='x', padx=24, pady=(4, 0))
        tk.Label(row, text=label, bg=C_BG, fg='#5a5a5a', font=(FONT, 8), width=4,
                 anchor='w').pack(side='left')
        for text, cmd in items:
            b = tk.Button(row, text=text, command=cmd, bg='#242424', fg=C_FG, relief='flat',
                          bd=0, activebackground='#2e2e2e', cursor='hand2', font=(FONT, 9))
            b.pack(side='left', expand=True, fill='x', padx=3, ipady=6)
            if cmd == self.toggle_uploader:
                self.btn_up = b

    def say(self, msg):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S  ') + msg + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    # ── 輪詢：背景收集、主執行緒畫 ────────────────────────────
    def pump(self):
        """主執行緒：把背景執行緒丟進 queue 的東西取出來畫。"""
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == 'state':
                    self.st = val
                    self._busy = False
                    self.render()
                else:
                    self.say(val)
        except queue.Empty:
            pass
        self.root.after(200, self.pump)

    def poll(self):
        if not self._busy:
            self._busy = True
            threading.Thread(target=self._collect, daemon=True).start()
        self.root.after(POLL_MS, self.poll)

    def _collect(self):
        st = dict(self.st)
        try:
            # tasklist 要開一個行程，15 秒查一次就好
            if time.time() - self._last_proc_check > 15 or 'rec' not in st:
                st['rec'] = process_running(os.path.basename(self.recorder))
                self._last_proc_check = time.time()
            st['csv_age'], st['csv_ts'] = csv_status(self.data_dir)
            st['up'] = uploader_running()
            st['up_last'] = last_log_line(UPLOAD_LOG)
            st['jet_ok'], st['jet_ts'], st['jet_err'] = jetson_status(self.url, self.station)
        finally:
            self.q.put(('state', st))

    def render(self):
        st = self.st
        # ① 記錄程式
        rec = st.get('rec')
        if rec is None:
            self._set('rec', '查不到', C_DIM, os.path.basename(self.recorder))
        else:
            self._set('rec', '執行中' if rec else '未執行', C_OK if rec else C_BAD, '')
        # ② CSV
        age, cts = st.get('csv_age'), st.get('csv_ts')
        if age is None:
            self._set('csv', '查無 CSV', C_BAD, '檢查資料夾設定')
        else:
            self._set('csv', '%.0f 分前' % age if age < 120 else '%.1f 小時前' % (age / 60),
                      C_BAD if age > STALE_MIN else C_OK,
                      cts.strftime('%m-%d %H:%M') if cts else '')
        # ③ 上傳程式
        up = st.get('up')
        self._set('up', '執行中' if up else '未執行', C_OK if up else C_WARN, '')
        if self.btn_up is not None:
            self.btn_up.configure(text='停止上傳' if up else '啟動上傳')
        # ④ Jetson
        jok, jts = st.get('jet_ok'), st.get('jet_ts')
        lag = (cts - jts).total_seconds() / 60.0 if (cts and jts) else None
        if not jok:
            self._set('jet', '連不到', C_WARN, st.get('jet_err', ''))
        elif lag is None:
            self._set('jet', '已連線', C_WARN, st.get('jet_err') or '尚無資料')
        else:
            self._set('jet', '已同步' if lag <= LAG_WARN_MIN else '落後 %.0f 分' % lag,
                      C_OK if lag <= LAG_WARN_MIN else C_WARN,
                      jts.strftime('%m-%d %H:%M'))

        # 只指出第一個斷掉的環節：後面的都是它的連帶結果
        if rec is False:
            msg, col = ('① 記錄程式沒有在執行 → 按「啟動記錄程式」。沒有它就沒有新資料'
                        '（2026-07-22 就是這樣靜默斷了 17.5 小時）。', C_BAD)
        elif age is None:
            msg, col = ('② 找不到 CSV → 按「編輯設定」確認 REACTOR_DATA_DIR 是記錄程式寫檔的資料夾。', C_BAD)
        elif age > STALE_MIN:
            msg, col = ('② CSV 已 %.0f 分鐘沒有更新，記錄程式卻在跑 → 檢查感測器電源與接線、'
                        '記錄程式畫面是否有錯誤。' % age, C_BAD)
        elif not up:
            msg, col = ('③ 上傳程式沒有在執行 → 按「啟動上傳」。資料都還在 CSV 裡，啟動後會自動補送。', C_WARN)
        elif not jok:
            msg, col = ('④ 連不到 Jetson → 檢查 USB-C 線與 Jetson 電源（開機約需 2 分鐘）。'
                        '資料不會掉，恢復連線後自動補送。', C_WARN)
        elif lag is None:
            msg, col = ('④ Jetson 還沒收到本站台的資料。若持續超過一分鐘，按「上傳紀錄」看原因。', C_WARN)
        elif lag > LAG_WARN_MIN:
            msg, col = ('④ Jetson 落後 CSV %.0f 分鐘：可能正在補送，或上傳出錯 → 按「上傳紀錄」。' % lag, C_WARN)
        else:
            msg, col = ('一切正常：最新資料 %s，Jetson 已同步。' % cts.strftime('%H:%M'), C_OK)
        self.diag.configure(text=msg, fg=col)

    def _set(self, key, text, color, sub):
        self.card[key].configure(text=text, fg=color)
        self.sub[key].configure(text=sub)

    # ── 動作 ────────────────────────────────────────────────
    def open_web(self):
        webbrowser.open(self.url.rstrip('/') + '/')

    def start_recorder(self):
        exe = self.recorder
        if not os.path.exists(exe):
            self.say('找不到記錄程式：%s → 按「記錄程式路徑」指定' % exe)
            return
        if process_running(os.path.basename(exe)):
            self.say('記錄程式已在執行中。')
            return
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe) or None)
            self.say('已啟動記錄程式。')
            self._last_proc_check = 0
        except OSError as e:
            self.say('★ 記錄程式啟動失敗：%s' % e)

    def toggle_uploader(self):
        if uploader_running():
            if not messagebox.askyesno('停止上傳',
                                       '停止後 Jetson 不會再收到新資料（CSV 照常記錄，'
                                       '重新啟動後會補送）。\n\n確定停止？'):
                return
            self._stop_uploader()
        else:
            subprocess.Popen([find_pythonw(), UPLOADER], cwd=BACKEND,
                             creationflags=DETACHED | NO_WINDOW, close_fds=True)
            self.say('已啟動上傳程式（背景執行，紀錄寫在 uploader.log）。')

    def _stop_uploader(self):
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
              "'*monitor_uploader.py*' -and $_.CommandLine -notlike '*--check*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }")
        try:
            out = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=NO_WINDOW)
            pids = (out.stdout or '').split()
            self.say('已停止上傳程式（%s）。' % (', '.join(pids) or '沒有找到行程'))
        except Exception as e:                          # noqa: BLE001
            self.say('★ 停止失敗：%s' % e)

    def reconcile(self):
        """對帳：本機每天行數 vs Jetson 筆數。輸出串進下方紀錄區。"""
        self.say('── 對帳（本機 CSV 行數 vs Jetson 筆數）──')

        def work():
            try:
                p = subprocess.Popen([find_python(), UPLOADER, '--check'], cwd=BACKEND,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=NO_WINDOW,
                                     env=dict(os.environ, PYTHONIOENCODING='utf-8'))
                lines = [ln.decode('utf-8', 'replace').rstrip() for ln in p.stdout]
                p.wait()
                bad = [ln for ln in lines if ln.startswith('✘')]
                show = bad[-15:] if bad else lines[-3:]
                for ln in show + ([lines[-1]] if bad and lines else []):
                    self.q.put(('say', '  ' + ln))
                if bad:
                    self.q.put(('say', '  （今天那一天不符是正常的：還在寫）'))
            except Exception as e:                      # noqa: BLE001
                self.q.put(('say', '  ★ 對帳失敗：%s' % e))

        threading.Thread(target=work, daemon=True).start()

    def open_log(self):
        if os.path.isfile(UPLOAD_LOG):
            os.startfile(UPLOAD_LOG)                    # noqa: S606
        else:
            self.say('還沒有 uploader.log：上傳程式從未在背景執行過。')

    def edit_env(self):
        path = os.path.join(BACKEND, '.env')
        if not os.path.isfile(path):
            self.say('沒有 edge_backend\\.env：請先執行 deploy\\monitor_uploader_setup.bat')
            return
        messagebox.showinfo('編輯設定',
                            '改完存檔後，要「停止上傳」再「啟動上傳」才會生效，'
                            '並重新開啟本面板。\n\n通行碼（REACTOR_INGEST_TOKEN）不要外流。')
        subprocess.Popen(['notepad.exe', path])

    def pick_recorder(self):
        exe = filedialog.askopenfilename(title='選擇感測器記錄程式（.exe）',
                                         filetypes=[('執行檔', '*.exe'), ('全部', '*.*')])
        if not exe:
            return
        cfg = load_json(LAUNCHER_CFG)
        cfg['recorder_path'] = exe
        try:
            with open(LAUNCHER_CFG, 'w', encoding='utf-8') as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=2)
        except OSError as e:
            self.say('★ 存檔失敗：%s' % e)
            return
        self.recorder = exe
        self._last_proc_check = 0
        self.say('記錄程式路徑已更新：%s' % exe)

    def fallback(self):
        """Jetson 故障時：開舊面板（架構 A），在這台跑整套後端。"""
        old = os.path.join(ROOT, 'launcher.pyw')
        if not os.path.isfile(old):
            self.say('找不到 launcher.pyw，無法切換單機模式。')
            return
        if not messagebox.askyesno(
                '單機備援模式',
                '只在 Jetson 故障、短期內修不好時使用。\n\n'
                '會開啟舊的控制台，在這台電腦上跑整套後端（約多用 60～350 MB 記憶體），'
                '網頁改看 http://127.0.0.1:8000。\n\n'
                '上傳程式不必停：Jetson 恢復後它會自動補送。\n\n繼續？'):
            return
        subprocess.Popen([find_pythonw(), old], cwd=ROOT)
        self.say('已開啟單機備援控制台（launcher.pyw）。')

    # ── 開機自動上傳（與 setup.bat 建的是同一個捷徑）────────────
    def autostart_on(self):
        d = startup_dir()
        return any(os.path.exists(os.path.join(d, n))
                   for n in (LNK_NAME, 'Bioreactor uploader.cmd'))

    def toggle_autostart(self):
        d = startup_dir()
        lnk = os.path.join(d, LNK_NAME)
        try:
            if self.auto.get():
                subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                os.path.join(ROOT, 'deploy', 'make_shortcut.ps1'),
                                '-Lnk', lnk, '-Target', find_pythonw(), '-Script', UPLOADER,
                                '-WorkDir', BACKEND],
                               capture_output=True, timeout=30, creationflags=NO_WINDOW)
                if not os.path.exists(lnk):
                    raise OSError('捷徑沒有建立成功')
                self.say('已設定開機自動上傳：%s' % lnk)
            else:
                for n in (LNK_NAME, 'Bioreactor uploader.cmd'):
                    p = os.path.join(d, n)
                    if os.path.exists(p):
                        os.remove(p)
                self.say('已取消開機自動上傳（目前在跑的這一份不受影響）。')
        except Exception as e:                          # noqa: BLE001
            self.say('★ 設定失敗：%s' % e)
            self.auto.set(self.autostart_on())


if __name__ == '__main__':
    root = tk.Tk()
    Panel(root)
    root.mainloop()
