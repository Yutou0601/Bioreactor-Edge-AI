
# -*- coding: utf-8 -*-
"""cycle 表的建立、寫入與查詢。

⚠ 常駐核心的一部分：只准 sqlite3（標準函式庫）與 numpy。
  CSV 讀取刻意不用 pandas——一個 62 MB 的相依，只為了 split(',')。

資料表設計見 docs/system/系統重構架構_2026-08-31.md §6。
關鍵欄位是 calib_ver：校準常數換版時，舊資料仍能追溯它當初用的是哪一版。
"""
import json
import os
import sqlite3
from datetime import datetime

import numpy as np

from core import cycle_estimator as ce

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get('REACTOR_DB') or os.path.join(HERE, 'reactor.db')
CALIB_PATH = os.path.join(HERE, 'calibration.json')

# 欄位索引：與 multivariate_increments.py 同步，勿單方面修改。
I_P_REACTOR = 11      # 反應器壓力
I_ORP = 7             # ORP（記錄只存絕對值，真值為負）
I_PH = 9              # pH
WASH_PER_DAY = 6      # 每日循環起始超過此數視為洗管線日

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycle (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source      TEXT,
  ts_start    TEXT,
  ts_end      TEXT,
  n_samples   INTEGER,
  duration_hr REAL,
  amplitude   REAL,
  curvature   REAL,
  screened    INTEGER,
  k_hat       REAL,
  rb_hat      REAL,
  rb          REAL,
  peq         REAL,
  amp_fit     REAL,
  resid_sd    REAL,
  calib_ver   TEXT,
  UNIQUE(source, ts_start)
);
CREATE INDEX IF NOT EXISTS ix_cycle_start ON cycle(ts_start);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def load_calibration():
    """讀離線模組產生的校準常數。沒有就回 None，不擋流程。"""
    if not os.path.exists(CALIB_PATH):
        return None
    try:
        with open(CALIB_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_one(path):
    """讀 BTP_Sensor_log CSV，回傳 (timestamps, hours, pressure)。

    ⚠ 這種檔**沒有表頭**，是位置式欄位：

        2026,4,27,0,0,21,_,556,2.51,7.21,30.0,0.95,0.0,0.33
        年   月 日 時 分 秒 _ ORP  ?   pH   溫度  壓力 CO2 CH4

    欄位索引取自 multivariate_increments.py（所有分析共用的載入器），
    不可自行推測：I_P_REACTOR=11、I_ORP=7、I_PH=9。
    ⚠ 欄 12/13 是氣體分析儀的 CO2/CH4，99.98% 是無效拖尾，不是 ORP/pH。

    ⚠ 不用 pandas：一個 62 MB 的相依，只為了 split(',')。
    """
    ts, pres = [], []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            p = line.strip().split(',')
            if len(p) < 14:
                continue
            try:
                ts.append(datetime(int(p[0]), int(p[1]), int(p[2]),
                                   int(p[3]), int(p[4]), int(float(p[5]))))
                pres.append(float(p[I_P_REACTOR]))
            except (ValueError, IndexError):
                continue
    if not ts:
        return None
    return ts, pres


def read_series(paths):
    """讀多個 CSV 並**合併排序**成一條連續序列。

    ⚠ 不可逐檔處理。BTP_Sensor_log 是一天一檔，而循環中位長 10.2 小時，
      大多會跨過午夜；逐檔切段會把跨日的一段攔腰砍斷，時長與振幅都錯。
      離線的 load4() 也是整個資料夾讀完排序才切——兩邊必須一致。
    """
    ts, pres = [], []
    for path in paths:
        got = _read_one(path)
        if got is None:
            continue
        ts.extend(got[0])
        pres.extend(got[1])
    if len(ts) < 60:
        return None
    order = sorted(range(len(ts)), key=lambda i: ts[i])
    ts = [ts[i] for i in order]
    pres = np.asarray([pres[i] for i in order], dtype=float)
    t0 = ts[0]
    hours = np.array([(x - t0).total_seconds() / 3600.0 for x in ts])
    return ts, hours, pres


def _wash_days(ts, cycles):
    """洗管線日：當天的循環起始次數超過 WASH_PER_DAY 即視為清洗。

    那些日子反覆循環是為了洗管路，不是正常運轉，估出來的速率沒有意義。
    對齊 clean_and_form.seg_clean 的判定。
    """
    from collections import Counter
    per_day = Counter(ts[a].date() for a, _ in cycles)
    return {d for d, n in per_day.items() if n > WASH_PER_DAY}


def ingest_paths(paths, source, con=None):
    """讀一批 CSV（同一個來源／期間），切段、估計、寫入 cycle 表。"""
    got = read_series(paths)
    if got is None:
        return {'source': source, 'error': '資料不足'}
    ts, hours, pressure = got
    calib = load_calibration()
    cver = (calib or {}).get('calibrated_at')

    own = con is None
    con = con or connect()
    n_seg = n_scr = n_new = n_wash = 0
    try:
        cycles = ce.segment(hours, pressure)
        wash = _wash_days(ts, cycles)
        for a, b in cycles:
            if ts[a].date() in wash:
                n_wash += 1
                continue
            n_seg += 1
            row = ce.estimate_cycle(hours[a:b + 1], pressure[a:b + 1])
            if row is None:
                continue
            n_scr += int(row['screened'])
            rb = (ce.apply_calibration(row.get('rb'), calib)
                  if row['screened'] else None)
            cur = con.execute(
                'INSERT OR IGNORE INTO cycle (source, ts_start, ts_end,'
                ' n_samples, duration_hr, amplitude, curvature, screened,'
                ' k_hat, rb_hat, rb, peq, amp_fit, resid_sd, calib_ver)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (source, ts[a].isoformat(sep=' '), ts[b].isoformat(sep=' '),
                 row['n_samples'], row['duration_hr'], row['amplitude'],
                 row['curvature'], int(row['screened']),
                 row.get('k'), row.get('rb'), rb, row.get('peq'),
                 row.get('amp'), row.get('sd'), cver))
            n_new += cur.rowcount
        con.commit()
    finally:
        if own:
            con.close()
    return {'source': source, 'segments': n_seg, 'screened': n_scr,
            'inserted': n_new, 'wash_skipped': n_wash}


