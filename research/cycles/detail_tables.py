
# -*- coding: utf-8 -*-
"""產生 2026-09-13 日報的全部明細表（重跑一次，數字不手抄）。

⚠ 報表裡的每一個數字都由本檔輸出，不從先前的報告複製。先前已經因為手抄
  而在別處出過錯（份額 38% vs 37%±1%），明細表數量更多，手抄必錯。

輸出：純文字表，直接貼進 markdown 的 ``` 區塊。

    python detail_tables.py            全部
    python detail_tables.py A C        只要指定的表
"""
import datetime as dt
import glob
import os
import sys
from collections import Counter, defaultdict

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))

ATM = 1.033
QUANT = 0.01
VHEAD = 1.00          # 頭空（總容積 1.99 L 的約一半，由兩支壓力計反推）
R_GAS = 8.314462618
KGF_PA = 98066.5

TAU_DIR = '202607至08最新循環研究'
AUTO_DIR = '0825-0831_氫氣不夠暫停進氣__自動化測試'

BATCHES = [
    ('tau1', 1, dt.date(2026, 7, 22), dt.date(2026, 7, 26)),
    ('tau5', 5, dt.date(2026, 7, 27), dt.date(2026, 7, 29)),
    ('tau10', 10, dt.date(2026, 7, 30), dt.date(2026, 8, 3)),
]


def load(folder):
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data', folder)
    got = read_series_full(sorted(glob.glob(os.path.join(d, '*.csv'))))
    if got is None:
        raise SystemExit('讀不到：%s' % d)
    ts, h, p, temp, co2, ch4 = got
    f = lambda v: np.array([x if x is not None else 0.0 for x in v])
    return ts, np.asarray(h), np.asarray(p), f(co2), f(ch4)


def descents(h, p, min_pts=3):
    """以補氣（單步跳升 > 0.03）為界切下降段。

    ⚠ 消耗量用「段首 − 段尾」，不可用所有負差加總——感測器 ±0.01 的抖動
      一小時就會累出 0.11，而實測速率只有 0.03。
    """
    segs, valley, start = [], p[0], 0
    for i in range(1, len(p)):
        if h[i] - h[i - 1] > 1.0 or p[i] - valley > 0.03:
            if i - 1 > start:
                segs.append((start, i - 1))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    segs.append((start, len(p) - 1))
    return [(s, e) for s, e in segs if e > s + min_pts and p[s] > p[e]]


def fit(t, y):
    """最小平方斜率與 R²（下降為正）。"""
    if len(t) < 3 or t[-1] == t[0]:
        return None, None
    A = np.vstack([t, np.ones_like(t)]).T
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ c
    ss = float(r @ r)
    st = float(((y - y.mean()) ** 2).sum())
    return -float(c[0]), (None if st <= 0 else 1 - ss / st)


def sub(ts, h, p, co2, ch4, d0, d1):
    m = np.array([d0 <= t.date() <= d1 for t in ts])
    ix = np.flatnonzero(m)
    return ([ts[i] for i in ix], h[ix] - h[ix[0]], p[ix], co2[ix], ch4[ix])


def ml(dp):
    return dp * KGF_PA * VHEAD * 1e-3 / (R_GAS * 303.15) * 22400


