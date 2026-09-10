
# -*- coding: utf-8 -*-
"""分析模組的探索、執行與結果讀取。

⚠ 這支是常駐核心的一部分，只用標準函式庫。**它從不 import 任何模組的
  程式碼**——只用 subprocess 把模組當成獨立的短命行程啟動。

  這條紅線是整個記憶體隔離的全部所在。一旦有人為了方便在這裡寫
  `from modules.covariate import analysis`，pandas 與 scipy 就永久進了
  常駐行程，60 MB 的預算當場作廢，而且不會有任何錯誤訊息。
  實際發生過：main.py 的 lifespan 無條件載入 torch，260 MB 藏了好幾個月
  （見 system_test 第 1 項）。

為什麼是子行程而不是執行緒或延遲 import：
  · 延遲 import 只是推遲付款。模組一被呼叫過，套件就永遠留在行程裡——
    Python 不會卸載已載入的模組。之後每一分鐘的常駐成本都包含它。
  · 子行程結束時作業系統把記憶體整個收回。峰值因此變成**排程問題**
    （一次只跑一個），不是架構問題。4 GB 的機器容得下一個暫時佔
    200 MB 的行程；容不下的是永遠常駐的 200 MB。

模組契約（見 docs/系統重構架構_2026-08-31.md §4）：

    modules/<name>/
      module.json     宣告：版本、標題、觸發、逾時、相依、輸入
      run.py          `python run.py <db_path> [input.json]`
                      讀輸入、算、寫回自己的 mod_* 表、結束

  run.py 不得長駐、不得 import 核心、不得寫別的模組的表。

⚠ 與架構文件的一處差異，以及為什麼：
  文件寫的是「run.py 收到一個參數：SQLite 路徑」。實作上多了第二個參數。

  原因是 experiment_store.compute_cycles() 讀的是 core.data_store 裡的
  **記憶體** sensor_records，而不是資料庫——文件 §6 規劃的 `sample` 表
  目前還不存在（DB 裡只有 cycle）。子行程另起一個 Python，看到的是空的
  記憶體，算出來會是「0 個循環」然後照常回報結論。

  兩條路：先把 sample 表做出來（文件 §10 第 6 步的正解，但要動到現行的
  匯入流程），或由核心把模組宣告要的輸入快照成 JSON 傳進去。這裡選後者，
  因為它不動資料流、可以立刻驗證整套模組框架，而且 sample 表做好之後，
  模組只要把 `input` 欄位拿掉改讀資料表即可，run.py 其餘不動。

  ⚠ 快照是**核心決定內容**的：模組只能在 module.json 的 `input` 欄位
    指名一個核心已知的提供者（見 _INPUT_PROVIDERS）。核心仍然從不
    import 模組的任何程式碼。
"""
import json
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # edge_backend/
MODULES_DIR = os.path.join(HERE, 'modules')

SCHEMA = """
CREATE TABLE IF NOT EXISTS module_run (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  name      TEXT,
  version   TEXT,
  started   TEXT,
  finished  TEXT,
  exit_code INTEGER,
  log       TEXT
);
CREATE INDEX IF NOT EXISTS ix_module_run_name ON module_run(name, started);
"""

# 一次只跑一個模組。峰值記憶體是排程問題——兩個各佔 200 MB 的模組同時跑，
# 就等於把常駐行程省下來的全部還回去。
_run_lock = threading.Lock()
_thread = None
_stop_evt = threading.Event()
_last_run_at = {}           # name -> datetime，供 every_minutes 判定
POLL_SECONDS = 30

# ⚠ 啟動後先等一下再跑第一輪。少了這段延遲，後端一啟動就會立刻噴出子行程：
#   從未跑過的模組 _last_run_at 是空的，due() 判定全部到期。實測後果是
#   POST /api/modules/<name>/run 在開機後的頭幾秒一律回 409（鎖被排程器
#   佔著），而現場的人只會看到「按了沒反應」。
#   也讓伺服器先把埠開起來——開機瞬間跟一個吃 200 MB 的子行程搶資源，
#   在 4 GB 的機器上不是好主意。
START_DELAY_SECONDS = 60

