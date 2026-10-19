# -*- coding: utf-8 -*-
"""研究實驗排程（介面「實驗排程」）：把要在 Jetson 上跑的研究腳本排成佇列，依序執行。

和 paper_jobs 的差別：那邊一次只收一個、跑完才能再按；這裡是**佇列**——可以先排好
一整晚的實驗，還沒開始的可以改參數、調順序、暫緩、取消。

    建立一列（queued）→ 排程執行緒發現沒有工作在跑 → 取順位最前的一列啟動子行程
    → 子行程結束時把結束碼寫進檔案 → 排程執行緒讀到就標成 done／error → 下一個

⚠ 只准跑白名單裡的腳本（TEMPLATES），參數逐一檢查型別與範圍，再組成命令列。
  不接受任意命令或任意路徑——這個頁面是開在網路上的。
⚠ 一次只跑一個。研究腳本都吃同一顆 GPU，兩個一起跑只會兩邊都慢、還可能爆記憶體。
⚠ 子行程開在自己的 session（start_new_session），後端重開不會砍到它；結束碼由外層
  sh 寫進檔案，所以就算子行程跑完時後端剛好不在，回來也知道它成功還是失敗。
⚠ 只准標準函式庫（常駐後端不 import torch／numpy）。
"""
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime

from core import sample_store

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # edge_backend/
REPO = os.path.dirname(HERE)
RESEARCH = os.path.join(REPO, 'research')
LOG_DIR = os.path.join(HERE, 'logs', 'research_jobs')
TICK_SEC = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_job (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  template  TEXT,
  name      TEXT,
  params    TEXT,          -- JSON（已通過檢查）
  status    TEXT,          -- queued / held / running / done / error / cancelled
  position  REAL,          -- 佇列順位，小的先跑
  created   TEXT,
  started   TEXT,
  finished  TEXT,
  pid       INTEGER,
  exit_code INTEGER,
  log_path  TEXT,
  out_dir   TEXT,
  note      TEXT
);
CREATE TABLE IF NOT EXISTS research_queue_state (k TEXT PRIMARY KEY, v TEXT);
"""


def _python():
    """研究腳本要 torch＋CUDA：Jetson 上那套在系統 python3，不在後端的 venv。"""
    p = os.environ.get('REACTOR_RESEARCH_PYTHON')
    if p:
        return p
    return '/usr/bin/python3' if os.path.isfile('/usr/bin/python3') else sys.executable


# ══════════════════════════════════════════════════════════
# 白名單：腳本＋參數表
#   每個參數：type（int／float／bool／choice／str）、default、範圍或選項、說明
#   argv(p, job) 回傳命令列參數；env(p) 回傳額外環境變數；out(p, job) 回傳輸出資料夾
# ══════════════════════════════════════════════════════════
def _npe_argv(p, job):
    a = ['--mode', p['mode'], '--noise', p['noise'], '--channels', p['channels'],
         '--folds', p['folds'], '--seeds', str(p['seeds']), '--max_epochs', str(p['max_epochs']),
         '--patience', str(p['patience']), '--K', str(p['K']), '--ns', str(p['ns']),
         '--tag', _npe_tag(p, job)]
    for k in ('n_train', 'n_test', 'bs'):
        if p[k]:
            a += ['--' + k, str(p[k])]
    if p['quick']:
        a.append('--quick')
    return a


def _npe_tag(p, job):
    return 'job%d_%s_%s_%s' % (job['id'], p['mode'], p['noise'], p['channels'].replace('+', ''))


TEMPLATES = {
    'npe_separation': dict(
        label='NPE：pH＋壓力分離生物／洩漏／溶解',
        script='ml/npe_separation.py',
        doc='攤銷式神經後驗估計（CNN＋BiGRU＋混合密度網路）。依模板 3 折交叉驗證，'
            '先驗 A 訓練、A／B1／B2 測試；80% 涵蓋率在 B1、B2 皆落在 0.70–0.90 才算校準通過。',
        params=dict(
            mode=dict(type='choice', choices=['single', 'group'], default='single',
                      help='single＝單循環；group＝K 個循環（τ=1、τ=10 各半）共用生物與洩漏'),
            noise=dict(type='choice', choices=['N2', 'clean'], default='N2',
                       help='N2＝疊上真實殘差；clean＝無雜訊（物理上限）'),
            channels=dict(type='choice', choices=['p+ph', 'p'], default='p+ph',
                          help='p＝消融：pH 通道歸零，只用壓力'),
            folds=dict(type='str', default='0,1,2', pattern=r'^[0-2](,[0-2]){0,2}$',
                       help='要跑哪幾折（逗號分隔，0–2）'),
            seeds=dict(type='int', default=3, min=1, max=10, help='每折訓練幾個種子做集成'),
            n_train=dict(type='int', default=0, min=0, max=200000,
                         help='訓練樣本數；0＝預設（single 40000／group 8000）'),
            n_test=dict(type='int', default=0, min=0, max=50000,
                        help='每個先驗的測試樣本數；0＝預設（single 6000／group 1500）'),
            max_epochs=dict(type='int', default=60, min=1, max=500, help='最多幾輪'),
            patience=dict(type='int', default=8, min=1, max=100, help='驗證損失幾輪沒進步就停'),
            K=dict(type='int', default=8, min=2, max=32, help='group 模式每組幾個循環'),
            bs=dict(type='int', default=0, min=0, max=4096, help='批次大小；0＝預設（single 512／group 64）'),
            ns=dict(type='int', default=2000, min=200, max=20000, help='後驗抽樣數'),
            quick=dict(type='bool', default=False, help='快速試跑（樣本少、8 輪、1 個種子）'),
        ),
        argv=_npe_argv,
        env=lambda p: {'ML_DEVICE': 'cuda'},
        out=lambda p, job: os.path.join(RESEARCH, 'ml', 'out_npe', _npe_tag(p, job)),
    ),
    'pump_tagger': dict(
        label='Bi-LSTM 泵狀態標註器',
        script='ml/pump_tagger.py',
        doc='從壓力／ORP／pH 增量標出泵開關；換種子重跑看變異。',
        params=dict(
            seed=dict(type='int', default=20261016, min=0, max=2 ** 31 - 1, help='隨機種子（PT_SEED）'),
            qa=dict(type='bool', default=False, help='加 --qa 輸出品管圖'),
        ),
        argv=lambda p, job: ['--qa'] if p['qa'] else [],
        env=lambda p: {'ML_DEVICE': 'cuda', 'PT_SEED': str(p['seed'])},
        out=lambda p, job: os.path.join(RESEARCH, 'ml', 'out_pump_tagger', 'seed%d' % p['seed']),
    ),
    'pinn_minute': dict(
        label='每分鐘 PINN（UDE）：CO2／H2 進出與甲烷',
        script='ml/pinn_minute_dissolution.py',
        doc='質量守恆寫成 ODE、菌的吃氣速率律由神經網路學（UDE），同時擬合每分鐘壓力與 pH（CO2）。'
            '比較定速／Monod／神經三種速率律，並做洩漏份額剖面與模擬回收測試。只用 CPU，多起點平行。',
        params=dict(
            quick=dict(type='bool', default=False, help='快速試跑（起點少、迭代少）'),
        ),
        argv=lambda p, job: ['--quick'] if p['quick'] else [],
        env=lambda p: {'PYTHONWARNINGS': 'ignore'},
        out=lambda p, job: os.path.join(RESEARCH, 'ml', 'out_pinn_minute'),
    ),
    'ch4_sequential': dict(
        label='甲烷份額模型：逐次更新',
        script='ml/ch4_sequential.py',
        doc='甲烷 ≈ 份額 × 壓降消耗 × 化學計量上限。每有新的排氣量測，就把它加進訓練、更新下一次的份額預測'
            '（卡爾曼漂移）。完整模式另做逐次前推驗證，比較 ORP／pH／壓力特徵有沒有贏過「過去平均」。'
            '⚠ 標籤來自 docs/analysis_charts_3batch/bio_activity_vents.csv，新排氣要先重跑 bio_activity_timeline.py。',
        params=dict(
            update_only=dict(type='bool', default=True, help='只更新狀態（幾秒）；關掉＝完整前推驗證（讀全部原始資料，數分鐘）'),
        ),
        argv=lambda p, job: ['--update'] if p['update_only'] else [],
        env=lambda p: {},
        out=lambda p, job: os.path.join(RESEARCH, 'ml', 'out_ch4_seq'),
    ),
    'softsensor_design': dict(
        label='軟感測器錨點排程設計',
        script='ml/softsensor_anchor_design.py',
        doc='模擬「何時排氣量 CH4」的策略，比較每單位錨點預算換到的精度。',
        params=dict(
            quick=dict(type='bool', default=False, help='快速試跑'),
        ),
        argv=lambda p, job: ['--quick'] if p['quick'] else [],
        env=lambda p: {'ML_DEVICE': 'cuda'},
        out=lambda p, job: os.path.join(RESEARCH, 'ml', 'out_softsensor_design'),
    ),
}


def templates():
    """給前端產生表單用：不含函式。"""
    return [dict(id=k, label=t['label'], doc=t['doc'], script=t['script'], params=t['params'])
            for k, t in TEMPLATES.items()]


def _clean(template, params):
    if template not in TEMPLATES:
        raise ValueError('沒有這個實驗範本：%s' % template)
    spec = TEMPLATES[template]['params']
    params = params or {}
    unknown = set(params) - set(spec)
    if unknown:
        raise ValueError('不認得的參數：%s' % '、'.join(sorted(unknown)))
    out = {}
    for k, s in spec.items():
        v = params.get(k, s['default'])
        t = s['type']
        try:
            if t == 'int':
                v = int(v)
                if not s['min'] <= v <= s['max']:
                    raise ValueError
            elif t == 'float':
                v = float(v)
                if not s['min'] <= v <= s['max']:
                    raise ValueError
            elif t == 'bool':
                v = v if isinstance(v, bool) else str(v).lower() in ('1', 'true', 'yes', 'on')
            elif t == 'choice':
                if v not in s['choices']:
                    raise ValueError
            else:
                v = str(v).strip()
                if 'pattern' in s and not re.match(s['pattern'], v):
                    raise ValueError
        except (TypeError, ValueError):
            rng = ('，範圍 %s–%s' % (s['min'], s['max'])) if 'min' in s else \
                  ('，可選 %s' % '／'.join(s['choices'])) if 'choices' in s else ''
            raise ValueError('參數 %s 不合法：%r%s' % (k, params.get(k), rng))
        out[k] = v
    return out


# ══════════════════════════════════════════════════════════
# 資料表
# ══════════════════════════════════════════════════════════
def connect():
    con = sqlite3.connect(sample_store._db_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _now():
    return datetime.now().isoformat(sep=' ', timespec='seconds')


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    try:                                          # 殭屍行程（已結束、等人收）也算不在
        with open('/proc/%d/stat' % int(pid)) as fh:
            return fh.read().split(') ')[-1][:1] != 'Z'
    except OSError:
        return True


def _exit_file(job_id):
    return os.path.join(LOG_DIR, 'job_%d.exit' % job_id)


def _paused(con):
    r = con.execute("SELECT v FROM research_queue_state WHERE k = 'paused'").fetchone()
    return bool(r and r['v'] == '1')


def set_paused(flag):
    con = connect()
    try:
        con.execute("INSERT OR REPLACE INTO research_queue_state (k, v) VALUES ('paused', ?)",
                    ('1' if flag else '0',))
        con.commit()
        return state()
    finally:
        con.close()


def _reap(con):
    """running 但行程已不在 → 讀結束碼檔決定 done／error。"""
    for r in con.execute("SELECT id, pid FROM research_job WHERE status = 'running'").fetchall():
        if _alive(r['pid']):
            continue
        code = None
        try:
            with open(_exit_file(r['id'])) as fh:
                code = int(fh.read().strip())
        except (OSError, ValueError):
            pass
        if code is None:
            st, note = 'error', '行程已不在、也沒有結束碼（被強制終止或 Jetson 重開過）'
        elif code == 0:
            st, note = 'done', None
        else:
            st, note = 'error', '結束碼 %d（看紀錄最後幾行）' % code
        con.execute("UPDATE research_job SET status = ?, exit_code = ?, finished = ?,"
                    " note = COALESCE(?, note) WHERE id = ? AND status = 'running'",
                    (st, code, _now(), note, r['id']))
    con.commit()


def _launch(con, job):
    t = TEMPLATES[job['template']]
    p = json.loads(job['params'])
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, 'job_%d.log' % job['id'])
    ef = _exit_file(job['id'])
    if os.path.exists(ef):
        os.remove(ef)
    script = os.path.join(RESEARCH, t['script'])
    cmd = [_python(), '-u', script] + t['argv'](p, dict(job))
    env = dict(os.environ, PYTHONUNBUFFERED='1', **t['env'](p))
    # 外層 sh 等子行程結束後把結束碼寫進檔案；"$@" 原樣傳參數，不經 shell 解讀
    wrapped = ['/bin/sh', '-c', '"$@"; echo $? > "%s"' % ef, 'job'] + cmd \
        if os.name == 'posix' else cmd
    log = open(log_path, 'a', encoding='utf-8')
    log.write('# %s 啟動：%s\n' % (_now(), ' '.join(cmd)))
    log.flush()
    kw = {'start_new_session': True} if os.name == 'posix' else {}
    try:
        proc = subprocess.Popen(wrapped, cwd=os.path.dirname(script), stdout=log,
                                stderr=subprocess.STDOUT, env=env, **kw)
    except OSError as e:
        con.execute("UPDATE research_job SET status = 'error', finished = ?, note = ? WHERE id = ?",
                    (_now(), '無法啟動：%s' % e, job['id']))
        con.commit()
        return
    finally:
        log.close()
    con.execute("UPDATE research_job SET status = 'running', started = ?, pid = ?, log_path = ?,"
                " out_dir = ?, exit_code = NULL WHERE id = ?",
                (_now(), proc.pid, log_path, t['out'](p, dict(job)), job['id']))
    con.commit()


_LOCK = threading.Lock()


def tick():
    """收掉結束的工作；沒有在跑的、佇列沒暫停 → 啟動順位最前的那一個。"""
    with _LOCK:
        con = connect()
        try:
            _reap(con)
            if con.execute("SELECT 1 FROM research_job WHERE status = 'running'").fetchone():
                return
            if _paused(con):
                return
            nxt = con.execute("SELECT * FROM research_job WHERE status = 'queued'"
                              " ORDER BY position, id LIMIT 1").fetchone()
            if nxt:
                _launch(con, nxt)
        finally:
            con.close()


_STOP = threading.Event()
_THREAD = None


def _loop():
    while not _STOP.wait(TICK_SEC):
        try:
            tick()
        except Exception as e:                      # 排程掛掉不能拖垮後端
            print('[研究排程] %s: %s' % (type(e).__name__, e))


def start():
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name='research-jobs', daemon=True)
    _THREAD.start()


def stop():
    _STOP.set()


# ══════════════════════════════════════════════════════════
# 查詢與操作（給 API）
# ══════════════════════════════════════════════════════════
_PROG = re.compile(r'^\[進度\]\s*(.+)$')


def _tail(path, n_bytes=4000):
    if not path or not os.path.isfile(path):
        return ''
    with open(path, 'rb') as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - n_bytes))
        return fh.read().decode('utf-8', 'replace')


def _summary(out_dir):
    """npe 的 results.json 有 summary：列在清單上給人一眼看結果。"""
    f = os.path.join(out_dir or '', 'results.json')
    if not out_dir or not os.path.isfile(f):
        return None
    try:
        with open(f, encoding='utf-8') as fh:
            return json.load(fh).get('summary')
    except (OSError, ValueError):
        return None


def _row(r):
    d = dict(r)
    d['params'] = json.loads(d['params']) if d.get('params') else {}
    d['label'] = TEMPLATES.get(d['template'], {}).get('label', d['template'])
    if d['status'] == 'running':
        prog = [m.group(1) for m in map(_PROG.match, _tail(d['log_path'], 20000).splitlines()) if m]
        d['progress'] = prog[-1] if prog else None
        try:
            d['elapsed_sec'] = int((datetime.now() - datetime.fromisoformat(d['started'])).total_seconds())
        except (TypeError, ValueError):
            d['elapsed_sec'] = None
    if d['status'] == 'done':
        d['summary'] = _summary(d['out_dir'])
    return d


def state():
    con = connect()
    try:
        _reap(con)
        rows = [_row(r) for r in con.execute(
            "SELECT * FROM research_job ORDER BY CASE status WHEN 'running' THEN 0"
            " WHEN 'queued' THEN 1 WHEN 'held' THEN 1 ELSE 2 END, position, id DESC").fetchall()]
        active = [r for r in rows if r['status'] in ('running', 'queued', 'held')]
        hist = sorted([r for r in rows if r['status'] not in ('running', 'queued', 'held')],
                      key=lambda r: r['id'], reverse=True)[:100]
        return dict(paused=_paused(con), python=_python(), active=active, history=hist)
    finally:
        con.close()


def get(job_id):
    con = connect()
    try:
        r = con.execute('SELECT * FROM research_job WHERE id = ?', (int(job_id),)).fetchone()
        return _row(r) if r else None
    finally:
        con.close()


def log(job_id, n_bytes=20000):
    j = get(job_id)
    if not j:
        return None
    return dict(id=j['id'], status=j['status'], text=_tail(j['log_path'], n_bytes))


def _next_pos(con):
    r = con.execute("SELECT MAX(position) AS m FROM research_job").fetchone()
    return (r['m'] or 0) + 1


def create(template, params, name=None, note=None, hold=False):
    p = _clean(template, params)
    con = connect()
    try:
        cur = con.execute("INSERT INTO research_job (template, name, params, status, position, created, note)"
                          " VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (template, (name or '').strip()[:80] or TEMPLATES[template]['label'],
                           json.dumps(p, ensure_ascii=False), 'held' if hold else 'queued',
                           _next_pos(con), _now(), (note or '').strip()[:500] or None))
        con.commit()
        jid = cur.lastrowid
    finally:
        con.close()
    tick()
    return get(jid)


def update(job_id, params=None, name=None, note=None):
    """只有還沒開始的（queued／held）能改參數。名稱與備註任何時候都能改。"""
    con = connect()
    try:
        r = con.execute('SELECT * FROM research_job WHERE id = ?', (int(job_id),)).fetchone()
        if not r:
            raise KeyError(job_id)
        if params is not None:
            if r['status'] not in ('queued', 'held'):
                raise RuntimeError('已經開始或結束的工作不能改參數；要改請「複製」一份再改')
            con.execute('UPDATE research_job SET params = ? WHERE id = ?',
                        (json.dumps(_clean(r['template'], params), ensure_ascii=False), r['id']))
        if name is not None:
            con.execute('UPDATE research_job SET name = ? WHERE id = ?', (name.strip()[:80] or r['name'], r['id']))
        if note is not None:
            con.execute('UPDATE research_job SET note = ? WHERE id = ?', (note.strip()[:500] or None, r['id']))
        con.commit()
    finally:
        con.close()
    return get(job_id)


def action(job_id, act):
    con = connect()
    try:
        _reap(con)
        r = con.execute('SELECT * FROM research_job WHERE id = ?', (int(job_id),)).fetchone()
        if not r:
            raise KeyError(job_id)
        st = r['status']
        if act == 'hold':
            if st != 'queued':
                raise RuntimeError('只有排隊中的工作能暫緩')
            con.execute("UPDATE research_job SET status = 'held' WHERE id = ?", (r['id'],))
        elif act == 'resume':
            if st != 'held':
                raise RuntimeError('只有暫緩中的工作能恢復')
            con.execute("UPDATE research_job SET status = 'queued' WHERE id = ?", (r['id'],))
        elif act in ('up', 'down', 'top'):
            if st not in ('queued', 'held'):
                raise RuntimeError('只有還沒開始的工作能調順序')
            q = con.execute("SELECT id, position FROM research_job WHERE status IN ('queued','held')"
                            " ORDER BY position, id").fetchall()
            ids = [x['id'] for x in q]
            i = ids.index(r['id'])
            if act == 'top':
                ids.insert(0, ids.pop(i))
            else:
                j = i - 1 if act == 'up' else i + 1
                if 0 <= j < len(ids):
                    ids[i], ids[j] = ids[j], ids[i]
            base = min(x['position'] for x in q)
            for k, jid in enumerate(ids):
                con.execute('UPDATE research_job SET position = ? WHERE id = ?', (base + k, jid))
        elif act == 'cancel':
            if st == 'running':
                try:
                    os.killpg(os.getpgid(int(r['pid'])), signal.SIGTERM)    # 連外層 sh 一起
                except (OSError, ValueError, AttributeError):
                    try:
                        os.kill(int(r['pid']), signal.SIGTERM)
                    except (OSError, ValueError):
                        pass
            elif st not in ('queued', 'held'):
                raise RuntimeError('這個工作已經結束了')
            con.execute("UPDATE research_job SET status = 'cancelled', finished = ?, note = COALESCE(note, '手動取消')"
                        " WHERE id = ?", (_now(), r['id']))
        elif act == 'clone':
            con.commit()
            con.close()
            con = None
            return create(r['template'], json.loads(r['params']), name='%s（複製 #%d）' % (r['name'], r['id']),
                          hold=True)
        elif act == 'delete':
            if st == 'running':
                raise RuntimeError('執行中的工作要先取消才能刪')
            con.execute('DELETE FROM research_job WHERE id = ?', (r['id'],))
        else:
            raise ValueError('不認得的動作：%s' % act)
        con.commit()
    finally:
        if con is not None:
            con.close()
    tick()
    return get(job_id)