# ══════════════════════════════════════════════════════════════════
def table_A():
    print('【表 A】τ=10 批次：每一段下降的完整明細')
    print()
    ts, h, p, co2, ch4 = load(TAU_DIR)
    t2, h2, p2, c2, m2 = sub(ts, h, p, co2, ch4, *BATCHES[2][2:])
    segs = descents(h2, p2)
    print('  #  起始時刻          結束時刻          時長   起壓   迄壓   總降    '
          '平均速率   斜率     R²    每小時降  筆數  判定')
    print('  ' + '-' * 116)
    for k, (s, e) in enumerate(segs, 1):
        t = h2[s:e + 1] - h2[s]
        y = p2[s:e + 1]
        sl, r2 = fit(t, y)
        dur = float(t[-1])
        drop = float(y[0] - y[-1])
        kind = '自動循環' if (5.0 <= dur <= 8.5 and 0.20 <= drop <= 0.30) else '★人工排氣'
        print('  %2d  %s  %s %5.1f  %.2f  %.2f  %6.3f  %8.4f  %7.4f  %.3f  %8.4f  %4d  %s'
              % (k, t2[s].strftime('%m-%d %H:%M'), t2[e].strftime('%m-%d %H:%M'),
                 dur, y[0], y[-1], drop, drop / dur, sl, r2, drop / dur,
                 e - s + 1, kind))
    reg = [(s, e) for s, e in segs
           if 5.0 <= h2[e] - h2[s] <= 8.5 and 0.20 <= p2[s] - p2[e] <= 0.30]
    amp = np.array([p2[s] - p2[e] for s, e in reg])
    dur = np.array([h2[e] - h2[s] for s, e in reg])
    print('  ' + '-' * 116)
    print('  自動循環 %d 段：降幅 %.3f±%.3f　時長 %.2f±%.2f hr　速率 %.4f±%.4f'
          % (len(reg), amp.mean(), amp.std(ddof=1), dur.mean(), dur.std(ddof=1),
             (amp / dur).mean(), (amp / dur).std(ddof=1)))


def table_B():
    print('【表 B】循環泵：小時內逐分鐘的平均壓降（三批對照）')
    print()
    ts, h, p, co2, ch4 = load(TAU_DIR)
    prof = {}
    for nm, tau, d0, d1 in BATCHES:
        t2, h2, p2, _, _ = sub(ts, h, p, co2, ch4, d0, d1)
        by = [[] for _ in range(60)]
        for j in range(1, len(t2)):
            dtr = h2[j] - h2[j - 1]
            if not (0.008 < dtr < 0.03) or p2[j] - p2[j - 1] > 0.03:
                continue
            by[t2[j].minute].append(p2[j - 1] - p2[j])
        prof[nm] = (np.array([np.mean(v) if len(v) > 5 else 0.0 for v in by]),
                    np.array([np.std(v, ddof=1) / np.sqrt(len(v))
                              if len(v) > 2 else 0.0 for v in by]),
                    np.array([len(v) for v in by]))
    win = {}
    for nm, tau, _, _ in BATCHES:
        mu = prof[nm][0]
        on, off = int(np.argmax(mu)), int(np.argmin(mu))
        win[nm] = (on, off, (off - on) % 60)
    print('  分 |        tau1（τ=1）        |        tau5（τ=5）        |'
          '       tau10（τ=10）')
    print('     |   壓降    ±SE    n  記號 |   壓降    ±SE    n  記號 |'
          '   壓降    ±SE    n  記號')
    print('  ' + '-' * 104)
    for i in range(60):
        row = '  %02d |' % i
        for nm, tau, _, _ in BATCHES:
            mu, se, n = prof[nm]
            on, off, gap = win[nm]
            mk = ''
            if i == on:
                mk = '開'
            elif i == off:
                mk = '停'
            elif (i - on) % 60 < gap:
                mk = '｜'
            row += ' %+.4f %.4f %4d  %-3s|' % (mu[i], se[i], n[i], mk)
        print(row[:-1])
    print('  ' + '-' * 104)
    for nm, tau, _, _ in BATCHES:
        mu = prof[nm][0]
        on, off, gap = win[nm]
        w = [(on + k) % 60 for k in range(gap)]
        tot = mu.sum()
        ws = sum(mu[i] for i in w)
        r_on = ws / (gap / 60.0)
        r_off = (tot - ws) / ((60 - gap) / 60.0)
        print('  %-6s 宣稱τ=%2d　泵窗 第%2d~%2d分（%2d 分）　佔壓降 %3.0f%%　'
              '泵開 %.4f / 泵停 %.4f = %.0f×'
              % (nm, tau, on, off, gap, ws / tot * 100, r_on, r_off, r_on / r_off))


