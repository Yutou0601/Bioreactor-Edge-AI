
# -*- coding: utf-8 -*-
"""系統測試：一次跑完，任何一項紅了就是有東西壞了。

    python system_test.py

十二項檢查，由內而外：

  1 記憶體守門  常駐核心不得載入 torch/pandas/sklearn/scipy/xgboost
  2 估計器一致  線上實作 vs 離線腳本，逐段比對 (曲率, k, r_b)
  3 切段正確    必須以資料夾為單位；逐檔處理會把跨午夜的循環砍斷
  4 資料庫      建表、匯入、去重（同一段不會重複寫入）
  5 API         /api/health、/api/rate、/api/cycles、/api/ingest_folder
  6 前端        後端有沒有把 dist/ 供應出去
  7 校準        calibration.json 有沒有被正確套用
  8 批次排程    自動開始/結束的判定；預設關閉的守門
  9 記憶體守門  **操作過之後**再檢查一次——第 1 項擋不住請求路徑偷渡
 10 分析模組    子行程隔離：跑模組不得把它的相依帶進常駐核心
 11 sample 表   重啟不掉資料；還原有上限（不然一年份吃 259 MB）
 12 CH4 即時路徑 不得拉進 scipy／xgboost；find_peaks 與 scipy 逐點一致

⚠ 第 1 項是最容易悄悄回歸的。torch 曾經因為 routes.py 一行模組層級
  import 而在每次啟動時載入 496 MB，而且沒有任何錯誤訊息。
  只要有人為了方便在核心 import 了重量級套件，這一項就會紅。

⚠ 第 2 項是搬移的驗收條件。跑得動不等於搬對了——數字必須與離線腳本
  逐位元相同，否則系統與論文對不上，而且不會報錯。

不需要感測器、不需要 MQTT broker。開發筆電上就能跑。
"""
import io
import os
import sys
import tempfile

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 第 2 項要與離線腳本逐段比對。那些腳本 2026-09-10 從 edge_backend/ 搬到了
# research/（見 research/README.md）——常駐核心的目錄只留上線程式碼。
RESEARCH = os.path.join(os.path.dirname(HERE), 'research')
if os.path.isdir(RESEARCH):
    sys.path.insert(0, RESEARCH)

PASS, FAIL = [], []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    print('  %s %-44s %s' % ('[OK]' if ok else '[★ ]', name, detail))
    return ok


def find_data_folder():
    """找一個有 CSV 的期間資料夾來測。"""
    # 2026-09-10 Testing_data 隨研究腳本搬到 research/。用同一個解析器，
    # 舊位置（edge_backend/Testing_data）仍然找得到。
    try:
        from paths import testing_data
        root = testing_data()
    except Exception:
        root = os.path.join(HERE, 'Testing_data')
    if not os.path.isdir(root):
        return None
    import glob
    best, n = None, 0
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d)
        if not os.path.isdir(p):
            continue
        c = len(glob.glob(os.path.join(p, '*.csv')))
        if c > n:
            best, n = p, c
    return best


# ── 1 記憶體守門 ────────────────────────────────────────────
print('\n1. 記憶體守門（常駐核心的相依）')
HEAVY = ('torch', 'pandas', 'sklearn', 'scipy', 'xgboost', 'onnxruntime')
import main                                                  # noqa: E402
loaded = [m for m in HEAVY if m in sys.modules]
check('匯入 main 不載入重量級套件', not loaded,
      ('★ 載入了 ' + ', '.join(loaded)) if loaded else 'numpy only')

# ⚠ 上面那一項只執行了 main.py 的**模組層級**程式碼。lifespan 是伺服器
#   啟動時才跑的，所以它擋不住「在 lifespan 裡 import 重量級套件」。
#
#   這個洞真的被踩過：main.py 的 lifespan 無條件呼叫
#   load_model_and_scalers()，而 core/inference.py 第 2 行是模組層級的
#   `import torch`。正式啟動時 RSS 54.1 → 313.8 MB（預算 60 MB），而這一
#   組測試從頭到尾是綠的——因為測試從來沒有跑過 lifespan。
#
#   TestClient 只有當成 context manager 用才會觸發 startup/shutdown。
from fastapi.testclient import TestClient as _TC                # noqa: E402
with _TC(main.app):
    pass
