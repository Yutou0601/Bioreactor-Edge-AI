# -*- coding: utf-8 -*-
"""串流資料 → cycle 表：論文 Algorithm 1 跟著資料一起跑。

資料夾匯入（cycle_store.ingest_folder）是「一整批讀完再切」；串流是資料一分鐘
一分鐘進來，所以這裡每隔幾分鐘把最近一段 sample 重新切一次，只寫**新完成**的段。

⚠ 只寫已完成的段——也就是後面已經接著一次補氣（或取樣中斷）的段。最後那段
  還在下降中，cycle 表以 (source, ts_start) 為唯一鍵且 INSERT OR IGNORE，
  半截寫進去就永遠是半截。進行中那段只在 current() 給暫定估計，不入表。

⚠ 只准 numpy 與標準函式庫（與 cycle_estimator 相同的規矩）。
"""
import threading
import time
from datetime import datetime, timedelta

import numpy as np

from core import cycle_estimator as ce
from core import cycle_store as cs
from core import sample_store

_lock = threading.Lock()
_last_sync = {}          # station -> time.monotonic()
WASH_LOOKBACK_HR = 24    # 判洗管線日要看當天全部的段，所以多往回讀一天


def _source(station):
    return 'stream:%s' % (station or 'default')


def _pressure_rows(station, since):
    """(ts 字串, 壓力) 由舊到新。

    ⚠ 優先讀 raw_sample，不讀 sample。sample 要等 ORP 前處理輸出才有那一列，
      而 ORP 突波期間處理器會把最多 15 分鐘的點連同**壓力**一起緩衝住。若在
      那時候同步，剛完成的那段就少了幾分鐘的壓力——實測同一份 13 天資料，
      起迄完全相同的 46 段裡有段曲率差了 12%、篩選結果翻掉一段。壓力本來
      就不經 ORP 前處理，收到就能用。
      raw_sample 沒有這個站台（例如資料是手動匯入的）才退回 sample。
    """
    from core import ingest
    con = ingest.connect()
    try:
        rows = con.execute(
            'SELECT ts, pressure FROM raw_sample WHERE station = ? AND ts >= ?'
            ' ORDER BY ts', (station, since)).fetchall()
        if rows:
            return [(r['ts'], r['pressure']) for r in rows]
    finally:
        con.close()
    return [(r['timestamp'], r.get('pressure'))
            for r in sample_store.load_window(since)]


def _latest_ts(station):
    """這個站台最新一筆的時間戳（raw_sample 優先，與 _pressure_rows 一致）。"""
    from core import ingest
    con = ingest.connect()
    try:
        r = con.execute('SELECT MAX(ts) FROM raw_sample WHERE station = ?',
                        (station,)).fetchone()
        if r and r[0]:
            return r[0]
    finally:
        con.close()
    return sample_store.stats()['last_ts']


def _series(since, station='default'):
    """since 之後的 (ts, hours, pressure)。壓力缺值的列丟掉。"""
    ts, p = [], []
    for t, pr in _pressure_rows(station, since):
        if pr is None or not t:
            continue
        try:
            ts.append(datetime.fromisoformat(t))
        except ValueError:
            continue
        p.append(float(pr))
    if len(ts) < 2:
        return None
    t0 = ts[0]
    hours = np.array([(x - t0).total_seconds() / 3600.0 for x in ts])
    return ts, hours, np.asarray(p, dtype=float)


def _open_start(hours, pressure):
    """最後一段（進行中）的起點索引。判定規則與 ce.segment() 逐行相同。"""
    h, p = hours, pressure
    valley, start = p[0], 0
    for i in range(1, len(p)):
        if h[i] - h[i - 1] > ce.GAP_HR:
            start, valley = i, p[i]
            continue
        if p[i] - valley > ce.REFILL_RISE:
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    return start


def _last_end(station, con):
    r = con.execute('SELECT MAX(ts_end) FROM cycle WHERE source = ?',
                    (_source(station),)).fetchone()
    return datetime.fromisoformat(r[0]) if r and r[0] else None


def sync(station='default'):
    """把新完成的段寫進 cycle 表。回傳摘要。"""
    with _lock:
        con = cs.connect()
        try:
            last_end = _last_end(station, con)
            if last_end is not None:
                since = (last_end - timedelta(hours=WASH_LOOKBACK_HR)).isoformat(sep=' ')
            else:
                # ⚠ 第一次從這個站台的**第一筆**開始，不是「最近幾天」。Jetson 剛
                #   上線時上傳程式會一口氣補送好幾週的舊檔；只往回看 7 天的話，
                #   更早的循環永遠不會被切（實測 13 天資料只切到後 23 段，少一半）。
                if not _latest_ts(station):
                    return {'source': _source(station), 'error': '沒有資料'}
                since = ''
            got = _series(since, station)
            if got is None:
                return {'source': _source(station), 'error': '資料不足'}
            ts, hours, p = got
            segs = ce.segment(hours, p)
            last = len(p) - 1
            done = [(a, b) for a, b in segs if b < last]       # 後面已有補氣／中斷
            if last_end is not None:
                new = [(a, b) for a, b in done if ts[a] > last_end]
            else:
                # 第一次：視窗起點那段可能是從中間切進來的，不知道真正起點，不寫。
                new = [(a, b) for a, b in done if a > 0]
            res = cs.store_segments(ts, hours, p, new, _source(station),
                                    con=con, wash_from=segs, exact_time=True)
            res['window_start'] = ts[0].isoformat(sep=' ')
            return res
        finally:
            con.close()
            _last_sync[station] = time.monotonic()