def table_C():
    print('【表 C】τ=10 自動循環的內部剖面（13 段相干疊加，每 30 分一格）')
    print()
    ts, h, p, co2, ch4 = load(TAU_DIR)
    t2, h2, p2, _, _ = sub(ts, h, p, co2, ch4, *BATCHES[2][2:])
    segs = descents(h2, p2)
    reg = [(s, e) for s, e in segs
           if 5.0 <= h2[e] - h2[s] <= 8.5 and 0.20 <= p2[s] - p2[e] <= 0.30]
    G = np.arange(0, 6.01, 0.5)
    M = np.array([np.interp(G, h2[s:e + 1] - h2[s], p2[s:e + 1] - p2[s])
                  for s, e in reg])
    print('  時刻(hr)   平均累計壓降    標準誤    區間速率   相對速率')
    print('  ' + '-' * 60)
    mu = M.mean(axis=0)
    se = M.std(axis=0, ddof=1) / np.sqrt(len(M))
    d1 = np.diff(mu) / np.diff(G)
    base = -d1.mean()
    for j, g in enumerate(G):
        rate = '' if j == 0 else '%8.4f  %7.2f×' % (-d1[j - 1], -d1[j - 1] / base)
        print('    %4.1f      %+.4f      %.4f  %s' % (g, mu[j], se[j], rate))
    print('  ' + '-' * 60)
    print('  n = %d 段；全段平均速率 %.4f kg/cm²/hr' % (len(M), base))


def table_D():
    print('【表 D】自動化批次：逐日明細（08-11 ~ 08-31）')
    print()
    ts, h, p, co2, ch4 = load(AUTO_DIR)
    segs = descents(h, p)
    by = defaultdict(list)
    for i, t in enumerate(ts):
        by[t.date()].append(i)
    print('  日期        筆數  覆蓋  壓力min~max  CH4中位  日變化  CO2中位  '
          '補氣次數  當日消耗  備註')
    print('  ' + '-' * 102)
    prev = None
    for d in sorted(by):
        ix = by[d]
        lo, hi = ix[0], ix[-1]
        cons = sum(p[max(s, lo)] - p[min(e, hi)] for s, e in segs
                   if min(e, hi) > max(s, lo) + 1
                   and p[max(s, lo)] > p[min(e, hi)])
        c = float(np.median(ch4[ix]))
        note = ''
        if d.day in (24, 25):
            note = '★氫氣耗盡'
        elif d.day == 31:
            note = '★覆蓋不足'
        elif d.day >= 26:
            note = '衰退期'
        elif d.day <= 23:
            note = '建立期'
        dlt = '' if prev is None else '%+6.1f' % (c - prev)
        print('  %s  %4d  %3.0f%%  %.2f~%.2f   %6.2f  %6s   %5.2f     %2d'
              '     %6.3f  %s'
              % (d, len(ix), len(ix) / 14.4, p[ix].min(), p[ix].max(), c, dlt,
                 float(np.median(co2[ix])),
                 int((np.diff(p[ix]) > 0.03).sum()), cons, note))
        prev = c