after_start = [m for m in HEAVY if m in sys.modules]
check('走完啟動流程（lifespan）也不載入', not after_start,
      ('★ lifespan 載入了 ' + ', '.join(after_start)) if after_start
      else 'lifespan 跑完仍是 numpy only')

# ── 2 估計器與離線腳本一致 ──────────────────────────────────
print('\n2. 估計器一致性（線上 vs 離線）')
try:
    import numpy as np
    from core import cycle_estimator as ce
    from dataset_c import collect_c
    from rb_recovery_study import curvature as off_curv
    from simulator_check import fit_LE as off_fit

    dc = dk = drb = 0.0
    n = nscr = 0
    rb_off, rb_on = [], []
    for _tag, t, y in collect_c():
        t = np.asarray(t, float)
        y = np.asarray(y, float)
        co, cn = off_curv(t, y), ce.curvature(t, y)
        if np.isfinite(co) and np.isfinite(cn):
            dc = max(dc, abs(co - cn))
        n += 1
        if not (np.isfinite(co) and co >= ce.CURV_MIN):
            continue
        nscr += 1
        a, b = off_fit(t, y), ce.fit_le(t, y)
        dk = max(dk, abs(a['k'] - b['k']))
        drb = max(drb, abs(a['rb'] - b['rb']))
        rb_off.append(a['rb'])
        rb_on.append(b['rb'])
    check('逐段曲率相同', dc == 0, 'max diff %.1e' % dc)
    check('逐段 k 相同', dk == 0, 'max diff %.1e' % dk)
    check('逐段 r_b 相同', drb == 0, 'max diff %.1e' % drb)
    m_off, m_on = float(np.median(rb_off)), float(np.median(rb_on))
    check('聚合中位數相同', m_off == m_on,
          '%d 段  離線 %.6f  線上 %.6f' % (nscr, m_off, m_on))
except Exception as e:                                       # noqa: BLE001
    check('估計器一致性', False, '%s: %s' % (type(e).__name__, e))

# ── 3 切段：必須以資料夾為單位 ──────────────────────────────
print('\n3. 切段（跨午夜的循環不得被砍斷）')
folder = find_data_folder()
if not folder:
    check('找得到測試資料', False, 'Testing_data 下沒有 CSV')
else:
    import glob
    from core import cycle_store as cs
    files = sorted(glob.glob(os.path.join(folder, '*.csv')))
    whole = cs.read_series(files)
    per_file = 0
    for f in files:
        one = cs.read_series([f])
        if one:
            per_file += len(ce.segment(one[1], one[2]))
    n_whole = len(ce.segment(whole[1], whole[2])) if whole else 0
    check('整批切段數 <= 逐檔切段數', n_whole <= per_file,
          '整批 %d，逐檔 %d（逐檔較多＝跨日被砍斷）' % (n_whole, per_file))
    med = float(np.median([whole[1][b] - whole[1][a]
                           for a, b in ce.segment(whole[1], whole[2])]))
    check('循環時長中位數 > 4 hr', med > 4.0, '%.1f hr' % med)

# ── 4 資料庫 ────────────────────────────────────────────────
print('\n4. 資料庫')
tmpdb = os.path.join(tempfile.gettempdir(), 'reactor_systest.db')
if os.path.exists(tmpdb):
    os.remove(tmpdb)
