
# -*- coding: utf-8 -*-
"""系統測試：一次跑完，任何一項紅了就是有東西壞了。

    python system_test.py

九項檢查，由內而外：

  1 記憶體守門  常駐核心不得載入 torch/pandas/sklearn/scipy/xgboost
  2 估計器一致  線上實作 vs 離線腳本，逐段比對 (曲率, k, r_b)
  3 切段正確    必須以資料夾為單位；逐檔處理會把跨午夜的循環砍斷
  4 資料庫      建表、匯入、去重（同一段不會重複寫入）
  5 API         /api/health、/api/rate、/api/cycles、/api/ingest_folder
  6 前端        後端有沒有把 dist/ 供應出去
  7 校準        calibration.json 有沒有被正確套用
  8 批次排程    自動開始/結束的判定；預設關閉的守門
  9 記憶體守門  **操作過之後**再檢查一次——第 1 項擋不住請求路徑偷渡

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
check('啟動不載入重量級套件', not loaded,
      ('★ 載入了 ' + ', '.join(loaded)) if loaded else 'numpy only')

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
    for sub in ('/rate', '/report', '/experiment', '/import'):
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

# ── 總結 ────────────────────────────────────────────────────
print('\n' + '=' * 64)
print('通過 %d 項，失敗 %d 項' % (len(PASS), len(FAIL)))
if FAIL:
    print('\n失敗的項目：')
    for f in FAIL:
        print('   ★', f)
    sys.exit(1)
print('全部通過')
