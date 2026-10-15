# -*- coding: utf-8 -*-
"""論文 Algorithm 2／3 的背景工作（介面「循環分析 → 論文檢定」）。

計算本身在 research/paper_tests.py，這裡只負責排程、追蹤與取結果：
    建立一列 → 開子行程跑 paper_tests.py --run-id N → 它把進度與結果寫回同一列。

⚠ 一律開子行程，不在常駐後端裡算。兩個演算法要幾萬次擬合、跑好幾分鐘，
  而且 research/ 那一串模組會把 pandas／matplotlib／scipy 全拉進來。放在常駐
  行程裡，算完也不會還記憶體（Python 不卸載模組）。
⚠ 一次只跑一個。兩個一起跑不會比較快（都吃同一顆 CPU），只會讓兩邊都慢一倍。
⚠ 只准標準函式庫。
"""
import json
import os
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime

from core import sample_store

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # edge_backend/
RESEARCH = os.path.join(os.path.dirname(HERE), 'research')
SCRIPT = os.path.join(RESEARCH, 'paper_tests.py')
LOG_DIR = os.path.join(HERE, 'logs')

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_test_run (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  created   TEXT,
  started   TEXT,
  finished  TEXT,
  status    TEXT,          -- queued / running / done / error / cancelled
  params    TEXT,          -- JSON
  stage     TEXT,          -- 目前在跑哪一段，或錯誤訊息
  progress  REAL,
  pid       INTEGER,
  result    TEXT,          -- JSON（paper_tests.run 的回傳）
  log       TEXT
);
"""

DEFAULTS = dict(dataset='paper', algo='both', exact_time=False, drop_k_edge=False,
                nrep=25, draws=41, station='BTP-1')


def _db():
    return sample_store._db_path()


def connect():
    con = sqlite3.connect(_db(), timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _reap(con):
    """status 還是 running／queued、但行程已經不在的：標成錯誤，不要永遠卡著。"""
    for r in con.execute("SELECT id, pid, status, created FROM paper_test_run"
                         " WHERE status IN ('queued', 'running')").fetchall():
        # queued 也要查：子行程若在把自己標成 running 之前就死了（例如匯入失敗），
        # 那一列會永遠卡在 queued，之後也啟動不了新工作。
        if r['pid'] and not _alive(r['pid']):
            con.execute("UPDATE paper_test_run SET status = 'error', stage = ?"
                        " WHERE id = ?", ('子行程已不存在（被終止或當機），結果未寫回', r['id']))
    con.commit()


def _clean(params):
    p = dict(DEFAULTS)
    for k, v in (params or {}).items():
        if k in DEFAULTS:
            p[k] = v
    if p['dataset'] not in ('paper', 'paper_all', 'stream'):
        raise ValueError('dataset 只能是 paper、paper_all 或 stream')
    if p['algo'] not in ('2', '3', 'both'):
        raise ValueError('algo 只能是 2、3 或 both')
    p['exact_time'] = bool(p['exact_time'])
    p['drop_k_edge'] = bool(p['drop_k_edge'])
    p['nrep'] = max(2, min(int(p['nrep']), 200))
    p['draws'] = max(2, min(int(p['draws']), 500))
    p['station'] = str(p['station'])[:40]
    return p


def start(params):
    """建立並啟動一個工作。回傳那一列；已有工作在跑就丟 RuntimeError。"""
    if not os.path.isfile(SCRIPT):
        raise RuntimeError('找不到 %s' % SCRIPT)
    p = _clean(params)
    con = connect()
    try:
        _reap(con)
        busy = con.execute("SELECT id FROM paper_test_run WHERE status IN ('queued','running')").fetchone()
        if busy:
            raise RuntimeError('第 %d 號工作還在跑，一次只跑一個' % busy['id'])
        now = datetime.now().isoformat(sep=' ', timespec='seconds')
        cur = con.execute("INSERT INTO paper_test_run (created, status, params, stage, progress)"
                          " VALUES (?, 'queued', ?, '等待啟動', 0)", (now, json.dumps(p)))
        run_id = cur.lastrowid
        con.commit()
        os.makedirs(LOG_DIR, exist_ok=True)
        log = open(os.path.join(LOG_DIR, 'paper_test_%d.log' % run_id), 'w', encoding='utf-8')
        kw = {}
        if os.name == 'posix':
            kw['start_new_session'] = True          # 後端重開不會連帶砍掉它
        proc = subprocess.Popen([sys.executable, SCRIPT, '--run-id', str(run_id), '--db', _db()],
                                cwd=RESEARCH, stdout=log, stderr=subprocess.STDOUT, **kw)
        con.execute("UPDATE paper_test_run SET pid = ? WHERE id = ?", (proc.pid, run_id))
        con.commit()
        return get(run_id, con=con)
    finally:
        con.close()


def _row(r, full=True):
    d = dict(r)
    d['params'] = json.loads(d['params']) if d.get('params') else {}
    res = json.loads(d['result']) if d.get('result') else None
    if res and not full:
        # 清單只要頭條數字；逐次抽樣的陣列留給單筆查詢
        a2, a3 = res.get('algorithm2') or {}, res.get('algorithm3') or {}
        res = {k: res.get(k) for k in ('n_cycles_total', 'n_retained', 'n_k_edge', 'rb_median',
                                        'frac_negative', 'seconds', 'error')}
        if a2:
            res['a2'] = {'rho_observed': a2.get('rho_observed'),
                         'B0': (a2['baselines'].get('B0') or {}).get('rho_mean'),
                         'B1': (a2['baselines'].get('B1') or {}).get('rho_mean'),
                         'B2': (a2['baselines'].get('B2') or {}).get('rho_mean'),
                         'bias_B0': (a2['baselines'].get('B0') or {}).get('bias_pct')}
        if a3:
            res['a3'] = {k: a3.get(k) for k in ('observed_median', 'null_median', 'null_max', 'p_value', 'draws')}
    d['result'] = res
    d.pop('log', None) if not full else None
    return d


def get(run_id, con=None):
    own = con is None
    con = con or connect()
    try:
        _reap(con)
        r = con.execute('SELECT * FROM paper_test_run WHERE id = ?', (int(run_id),)).fetchone()
        return _row(r) if r else None
    finally:
        if own:
            con.close()


def list_runs(limit=50):
    con = connect()
    try:
        _reap(con)
        return [_row(r, full=False) for r in
                con.execute('SELECT * FROM paper_test_run ORDER BY id DESC LIMIT ?', (int(limit),))]
    finally:
        con.close()


def cancel(run_id):
    con = connect()
    try:
        r = con.execute('SELECT pid, status FROM paper_test_run WHERE id = ?', (int(run_id),)).fetchone()
        if not r or r['status'] not in ('queued', 'running'):
            return False
        if _alive(r['pid']):
            try:
                os.kill(int(r['pid']), signal.SIGTERM)
            except OSError:
                pass
        con.execute("UPDATE paper_test_run SET status = 'cancelled', stage = '已取消',"
                    " finished = ? WHERE id = ?",
                    (datetime.now().isoformat(sep=' ', timespec='seconds'), int(run_id)))
        con.commit()
        return True
    finally:
        con.close()