# module.json 必填欄位。缺一個就整包不載入——寧可少一個模組，也不要一個
# 半殘的模組在排程裡以未定義的行為反覆失敗。
REQUIRED = ('name', 'version', 'title', 'entry')


def _db_path():
    """與 cycle_store 用同一個資料庫。

    ⚠ 刻意不 import cycle_store 來拿這個路徑：那支模組層級 import numpy，
      而本模組要能在最精簡的情境下（例如只是列出模組清單）使用。
    """
    return os.environ.get('REACTOR_DB') or os.path.join(HERE, 'reactor.db')


def connect(path=None):
    con = sqlite3.connect(path or _db_path())
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def discover():
    """掃 modules/ 底下所有 module.json。壞掉的個別跳過並記下原因。

    回傳 list[dict]：module.json 的內容，加上 `dir` 與 `ok`／`error`。
    ⚠ 壞掉的模組要**留在清單裡**並帶 error，不是靜默略過。介面上看得到
      「這個模組壞了」，才不會有人以為它在跑。
    """
    out = []
    if not os.path.isdir(MODULES_DIR):
        return out
    for name in sorted(os.listdir(MODULES_DIR)):
        d = os.path.join(MODULES_DIR, name)
        cfg = os.path.join(d, 'module.json')
        if not os.path.isfile(cfg):
            continue
        try:
            with open(cfg, encoding='utf-8') as fh:
                m = json.load(fh)
        except (OSError, ValueError) as e:
            out.append({'name': name, 'dir': d, 'ok': False,
                        'error': 'module.json 讀取失敗：%s' % e})
            continue
        missing = [k for k in REQUIRED if not m.get(k)]
        if missing:
            out.append({'name': m.get('name') or name, 'dir': d, 'ok': False,
                        'error': 'module.json 缺欄位：%s' % ', '.join(missing)})
            continue
        if not os.path.isfile(os.path.join(d, m['entry'])):
            out.append({'name': m['name'], 'dir': d, 'ok': False,
                        'error': '找不到 entry：%s' % m['entry']})
            continue
        m['dir'] = d
        m['ok'] = True
        m.setdefault('timeout_s', 300)
        m.setdefault('writes', 'mod_' + m['name'])
        m.setdefault('trigger', {})
        out.append(m)
    return out


def get(name):
    for m in discover():
        if m.get('name') == name:
            return m
    return None


# ── 輸入提供者 ────────────────────────────────────────────────────────
# 模組在 module.json 用 `"input": "<key>"` 指名要哪一份快照。只有這裡列出
# 的鍵是合法的——核心決定能給什麼，模組不能要求任意程式碼被執行。
#
# ⚠ 每個提供者都要**延遲 import**。experiment_store 目前是純標準庫，但這裡
#   是常駐核心，模組層級 import 的東西日後被人加重了也不會有人察覺。
def _provide_all_cycles():
    from core import experiment_store as exp
    return [r for r in exp.all_cycles() if r.get('complete')]


def _provide_cycle_trajectories():
    from core import experiment_store as exp
    return exp.complete_cycle_trajectories()


_INPUT_PROVIDERS = {
    # 每列一個完整循環的特徵（drop_rate、pre_injection_orp、n_minutes…）
    'complete_cycles': _provide_all_cycles,
    # 每個完整循環的壓力軌跡，供灰箱擬合
    'cycle_trajectories': _provide_cycle_trajectories,
}