def table_E():
    print('【表 E】化學計量：分階段與各種估計量')
    print()
    ts, h, p, co2, ch4 = load(AUTO_DIR)
    segs = descents(h, p)
    hr = np.floor(h).astype(int)
    PH = [('建立期', dt.date(2026, 8, 11), dt.date(2026, 8, 23)),
          ('氫氣耗盡', dt.date(2026, 8, 24), dt.date(2026, 8, 25)),
          ('衰退期', dt.date(2026, 8, 26), dt.date(2026, 8, 30))]
    print('  期間        天數  總消耗   CH4起→迄      估計量         '
          'CH4產量      生物份額     CH4產率')
    print('  ' + '-' * 104)
    for nm, d0, d1 in PH:
        m = np.array([d0 <= t.date() <= d1 for t in ts])
        ix = np.flatnonzero(m)
        lo, hi = ix[0], ix[-1]
        cons = sum(p[max(s, lo)] - p[min(e, hi)] for s, e in segs
                   if s >= lo and e <= hi)
        days = (h[hi] - h[lo]) / 24
        y = []
        for u in sorted(set(hr[m])):
            k = np.flatnonzero((hr == u) & m)
            if len(k) >= 40:
                y.append(float((ch4[k] / 100.0 * (p[k] + ATM)).mean()))
        y = np.array(y)
        rows = [('單筆端點', ch4[hi] / 100 * (p[hi] + ATM)
                 - ch4[lo] / 100 * (p[lo] + ATM), None)]
        for K in (6, 12, 24):
            if len(y) >= 3 * K:
                g = y[-K:].mean() - y[:K].mean()
                s = np.sqrt(y[-K:].var(ddof=1) / K + y[:K].var(ddof=1) / K)
                rows.append(('兩端各 %d hr' % K, g, s))
        first = True
        for lab, g, s in rows:
            head = ('  %-10s %4.1f  %6.2f   %4.1f%%→%4.1f%%  '
                    % (nm, days, cons, ch4[lo], ch4[hi])) if first \
                else ' ' * 42
            err = '' if s is None else ' ± %.4f' % s
            errp = '' if s is None else ' ± %.0f%%' % (s / cons / 0.25 * 100)
            star = '  ← 建議' if lab == '兩端各 6 hr' else ''
            print('%s%-14s %+.4f%-10s %+4.0f%%%-9s %7.0f mL/天%s'
                  % (head, lab, g, err, g / cons / 0.25 * 100, errp,
                     ml(g) / days, star))
            first = False
        print()
    print('  化學計量上限：CH4/消耗 ≤ 0.25（生物份額 ≤ 100%）')
    print('  ⚠ 份額為負代表該期間沒有甲烷在產生，現有的正被補入氣體稀釋')
    print('  ⚠ CH4 產率以頭空 1.00 L、30 °C 換算；溫度欄恆為 30.00 非實測值')


def table_F():
    print('【表 F】三批次總表（τ 槓桿）')
    print()
    ts, h, p, co2, ch4 = load(TAU_DIR)
    print('  批次    τ   期間            天數  段數  降幅中位  時長中位  '
          '速率中位   泵窗   佔壓降  CH4峰')
    print('  ' + '-' * 100)
    for nm, tau, d0, d1 in BATCHES:
        t2, h2, p2, _, m2 = sub(ts, h, p, co2, ch4, d0, d1)
        segs = descents(h2, p2)
        amp = np.array([p2[s] - p2[e] for s, e in segs])
        dur = np.array([h2[e] - h2[s] for s, e in segs])
        by = [[] for _ in range(60)]
        for j in range(1, len(t2)):
            dtr = h2[j] - h2[j - 1]
            if not (0.008 < dtr < 0.03) or p2[j] - p2[j - 1] > 0.03:
                continue
            by[t2[j].minute].append(p2[j - 1] - p2[j])
        mu = np.array([np.mean(v) if len(v) > 5 else 0.0 for v in by])
        on, off = int(np.argmax(mu)), int(np.argmin(mu))
        gap = (off - on) % 60
        w = sum(mu[(on + k) % 60] for k in range(gap))
        from core import ch4_realtime as c4
        pk = c4.find_peaks_np(m2, c4.VENT_PROMINENCE, c4.VENT_MIN_DISTANCE)
        print('  %-6s %2d  %s~%s  %4.1f  %3d   %7.3f  %7.2f  %8.4f  '
              '%2d-%2d(%2d)  %3.0f%%   %d'
              % (nm, tau, d0.strftime('%m/%d'), d1.strftime('%m/%d'),
                 (d1 - d0).days + 1, len(segs), np.median(amp),
                 np.median(dur), np.median(amp / dur), on, off, gap,
                 w / mu.sum() * 100, len(pk)))
    print('  ' + '-' * 100)
    print('  「泵窗」＝驟降尖峰至回升尖峰的分鐘區間；其長度應等於 τ')


TABLES = {'A': table_A, 'B': table_B, 'C': table_C,
          'D': table_D, 'E': table_E, 'F': table_F}


def main():
    want = [x.upper() for x in sys.argv[1:]] or list(TABLES)
    for k in want:
        if k not in TABLES:
            print('沒有這張表：%s（可用 %s）' % (k, ' '.join(TABLES)))
            continue
        print('=' * 106)
        TABLES[k]()
        print()


if __name__ == '__main__':
    main()