try:
    con = cs.connect(tmpdb)
    r1 = cs.ingest_folder(folder, con=con)
    check('匯入成功', r1.get('inserted', 0) > 0, str(r1))
    r2 = cs.ingest_folder(folder, con=con)
    check('重複匯入不會重寫', r2.get('inserted', 0) == 0,
          '第二次寫入 %d 筆' % r2.get('inserted', -1))
    rows = cs.list_cycles(con=con)
    check('查得到循環', len(rows) > 0, '%d 筆' % len(rows))
    bad = [r for r in rows if r['screened'] and r['rb_hat'] is None]
    check('通過預篩者都有估計值', not bad, '缺值 %d 筆' % len(bad))
    con.close()
except Exception as e:                                       # noqa: BLE001
    check('資料庫', False, '%s: %s' % (type(e).__name__, e))

# ── 5 API ───────────────────────────────────────────────────
print('\n5. API')
try:
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    for path in ('/api/health', '/api/rate', '/api/cycles',
                 '/api/records', '/api/experiment/runs'):
        r = c.get(path)
        check('GET %s' % path, r.status_code == 200, 'HTTP %d' % r.status_code)
    r = c.post('/api/ingest_folder', params={'folder': folder})
    check('POST /api/ingest_folder', r.status_code == 200,
          'HTTP %d' % r.status_code)
    r = c.post('/api/ingest_folder', params={'folder': 'no/such/dir'})
    check('不存在的資料夾要回 400', r.status_code == 400,
          'HTTP %d' % r.status_code)
except Exception as e:                                       # noqa: BLE001
    check('API', False, '%s: %s' % (type(e).__name__, e))

# ── 6 前端 ──────────────────────────────────────────────────
print('\n6. 前端')
try:
    r = c.get('/')
    check('後端供應 dist/', r.status_code == 200 and '<html' in r.text.lower(),
          'HTTP %d，%d bytes' % (r.status_code, len(r.text)))
    # ⚠ SPA 路由回退：vue-router 用 createWebHistory，/rate 等路徑在伺服器
    #   上沒有對應檔案。只掛 StaticFiles(html=True) 的話，直接輸入網址或
    #   在該頁重新整理就會 404。實際踩過一次。
    for sub in ('/rate', '/report', '/experiment', '/import', '/modules'):
        r = c.get(sub)
        check('前端路由 %s 回退到 index.html' % sub,
              r.status_code == 200 and '<html' in r.text[:200].lower(),
              'HTTP %d' % r.status_code)
    r = c.get('/api/rate')
    check('/api 不被 SPA 回退攔截', r.status_code == 200
          and r.text.lstrip().startswith('{'), 'HTTP %d' % r.status_code)
except Exception as e:                                       # noqa: BLE001
    check('前端', False, str(e))

# ── 7 校準 ──────────────────────────────────────────────────
print('\n7. 校準常數')
calib = cs.load_calibration()
if calib is None:
    check('calibration.json 存在', False, '找不到；rb 欄會是未校準值')
else:
    check('calibration.json 存在', True, '版本 %s' % calib.get('calibrated_at'))
    d = c.get('/api/rate').json()
    if d.get('median_rb') and d.get('median_rb_hat'):
        got = d['median_rb'] / d['median_rb_hat'] - 1
        want = calib['correction']
        check('校準確實套用到 rb 欄', abs(got - want) < 1e-9,
              '實測 %+.4f，應為 %+.4f' % (got, want))