def _write_input(m):
    """把模組宣告的輸入寫成暫存 JSON，回傳路徑；沒宣告就回 None。

    ⚠ 用 json.dump 前先讓 datetime 之類的物件轉成字串。提供者回傳的內容
      來自記憶體結構，混進不可序列化的值時要當場失敗，不要寫出半個檔案
      讓模組讀到截斷的 JSON。
    """
    key = m.get('input')
    if not key:
        return None
    fn = _INPUT_PROVIDERS.get(key)
    if fn is None:
        raise ValueError('module.json 的 input 不是核心認得的鍵：%r（可用：%s）'
                         % (key, ', '.join(sorted(_INPUT_PROVIDERS))))
    data = fn()
    path = os.path.join(m['dir'], '_input.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, default=str)
    os.replace(tmp, path)          # 原子替換：模組不會讀到寫到一半的檔
    return path


def run_module(name, con=None):
    """把一個模組當子行程跑完，並把結果記進 module_run。

    ⚠ 不論成功或失敗都要留下一筆紀錄。「模組靜默地什麼都沒做」比「模組
      報錯」更難查——沒有紀錄的話，介面上只會看到結果一直是舊的。
    """
    m = get(name)
    if m is None:
        return {'ok': False, 'error': '沒有這個模組：%s' % name}
    if not m.get('ok'):
        return {'ok': False, 'error': m.get('error')}

    if not _run_lock.acquire(blocking=False):
        return {'ok': False, 'error': '已有另一個模組在跑（一次只跑一個）'}

    started = datetime.now()
    timeout = float(m.get('timeout_s') or 300)
    try:
        argv = [sys.executable, m['entry'], _db_path()]
        inp = _write_input(m)                    # 沒宣告 input 就回 None
        if inp:
            argv.append(inp)
        # ⚠ 用 sys.executable 而不是 'python'：監控電腦上服務可能跑在 venv
        #   裡，而 PATH 上的 python 是另一套，模組宣告的相依會對不上。
        proc = subprocess.run(
            argv, cwd=m['dir'], timeout=timeout,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
        )
        code, log = proc.returncode, (proc.stdout or '') + (proc.stderr or '')
    except subprocess.TimeoutExpired:
        code, log = -1, '逾時：超過 %.0f 秒仍未結束，已強制終止' % timeout
    except Exception as e:                       # 準備輸入失敗、找不到直譯器等
        code, log = -2, '%s: %s' % (type(e).__name__, e)
    finally:
        _run_lock.release()

    finished = datetime.now()
    _last_run_at[name] = finished

    own = con is None
    con = con or connect()
    try:
        con.execute(
            'INSERT INTO module_run (name, version, started, finished,'
            ' exit_code, log) VALUES (?,?,?,?,?,?)',
            (name, m.get('version'), started.isoformat(sep=' '),
             finished.isoformat(sep=' '), code, log[-4000:]))
        con.commit()
    finally:
        if own:
            con.close()

    return {'ok': code == 0, 'exit_code': code,
            'seconds': round((finished - started).total_seconds(), 1),
            'log': log[-4000:]}


def last_result(name, con=None):
    """讀模組自己那張 mod_* 表最新的一筆。

    ⚠ 表不存在是**正常狀態**（模組還沒跑過），不是錯誤。回 'never_run'
      讓介面說得出「還沒跑過」，而不是丟一個 SQL 例外上去。
    """
    m = get(name)
    if m is None:
        return {'status': 'unknown_module'}
    table = m.get('writes') or ('mod_' + name)
    own = con is None
    con = con or connect()
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        if not exists:
            return {'status': 'never_run', 'table': table}
        row = con.execute(
            'SELECT * FROM "%s" ORDER BY id DESC LIMIT 1' % table).fetchone()
        if row is None:
            return {'status': 'empty', 'table': table}
        d = dict(row)
        # payload 慣例上是 JSON 字串。解得開就解，解不開就原樣回傳——
        # 模組可以自訂欄位，介面不該因為某個模組沒照慣例就整頁壞掉。
        if isinstance(d.get('payload'), str):
            try:
                d['payload'] = json.loads(d['payload'])
            except ValueError:
                pass
        return {'status': 'ok', 'table': table, 'result': d}
    finally:
        if own:
            con.close()


def history(name=None, limit=20, con=None):
    """最近的執行紀錄。介面用它回答「上次跑成功了嗎、花多久」。"""
    own = con is None
    con = con or connect()
    try:
        if name:
            rows = con.execute(
                'SELECT * FROM module_run WHERE name = ?'
                ' ORDER BY id DESC LIMIT ?', (name, int(limit)))
        else:
            rows = con.execute(
                'SELECT * FROM module_run ORDER BY id DESC LIMIT ?',
                (int(limit),))
        return [dict(r) for r in rows]
    finally:
        if own:
            con.close()


def due(now=None):
    """此刻該跑哪些模組。相依的狀態只有 _last_run_at，可以餵時間進去測。"""
    now = now or datetime.now()
    out = []
    for m in discover():
        if not m.get('ok'):
            continue
        trig = m.get('trigger') or {}
        if trig.get('type') != 'schedule':
            continue
        every = trig.get('every_minutes')
        if not every:
            continue
        last = _last_run_at.get(m['name'])
        if last is None or (now - last).total_seconds() >= float(every) * 60:
            out.append(m['name'])
    return out


def tick(now=None):
    """跑一輪。一次只啟動一個——排隊比並行安全。"""
    done = []
    for name in due(now):
        result = run_module(name)
        result['name'] = name
        done.append(result)
        break                     # 下一輪再跑下一個
    return done


def _restore_last_run():
    """從 module_run 把上次執行時刻補回來。

    ⚠ 少了這一步，後端每次重開都會把所有排程模組立刻跑一遍。監控電腦
      跳電重開幾次，就會連續跑好幾輪 pandas/scipy 的子行程。
    """
    try:
        con = connect()
        try:
            for r in con.execute('SELECT name, MAX(finished) f FROM module_run'
                                 ' GROUP BY name'):
                if r['f']:
                    try:
                        _last_run_at[r['name']] = datetime.fromisoformat(r['f'])
                    except ValueError:
                        pass
        finally:
            con.close()
    except Exception as e:
        print('[模組] 還原上次執行時刻失敗（將視為從未跑過）：%s' % e)


def _loop():
    _restore_last_run()
    # 開機後先讓伺服器站穩，再開始跑模組（見 START_DELAY_SECONDS）。
    if _stop_evt.wait(START_DELAY_SECONDS):
        return
    while not _stop_evt.is_set():
        try:
            tick()
        except Exception as e:
            # ⚠ 模組壞掉不得拖垮記錄器。這裡吞例外是刻意的：資料收集的
            #   優先序高於任何分析結果。
            print('[模組] 排程一輪失敗：%s: %s' % (type(e).__name__, e))
        _stop_evt.wait(POLL_SECONDS)


def start():
    """獨立的 daemon 執行緒。

    ⚠ 刻意不跟批次排程（core/scheduler.py）共用那條執行緒：模組的逾時
      上限是 300 秒，共用的話一個慢模組會把批次的自動結束延後五分鐘。
    """
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_evt.clear()
    _thread = threading.Thread(target=_loop, name='module-runner', daemon=True)
    _thread.start()
    mods = discover()
    ok = [m for m in mods if m.get('ok')]
    bad = [m for m in mods if not m.get('ok')]
    print('[模組] 排程已啟動（每 %d 秒檢查，%d 個可用）' % (POLL_SECONDS, len(ok)))
    for m in bad:
        print('[模組] ⚠ %s 無法載入：%s' % (m.get('name'), m.get('error')))


def stop():
    _stop_evt.set()


def status():
    mods = discover()
    return {
        'running': bool(_thread and _thread.is_alive()),
        'poll_seconds': POLL_SECONDS,
        'n_modules': len([m for m in mods if m.get('ok')]),
        'n_broken': len([m for m in mods if not m.get('ok')]),
        'busy': _run_lock.locked(),
        'last_run_at': {k: v.isoformat(sep=' ')
                        for k, v in _last_run_at.items()},
    }