def maybe_sync(station='default', min_interval=300):
    """距上次同步超過 min_interval 秒才同步。給接收端每批呼叫用。"""
    t = _last_sync.get(station)
    if t is not None and time.monotonic() - t < min_interval:
        return None
    return sync(station)


RECENT_HR = 3.0      # 「目前速率」看最近幾小時（10 分鐘視窗量不到東西，見 descent_report）


def _stoich(seg_h, seg_p, est, temp_c=30.0):
    """由本段壓降推 CO2 消耗與 CH4 產量。全部是**上限**，除了 bio_* 兩項。

    CO2 + 4H2 → CH4 + 2H2O(液)：氣相淨少 4 mol／每 mol CO2。所以
        CO2 消耗 = CH4 產量 ≤ 淨壓降 / 4
    ⚠ 是上限不是等號：壓降還有物理項（溶解、論文的 A·e^{-kt}），那部分消耗
      氣體卻不產 CH4。實測三批排氣對帳 CH4/壓降 = 0.17~0.22（上限 0.25）。
    ⚠ 濃度上限用分壓比，頭空體積自己消掉；換成 mmol 才需要體積，而頭空
      1.00 L 的四分位是 0.60~2.14（descent_report.HEADSPACE_L），mmol 只能
      當量級看。
    bio_*：用 Algorithm 1 的 r_b（只有通過曲率篩選才有）換算的生物份額速率。
    """
    from core import descent_report as dr
    keep = seg_h >= ce.SKIP_MIN            # 與 Algorithm 1 相同：掐掉補氣本身那幾分鐘
    if keep.sum() < 2:
        return None
    seg_h, seg_p = seg_h[keep], seg_p[keep]
    drop = float(seg_p[0] - seg_p[-1])
    p_abs = float(seg_p[-1]) + dr.ATM
    up = max(drop, 0.0) / 4.0
    recent = seg_h >= seg_h[-1] - RECENT_HR
    slope, r2 = dr._slope(seg_h[recent], seg_p[recent]) if recent.sum() >= 3 else (None, None)
    recent_drop = float(seg_p[recent][0] - seg_p[recent][-1]) if recent.sum() >= 2 else 0.0
    mm = lambda kgf: None if kgf is None else round(
        1000.0 * dr.moles_from_pressure(kgf, dr.HEADSPACE_L, temp_c), 3)
    out = {
        # 淨降從補氣後 SKIP_MIN 起算，不是從補氣瞬間；畫面要把起算值一起列出，
        # 否則「起點 − 目前 ≠ 淨降」會讓人以為算錯。
        'p_from': float(seg_p[0]),
        'net_drop_kgf': round(drop, 4),
        'co2_consumed_upper_kgf': round(up, 5),
        'ch4_frac_upper': round(up / p_abs, 4) if p_abs > 0 else None,
        'co2_consumed_upper_mmol': mm(up),
        'rate_upper_kgf_hr': None if slope is None else round(slope / 4.0, 5),
        'rate_upper_mmol_hr': None if slope is None else mm(slope / 4.0),
        'recent_hr': RECENT_HR,
        # 最近 3 小時壓力變化不到 3 個量化階時，斜率主要是量化雜訊
        'recent_below_quantum': abs(recent_drop) < 3 * dr.QUANT,
        'headspace_l': dr.HEADSPACE_L,
        'measured_ratio_range': [0.17, 0.22],
        'bio_rate_kgf_hr': None, 'bio_rate_mmol_hr': None,
    }
    if est and est.get('screened') and est.get('rb') is not None:
        out['bio_rate_kgf_hr'] = round(est['rb'] / 4.0, 6)
        out['bio_rate_mmol_hr'] = mm(est['rb'] / 4.0)
    return out


def current(station='default', lookback_hr=48):
    """進行中那段的暫定狀態。⚠ 數字會隨時間變，不入表。"""
    latest = _latest_ts(station)
    if not latest:
        return None
    since = datetime.fromisoformat(latest) - timedelta(hours=lookback_hr)
    got = _series(since.isoformat(sep=' '), station)
    if got is None:
        return None
    ts, hours, p = got
    a = _open_start(hours, p)
    seg_h = np.array([(x - ts[a]).total_seconds() / 3600.0 for x in ts[a:]])
    seg_p = p[a:]
    out = {
        'ts_start': ts[a].isoformat(sep=' '),
        'ts_last': ts[-1].isoformat(sep=' '),
        'duration_hr': round(float(seg_h[-1]), 3),
        'n_samples': int(len(seg_p)),
        'p_start': float(seg_p[0]), 'p_now': float(seg_p[-1]),
        'drop': round(float(seg_p[0] - seg_p.min()), 4),
        'provisional': True,
        'estimate': None,
        'why_no_estimate': None,
        'stoich': _stoich(seg_h, seg_p, None),   # 上限一開始就能算；r_b 要等滿 4 小時
    }
    if seg_h[-1] < ce.MIN_HR:
        out['why_no_estimate'] = '這段才 %.1f 小時，未滿 %.0f 小時不估計' % (
            seg_h[-1], ce.MIN_HR)
        return out
    est = ce.estimate_cycle(seg_h, seg_p)
    if est is None:
        out['why_no_estimate'] = '有效點數不足'
        return out
    out['curvature'] = est.get('curvature')
    out['screened'] = est.get('screened')
    out['stoich'] = _stoich(seg_h, seg_p, est)
    if not est.get('screened'):
        out['why_no_estimate'] = ('曲率 %.2f 未達 %.2f：目前這段太直，物理與生物'
                                  '兩項分不開（論文 Algorithm 1 第 2 行）'
                                  % (est.get('curvature') or float('nan'), ce.CURV_MIN))
        return out
    out['estimate'] = {k: est.get(k) for k in ('k', 'rb', 'peq', 'amp', 'sd')}
    return out