# ── 8 批次排程 ──────────────────────────────────────────────
print('\n8. 批次排程（自動開始／自動結束）')
try:
    from datetime import datetime, timedelta
    from core import experiment_store as exp
    from core import scheduler

    NOW = datetime(2026, 9, 2, 12, 0, 0)

    def _ts(dt):
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    past, future = _ts(NOW - timedelta(hours=1)), _ts(NOW + timedelta(hours=5))
    runs = [
        # 排定時間已過，但沒勾旗標 → 不該被碰
        {'run_id': 'X1', 'status': 'planned', 'scheduled_start': past},
        {'run_id': 'X2', 'status': 'planned', 'auto_start': True,
         'scheduled_start': past},
        {'run_id': 'X3', 'status': 'planned', 'auto_start': True,
         'scheduled_start': future},
        # 已跑 50hr、target 48hr → 逾時
        {'run_id': 'X4', 'status': 'running', 'auto_stop': True,
         'start_time': _ts(NOW - timedelta(hours=50)), 'target_hours': 48.0},
        # 逾時但沒勾 auto_stop → 不該被碰
        {'run_id': 'X5', 'status': 'running',
         'start_time': _ts(NOW - timedelta(hours=50)), 'target_hours': 48.0},
    ]
    acts = {a['run_id']: a for a in scheduler.pending_actions(runs, NOW)}
    # ⚠ 這一項是預設安全的守門：只要有人把旗標改成預設開啟，既有的手動批次
    #   就會在下一次啟動時被排程器接管、悄悄地自動結束。
    check('沒勾旗標者不被排程動到',
          'X1' not in acts and 'X5' not in acts, str(sorted(acts)))
    check('auto_start 到點才觸發',
          acts.get('X2', {}).get('action') == 'start' and 'X3' not in acts,
          str(sorted(acts)))
    check('auto_stop 逾時觸發', acts.get('X4', {}).get('action') == 'vent')
    # ⚠ 後端若停機數小時再開，批次必須結束在它「該結束的時間」，不是被發現
    #   的時間，否則量測結果的時間窗會比設計多出停機那段。
    check('結束時刻＝應結束時刻，非發現時刻',
          acts.get('X4', {}).get('at') == _ts(NOW - timedelta(hours=2)),
          acts.get('X4', {}).get('at'))
    check('scheduled_end 優先於 target_hours',
          exp.due_time({'start_time': _ts(NOW), 'target_hours': 48.0,
                        'scheduled_end': '2026-09-02T09:00'})
          == datetime(2026, 9, 2, 9, 0, 0))
    r = c.get('/api/experiment/scheduler')
    check('GET /api/experiment/scheduler', r.status_code == 200,
          'HTTP %d' % r.status_code)
    # 面板必須講清楚自動停止不會停機——只讀不控，現場仍須有人排氣。
    check('狀態含「不會關閥」的提示', '不會關閥' in r.json().get('note', ''))
except Exception as e:                                       # noqa: BLE001
    check('批次排程', False, '%s: %s' % (type(e).__name__, e))

# ── 9 記憶體守門（操作過之後）────────────────────────────────
print('\n9. 記憶體守門（實際操作過之後）')
# ⚠ 第 1 項只看「啟動時」有沒有載入重量級套件，這不夠。延遲匯入只是把成本
#   往後挪，沒有避免它——Python 不會卸載模組，所以只要有任何一條**請求路徑**
#   碰到 torch，第一個使用者一點下去就永久付掉，而第 1 項永遠是綠的。
#
#   2026-09-03 實際踩到：/api/import_csv 為了預熱 LSTM buffer 呼叫
#   _inference()，把 torch → sklearn → scipy 全拉進來，RSS 62 → 348 MB，
#   而那個預測值前端根本不渲染。第 1 項當時是綠的。
#
#   所以這一項要在**操作過**之後才檢查。
try:
    import ctypes
    from ctypes import wintypes

    class _PMC(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] \
            + [(nm, ctypes.c_size_t) for nm in
               ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
                'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                'PagefileUsage', 'PeakPagefileUsage')]

    _k32 = ctypes.windll.kernel32
    # ⚠ GetCurrentProcess() 回傳偽控制代碼 -1；不設 restype 會被截成 32 位元，
    #   呼叫靜默失敗回 0，量出來全是 0.0 MB（踩過）。
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _gpmi = ctypes.windll.psapi.GetProcessMemoryInfo
    _gpmi.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]

    def _rss_mb():
        s = _PMC()
        s.cb = ctypes.sizeof(s)
        if not _gpmi(_k32.GetCurrentProcess(), ctypes.byref(s), s.cb):
            return None
        return s.WorkingSetSize / 1e6

    rss_before = _rss_mb()
    # 走一遍最容易偷渡重量級套件的路徑：CSV 單檔匯入
    import glob as _glob
    csvs = sorted(_glob.glob(os.path.join(folder, '*.csv')))[:1]
    for _f in csvs:
        with open(_f, 'rb') as _fh:
            c.post('/api/import_csv',
                   files={'file': (os.path.basename(_f), _fh, 'text/csv')})
    # 這兩支是 496 MB 級別的，任何請求路徑都不該把它們拉進常駐行程。
    BANNED = ('torch', 'xgboost', 'onnxruntime')
    got = [m for m in BANNED if m in sys.modules]
    check('CSV 匯入後仍未載入 torch/xgboost', not got,
          ('★ 載入了 ' + ', '.join(got)) if got else '乾淨')
    rss_after = _rss_mb()
    if rss_before and rss_after:
        # ⚠ 這個增量在**完整跑一輪**時會接近 0，因為第 2～4 組已經先載入了
        #   離線腳本（dataset_c → pandas、simulator_check → scipy）。也就是
        #   說它在這裡是個容易誤導的綠燈，真正有效的是上面 torch 那一項。
        #   單獨量常駐核心請用 scratchpad/mem_probe.py（乾淨行程）。
        already = [m for m in ('pandas', 'scipy') if m in sys.modules]
        check('CSV 匯入未再拉進新的重量級套件',
              rss_after - rss_before < 120,
              '%.1f → %.1f MB（+%.1f）%s'
              % (rss_before, rss_after, rss_after - rss_before,
                 '；註：%s 已由前面幾組載入，此增量偏低'
                 % '/'.join(already) if already else ''))
