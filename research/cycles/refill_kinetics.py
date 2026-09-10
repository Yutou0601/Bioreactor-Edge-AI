
# -*- coding: utf-8 -*-
"""
補氣事件的動力學：自動補氣 vs 手動補氣
════════════════════════════════════════════════════════════════════════

設備方指出：「循環是慢慢下降，補氣是快速上升」，且 2026-07-11 的
Pend 移位「應該是有手動補氣」。

這是一個**必須檢驗的替代解釋**。切分器把「壓力上升 > 0.03」當成循環結束，
所以若有人在壓力尚未降到觸發閾值時就手動補氣，循環會被提早切斷，
記下一個**虛高的 Pend**——那麼「Pend 由 0.72 持續移到 0.92」就不是
設定點改變，而是七月手動補氣變頻繁造成的假象。

判別依據（設備方提供）：**上升速率**。自動補氣由控制器觸發，
起始壓力應集中在觸發閾值附近；手動補氣起始壓力隨機。

輸出 -> docs/analysis_charts_3batch/refill_kinetics.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import glob
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import load, TD                           # noqa: E402

RISE = 0.03         # 判定為上升事件的最小幅度（同切分器）
MAXGAP = 1.0        # 資料連續性（小時）


def rise_events(rows):
    """找出所有壓力上升事件，記錄起點、終點、歷時與速率。"""
    ts = [r[0] for r in rows]
    P = np.array([r[1] for r in rows], float)
    h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
    ev, i = [], 1
    n = len(P)
    while i < n:
        if h[i]-h[i-1] > MAXGAP:
            i += 1; continue
        if P[i] > P[i-1]:
            j = i
            # 延伸到上升結束
            while j+1 < n and h[j+1]-h[j] <= MAXGAP and P[j+1] >= P[j]:
                j += 1
            amp = P[j]-P[i-1]
            dur = h[j]-h[i-1]
            if amp >= RISE and dur > 0:
                ev.append(dict(t=ts[i-1], P_from=P[i-1], P_to=P[j],
                               amp=amp, dur_hr=dur,
                               rate=amp/dur, nsamp=j-i+2))
            i = j+1
        else:
            i += 1
    return ev


def main():
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append((sp, f'{d}/{s}'))

    seen, ev = set(), []
    for path, tag in folders:
        try:
            rows = load(path)
        except Exception:
            continue
        if len(rows) < 2000:
            continue
        for e in rise_events(rows):
            key = (e['t'].replace(second=0), round(e['amp'], 2))
            if key in seen:
                continue
            seen.add(key)
            e['folder'] = tag
            ev.append(e)
    ev.sort(key=lambda x: x['t'])

    print('══ 補氣事件動力學 ══')
    print(f'   上升事件 {len(ev)} 個   '
          f'{ev[0]["t"].date()} → {ev[-1]["t"].date()}\n')

    rate = np.array([e['rate'] for e in ev])
    amp = np.array([e['amp'] for e in ev])
    dur = np.array([e['dur_hr'] for e in ev])
    frm = np.array([e['P_from'] for e in ev])
    T = [e['t'] for e in ev]

    print('── 整體分布 ──')
    for nm, v, u in (('上升幅度', amp, 'kg/cm²'), ('歷時', dur*60, 'min'),
                     ('速率', rate, 'kg/cm²/hr'), ('起始壓力', frm, 'kg/cm²')):
        q = np.quantile(v, [.05, .25, .5, .75, .95])
        print(f'   {nm:<8}{u:<12} 5% {q[0]:7.3f}  25% {q[1]:7.3f}'
              f'  中位 {q[2]:7.3f}  75% {q[3]:7.3f}  95% {q[4]:7.3f}')

    # ── 關鍵檢定：起始壓力是否集中在觸發閾值？──────────────
    print('\n── 檢定 1：自動補氣的起始壓力應集中在觸發閾值 ──')
    print('   （手動補氣的起始壓力隨機分布）')
    print(f'   {"期間":<16}{"n":>5}{"起始壓力中位":>13}{"IQR":>16}'
          f'{"前3值涵蓋":>11}')
    print('   '+'-'*64)
    periods = [('2025-10 → 2026-05', dt.date(2025, 10, 1), dt.date(2026, 6, 1)),
               ('2026-07-01 → 07-11', dt.date(2026, 7, 1), dt.date(2026, 7, 11)),
               ('2026-07-11 → 08-04', dt.date(2026, 7, 11), dt.date(2026, 8, 4))]
    for nm, a, b in periods:
        s = np.array([a <= t.date() < b for t in T])
        if s.sum() < 3:
            continue
        v = frm[s]
        q = np.quantile(v, [.25, .75])
        qq = np.round(v/0.01)
        _, c = np.unique(qq, return_counts=True)
        top3 = np.sort(c)[::-1][:3].sum()/c.sum()
        print(f'   {nm:<16}{s.sum():>5}{np.median(v):>13.3f}'
              f'{f"[{q[0]:.2f}, {q[1]:.2f}]":>16}{top3:>11.0%}')

    # ── 檢定 2：上升速率是否有雙峰（自動 vs 手動）────────────
    print('\n── 檢定 2：上升速率的分布 ──')
    print(f'   {"期間":<16}{"n":>5}{"速率中位":>11}{"歷時中位(min)":>15}'
          f'{"幅度中位":>11}')
    print('   '+'-'*60)
    for nm, a, b in periods:
        s = np.array([a <= t.date() < b for t in T])
        if s.sum() < 3:
            continue
        print(f'   {nm:<16}{s.sum():>5}{np.median(rate[s]):>11.3f}'
              f'{np.median(dur[s])*60:>15.1f}{np.median(amp[s]):>11.3f}')

    # ── 檢定 3：七月的上升事件頻率是否異常 ──────────────────
    print('\n── 檢定 3：上升事件的頻率（次/天）──')
    import collections
    by = collections.defaultdict(list)
    for e in ev:
        by[(e['t'].year, e['t'].month)].append(e)
    print(f'   {"月":<10}{"事件數":>7}{"涵蓋天數":>10}{"次/天":>9}'
          f'{"起始壓力中位":>13}')
    print('   '+'-'*50)
    for k in sorted(by):
        g = by[k]
        days = len({e['t'].date() for e in g})
        f0 = np.median([e['P_from'] for e in g])
        print(f'   {k[0]}-{k[1]:02d}   {len(g):>7}{days:>10}'
              f'{len(g)/max(days,1):>9.2f}{f0:>13.3f}')

    with open(f'{OUT}/refill_kinetics.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['time', 'folder', 'P_from', 'P_to', 'amp',
                    'dur_hr', 'rate', 'n_samples'])
        for e in ev:
            w.writerow([e['t'].strftime('%Y-%m-%d %H:%M'), e['folder'],
                        f'{e["P_from"]:.3f}', f'{e["P_to"]:.3f}',
                        f'{e["amp"]:.3f}', f'{e["dur_hr"]:.3f}',
                        f'{e["rate"]:.3f}', e['nsamp']])
    print(f'\n輸出 → {OUT}/refill_kinetics.csv')


if __name__ == '__main__':
    main()