def ingest_folder(folder, source=None, con=None):
    """一個資料夾＝一個期間。這是正確的處理單位。"""
    import glob
    paths = sorted(glob.glob(os.path.join(folder, '*.csv')))
    return ingest_paths(paths, source or os.path.basename(folder), con=con)


def list_cycles(limit=500, screened_only=False, con=None):
    own = con is None
    con = con or connect()
    try:
        q = 'SELECT * FROM cycle'
        if screened_only:
            q += ' WHERE screened = 1'
        q += ' ORDER BY ts_start DESC LIMIT ?'
        return [dict(r) for r in con.execute(q, (int(limit),))]
    finally:
        if own:
            con.close()


def median_ci(vals, conf=0.95):
    """中位數的無分布 95% 區間（次序統計量法）。

    ⚠ 為什麼要有這個：單一循環的 r_b 幾乎沒有資訊量——實測 179 段裡有
      17.9% 算出**負的**生物速率（物理上不可能），單段範圍 −0.266~0.038。
      r_b 只有作為**多段的中位數**才有意義，而精度強烈取決於段數：
          N=1 → ±714%    N=10 → ±56%    N=50 → ±13%    N=179 → ±6%
      介面若只顯示中位數而不顯示 N 與精度，累積 8 段時看起來會跟 179 段
      一樣有自信。這個函式讓前端可以把「還不能用」講出來。

    用次序統計量而非 bootstrap：精確、純標準庫、O(n log n)，不必為了一個
    數字在常駐核心裡跑 2000 次重抽樣。
    """
    from math import comb
    xs = sorted(float(v) for v in vals)
    n = len(xs)
    if n == 0:
        return None, None
    if n < 6:            # 太少，次序統計量給不出有意義的區間
        return xs[0], xs[-1]
    alpha = 1.0 - conf
    # 找最大的 k 使得 P(X<k) + P(X>n-k) <= alpha，X~Bin(n, 0.5)
    cum = 0.0
    k = 0
    for i in range(n + 1):
        p = comb(n, i) / (2.0 ** n)
        if 2 * (cum + p) > alpha:
            break
        cum += p
        k = i + 1
    k = max(k, 1)
    return xs[k - 1], xs[n - k]


def summary(con=None):
    """目前的聚合速率——論文報的就是這個統計量（中位數）。"""
    own = con is None
    con = con or connect()
    try:
        rows = con.execute(
            'SELECT rb_hat, rb FROM cycle WHERE screened = 1'
            ' AND rb_hat IS NOT NULL').fetchall()
        n_all = con.execute('SELECT COUNT(*) FROM cycle').fetchone()[0]
    finally:
        if own:
            con.close()
    calib = load_calibration()
    if not rows:
        return {'n_cycles': n_all, 'n_screened': 0, 'calibration': calib}
    raw = np.array([r['rb_hat'] for r in rows], dtype=float)
    cal = np.array([r['rb'] for r in rows if r['rb'] is not None],
                   dtype=float)
    med = float(np.median(cal)) if len(cal) else float(np.median(raw))
    lo, hi = median_ci(cal if len(cal) else raw)
    # ⚠ 精度是「這批段數的中位數精度」，不是速率本身的穩定度，也不是單一
    #   循環的誤差。單段根本不可用（17.9% 為負）——見 median_ci 的說明。
    prec = (hi - lo) / 2.0 / abs(med) * 100.0 if med and lo is not None else None
    return {
        'n_cycles': n_all,
        'n_screened': len(rows),
        'median_rb_hat': float(np.median(raw)),
        'median_rb': float(np.median(cal)) if len(cal) else None,
        'negative_fraction': float((raw < 0).mean()),
        # 中位數的 95% 區間與相對精度，讓前端能顯示「累積幾段、目前多準」
        'median_ci': [lo, hi] if lo is not None else None,
        'precision_pct': round(prec, 1) if prec is not None else None,
        # 經驗門檻：±30% 以上只能當趨勢看，±15% 以內才適合引用
        'usability': ('unusable' if prec is None or prec > 30 else
                      'indicative' if prec > 15 else 'usable'),
        'calibration': calib,
    }