except Exception as e:                                       # noqa: BLE001
    check('記憶體守門（操作後）', False, '%s: %s' % (type(e).__name__, e))

# ── 10 分析模組（子行程隔離）──────────────────────────────────
print('')
print('10. 分析模組（獨立子行程）')
# ⚠ 這一組守的是整個模組化的那條紅線：**核心從不 import 模組的程式碼**。
#   一旦有人為了方便在 module_runner 裡寫 `from modules.covariate import
#   analysis`，pandas 與 scipy 就永久進了常駐行程，60 MB 預算當場作廢，
#   而且不會有任何錯誤訊息——這正是 torch 藏了好幾個月的方式。
import ast as _ast                                            # noqa: E402
import shutil as _shutil                                      # noqa: E402

from core import module_runner as mr                          # noqa: E402

# 模組會寫進資料庫。導到暫存檔，不要碰到現場的 reactor.db。
_moddb = os.path.join(tempfile.gettempdir(), 'reactor_modtest.db')
if os.path.exists(_moddb):
    os.remove(_moddb)
_prev_db = os.environ.get('REACTOR_DB')
os.environ['REACTOR_DB'] = _moddb
try:
    mods = mr.discover()
    ok_mods = [m for m in mods if m.get('ok')]
    bad_mods = [m for m in mods if not m.get('ok')]
    check('探索得到模組', len(ok_mods) >= 2,
          '可用 %d 個：%s' % (len(ok_mods),
                           ', '.join(m['name'] for m in ok_mods)))
    check('沒有壞掉的模組', not bad_mods,
          ('★ ' + '; '.join('%s: %s' % (m.get('name'), m.get('error'))
                            for m in bad_mods)) if bad_mods else '全部可載入')

    # ★ 紅線（動態）：跑一個模組之後，常駐行程不得多出任何套件。
    _before = set(sys.modules)
    _res = mr.run_module('covariate')
    _after = set(sys.modules)
    check('手動執行模組成功', _res.get('ok'),
          'exit=%s %.1fs %s'
          % (_res.get('exit_code'), _res.get('seconds', 0),
             (_res.get('log') or _res.get('error') or '').strip()[:90]))
    _gained = sorted(m for m in (_after - _before)
                     if '.' not in m and not m.startswith('_'))
    check('★ 執行模組不會把它的相依帶進常駐行程', not _gained,
          ('★ 多出了 ' + ', '.join(_gained)) if _gained
          else '子行程跑完，核心的 sys.modules 沒有變動')

    _got = mr.last_result('covariate')
    check('模組結果讀得回來', _got.get('status') == 'ok',
          'status=%s table=%s' % (_got.get('status'), _got.get('table')))
    check('執行紀錄有留下', len(mr.history('covariate', limit=5)) >= 1,
          '%d 筆' % len(mr.history('covariate', limit=5)))

    # ★ 紅線（靜態）：原始碼層級禁止 import 模組的程式碼。
    #   動態檢查只涵蓋「這次真的跑過的那條路徑」，靜態檢查涵蓋全部分支。
    _src = io.open(os.path.join(HERE, 'core', 'module_runner.py'),
                   encoding='utf-8').read()
    _offend = []
    for _n in _ast.walk(_ast.parse(_src)):
        if isinstance(_n, _ast.ImportFrom) and (_n.module or '').startswith('modules'):
            _offend.append('line %d: from %s' % (_n.lineno, _n.module))
        elif isinstance(_n, _ast.Import):
            for _a in _n.names:
                if _a.name.startswith('modules'):
                    _offend.append('line %d: import %s' % (_n.lineno, _a.name))
    check('★ module_runner 原始碼不得 import 模組的程式碼', not _offend,
          ('★ ' + '; '.join(_offend)) if _offend else '只用 subprocess 啟動')

    # 壞掉的模組必須被列出來並帶 error，不是靜默略過——否則沒有人會發現
    # 某個分析其實已經幾個月沒更新了。
    _brokendir = os.path.join(mr.MODULES_DIR, '_systest_broken')
    os.makedirs(_brokendir, exist_ok=True)
    try:
        with io.open(os.path.join(_brokendir, 'module.json'), 'w',
                     encoding='utf-8') as _fh:
            _fh.write('{"name": "_systest_broken", "version": "0", '
                      '"title": "壞的", "entry": "nope.py"}')
        _found = [m for m in mr.discover() if m.get('name') == '_systest_broken']
        check('壞掉的模組會被列出並帶 error',
              bool(_found) and not _found[0].get('ok') and _found[0].get('error'),
              _found[0].get('error') if _found else '★ 整個被略過了')
    finally:
        _shutil.rmtree(_brokendir, ignore_errors=True)

    # API
    for _url, _want in (('/api/modules', 200),
                        ('/api/modules/covariate/result', 200),
                        ('/api/modules/covariate/runs', 200),
                        ('/api/modules/does_not_exist/result', 404)):
        _r = c.get(_url)
        check('GET %s' % _url, _r.status_code == _want,
              'HTTP %d（應為 %d）' % (_r.status_code, _want))
except Exception as _e:                                      # noqa: BLE001
    check('分析模組', False, '%s: %s' % (type(_e).__name__, _e))
finally:
    if _prev_db is None:
        os.environ.pop('REACTOR_DB', None)
    else:
        os.environ['REACTOR_DB'] = _prev_db

# ── 11 sample 表（durable 儲存）──────────────────────────────
print('')
print('11. sample 表（感測資料的 durable 儲存）')
# ⚠ 這一組守兩件事：
#   1 **重啟不掉資料。** 在此之前感測資料只存在記憶體，後端一重開監控頁、
#     批次分析、CH4 預測全部歸零，而畫面上看不出是「沒資料」還是「重開過」。
#   2 **記憶體不隨時間長大。** 實測每筆記錄在記憶體佔 517 bytes，一年的
#     一分鐘取樣＝525,600 筆＝259 MB，而這台的常駐預算是 60 MB。所以啟動
#     只還原最近 N 筆，不是全部——這一項就是在守那個上限真的有作用。
from core import sample_store as ss                            # noqa: E402
from core.data_store import sensor_records                     # noqa: E402

_sdb = os.path.join(tempfile.gettempdir(), 'reactor_sampletest.db')
if os.path.exists(_sdb):
    os.remove(_sdb)
_prev_sdb = os.environ.get('REACTOR_DB')
os.environ['REACTOR_DB'] = _sdb
try:
    _csvs = sorted(glob.glob(os.path.join(folder, '*.csv')))[:2]
    _n_imported = 0
    for _f in _csvs:
        with open(_f, 'rb') as _fh:
            _r = c.post('/api/import_csv',
                        files={'file': (os.path.basename(_f), _fh, 'text/csv')})
        _n_imported += (_r.json() or {}).get('imported', 0)

    _st = ss.stats()
    check('匯入會寫進 sample 表', _st['n_samples'] > 0,
          '表內 %d 筆（%s → %s）'
          % (_st['n_samples'], _st['first_ts'], _st['last_ts']))

    # ★ 重匯同一個檔不得產生重複列（ts 是主鍵 + INSERT OR IGNORE）
    _before = _st['n_samples']
    with open(_csvs[0], 'rb') as _fh:
        c.post('/api/import_csv',
               files={'file': (os.path.basename(_csvs[0]), _fh, 'text/csv')})
    _after = ss.stats()['n_samples']
    check('★ 重匯同一個檔不會產生重複列', _after == _before,
          '%d → %d 筆' % (_before, _after))

    # ★ 重啟還原：清空記憶體，用 load_recent 模擬 lifespan 那段
    _restored = ss.load_recent()
    check('★ 重啟後還原得回來', len(_restored) == min(_before, ss.DEFAULT_MEMORY_LIMIT),
          '還原 %d 筆（表內 %d）' % (len(_restored), _before))

    # ★ 記憶體上限真的有作用——不設限的話一年份會吃掉 259 MB
    _capped = ss.load_recent(limit=50)
    check('★ 還原有筆數上限', len(_capped) == min(50, _before),
          '要 50 筆，拿到 %d 筆' % len(_capped))

    # 還原的順序必須由舊到新：EMA、相位判定、切段都假設時間遞增
    _ts = [r['timestamp'] for r in _capped]
    check('★ 還原的順序是由舊到新', _ts == sorted(_ts),
          '首 %s → 末 %s' % (_ts[0][:19], _ts[-1][:19]) if _ts else '無資料')

    # 欄位不得在還原時靜默掉——架構文件 §6 只列五欄，實際記錄有十二欄
    _need = ('timestamp', 'orp', 'orp_raw', 'orp_cleaned', 'is_anomaly',
             'pressure', 'ph', 'temp', 'mixer_pressure', 'co2_pct',
             'ch4_pct', 'note')
    _miss = [k for k in _need if _capped and k not in _capped[0]]
    check('★ 還原不掉欄位', not _miss,
          ('★ 少了 ' + ', '.join(_miss)) if _miss else '十二欄齊全')

    # 時間窗查詢不得改動記憶體
    _mem_before = len(sensor_records)
    _w = ss.load_window(_st['first_ts'], _st['last_ts'])
    check('時間窗查詢不動記憶體', len(sensor_records) == _mem_before,
          '查到 %d 筆，記憶體仍為 %d 筆' % (len(_w), len(sensor_records)))

    for _url, _want in (('/api/samples', 200), ('/api/samples/window', 422)):
        _r = c.get(_url)
        check('GET %s' % _url, _r.status_code == _want,
              'HTTP %d（應為 %d）' % (_r.status_code, _want))
except Exception as _e:                                      # noqa: BLE001
    check('sample 表', False, '%s: %s' % (type(_e).__name__, _e))
finally:
    if _prev_sdb is None:
        os.environ.pop('REACTOR_DB', None)
    else:
        os.environ['REACTOR_DB'] = _prev_sdb

# ── 12 CH4 即時路徑（不得依賴 scipy／xgboost）──────────────────
print('')
print('12. CH4 即時路徑')
# ⚠ CH4 這條路徑上曾經有**兩個**重相依，而且都躲在「延遲 import」後面：
#   · xgboost（單獨 +119.5 MB）——在核心的背景**執行緒**裡跑。執行緒不是
#     子行程，所以只要有人開過一次 CH4 面板就永久留著。已搬成模組。
#   · scipy.signal.find_peaks（numpy 之後再 +69.6 MB，比整個預算還大）——
#     寫在 detect_vents 函式裡，但 detect_vents 在**即時請求路徑**上。
#     已改成純 numpy 實作。
#
#   兩個都不會報錯、都不影響功能、都是慢慢把常駐行程撐大。這一組守它們。
try:
    _before = set(sys.modules)
    _r = c.get('/api/ch4_prediction')
    _gained = [m for m in ('scipy', 'xgboost', 'torch', 'sklearn')
               if m not in _before and m in sys.modules]
    check('GET /api/ch4_prediction', _r.status_code == 200,
          'HTTP %d' % _r.status_code)
    check('★ 即時預測不得拉進 scipy／xgboost', not _gained,
          ('★ 多了 ' + ', '.join(_gained)) if _gained else '只用 numpy')

    _j = _r.json()
    check('回應含特徵歸因欄位', 'feature_selection' in _j,
          'status=%s' % (_j.get('feature_selection') or {}).get('status'))

    # ★ 純 numpy 的 find_peaks 必須與 scipy **逐點相同**。這不是「差不多的
    #   實作」——峰的位置決定循環怎麼切，切錯不會報錯，只會讓所有下游數字
    #   靜默偏掉。開發機有裝 scipy 就在這裡重跑比對；監控電腦沒裝就跳過。
    try:
        from scipy.signal import find_peaks as _sp_find_peaks
    except ImportError:
        _sp_find_peaks = None
    if _sp_find_peaks is None:
        check('★ find_peaks 與 scipy 一致', True, '本機未裝 scipy，跳過比對')
    else:
        import numpy as _np
        from core.ch4_realtime import find_peaks_np as _np_find_peaks
        _rng = _np.random.default_rng(12345)
        _bad = _npk = 0
        for _t in range(400):
            _n = int(_rng.integers(3, 300))
            _kind = _t % 4
            if _kind == 0:
                _a = _rng.normal(0, 1, _n)                     # 連續
            elif _kind == 1:
                _a = _np.round(_rng.normal(0, 1, _n))          # 大量平台
            elif _kind == 2:
                _a = _np.round(_rng.normal(0, 3, _n), 1)       # 少量平台
            else:
                _a = _np.full(_n, 5.0)                         # 幾乎全平
                _a[_rng.integers(0, _n, 3)] = 9.0
            _prom = float(_rng.choice([0.3, 1.0, 5.0]))
            _dist = int(_rng.integers(1, 30)) if _t % 2 else None
            _ref, _ = _sp_find_peaks(_a, prominence=_prom, distance=_dist)
            _got = _np_find_peaks(_a, _prom, _dist)
            _npk += len(_ref)
            if list(_ref) != list(_got):
                _bad += 1
        check('★ find_peaks 與 scipy 逐點一致', _bad == 0,
              '400 組隨機訊號、%d 個峰，不一致 %d 組' % (_npk, _bad))

    # ch4_attribution 模組要跑得起來（樣本不足也算成功——那是正常狀態）
    _res = mr.run_module('ch4_attribution')
    check('ch4_attribution 模組可執行', _res.get('ok'),
          'exit=%s %s' % (_res.get('exit_code'),
                          (_res.get('log') or _res.get('error') or '').strip()[:80]))
except Exception as _e:                                      # noqa: BLE001
    check('CH4 即時路徑', False, '%s: %s' % (type(_e).__name__, _e))

# ── 總結 ────────────────────────────────────────────────────
print('\n' + '=' * 64)
print('通過 %d 項，失敗 %d 項' % (len(PASS), len(FAIL)))
if FAIL:
    print('\n失敗的項目：')
    for f in FAIL:
        print('   ★', f)
    sys.exit(1)
print('全部通過')
