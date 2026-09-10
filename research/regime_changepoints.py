
# -*- coding: utf-8 -*-
"""
製程異動的變點偵測（Regime Change-Point Detection）
════════════════════════════════════════════════════════════════════════

我們是靠手動翻資料才找到 2026-04-07 那次介入的。本檔把它自動化：
把全部歷史資料（去重後）攤成一條**依時間排序的循環層級序列**，
以精確最佳分割（optimal partitioning DP + BIC 懲罰）找出所有變點。

序列取兩個量：
  · 組成校正的 k_La 代理  r_head / (f_CO2 * P_head)   -> 傳質狀態
  · 平均下降速率                                      -> 總體活性

輸出 -> docs/analysis_charts_3batch/regime_changepoints.csv
"""
from paths import testing_data          # Testing_data 的位置解析
import os
import sys
import csv
import glob
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TD = testing_data()
M, PORD = 1.5, 6
# 各資料夾的進氣 CO2 莫耳分率（4:1 -> 0.2；1:1 -> 0.5）
FCO2 = {'0109-0123_H2_1CO2_1': 0.5}
DEFAULT_FCO2 = 0.2


def head_rate(t, y):
    m = min(M, (t[-1]-t[0])/5)
    u = (t-(t[0]+m))/m
    ins = np.abs(u) < 1
    if ins.sum() < 15:
        return np.nan, np.nan
    base = 1-u[ins]**2
    ph = base**PORD
    dph = PORD*base**(PORD-1)*(-2*u[ins])/m
    w = np.trapezoid(ph, t[ins])
    if w <= 0:
        return np.nan, np.nan
    return (np.trapezoid(dph*y[ins], t[ins])/w,
            np.trapezoid(ph*y[ins], t[ins])/w)


def load(folder):
    rows = []
    for fp in sorted(glob.glob(os.path.join(folder, '*.csv'))):
        for line in open(fp, encoding='utf-8', errors='replace'):
            p = line.strip().split(',')
            if len(p) < 14:
                continue
            try:
                rows.append((dt.datetime(int(p[0]), int(p[1]), int(p[2]),
                                         int(p[3]), int(p[4]), int(float(p[5]))),
                             float(p[11])))
            except Exception:
                continue
    rows.sort()
    return rows


def segment(rows, minhr=4):
    ts = [r[0] for r in rows]; P = np.array([r[1] for r in rows])
    h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
    out, valley, start = [], P[0], 0
    for i in range(1, len(P)):
        if h[i]-h[i-1] > 1.0:
            if h[i-1]-h[start] > minhr:
                out.append((start, i-1))
            start, valley = i, P[i]; continue
        if P[i]-valley > 0.03:
            if h[i-1]-h[start] > minhr:
                out.append((start, i-1))
            start, valley = i, P[i]
        elif P[i] < valley:
            valley = P[i]
    if h[-1]-h[start] > minhr:
        out.append((start, len(P)-1))
    return [(a, b) for a, b in out
            if h[b]-h[a] >= minhr and P[a]-P[b] >= 0.10], h, P, ts


def gather():
    """跨全部資料夾收集循環，並以 (起始時刻, 時長) 去重。"""
    seen, rows = {}, []
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if os.path.isdir(p):
            if glob.glob(os.path.join(p, '*.csv')):
                folders.append((p, d))
            for s in sorted(os.listdir(p)):
                sp = os.path.join(p, s)
                if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                    folders.append((sp, f'{d}/{s}'))
    for path, tag in folders:
        try:
            raw = load(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        cyc, h, P, ts = segment(raw)
        f = FCO2.get(tag.split('/')[0], DEFAULT_FCO2)
        for a, b in cyc:
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            r, p = head_rate(h[a:b+1]-h[a], P[a:b+1])
            if not np.isfinite(r) or p <= 0:
                continue
            seen[key] = 1
            rows.append(dict(t=ts[a], folder=tag, dur=h[b]-h[a],
                             P0=P[a], rate=(P[a]-P[b])/(h[b]-h[a]),
                             kla=r/(f*p), f=f))
    rows.sort(key=lambda x: x['t'])
    return rows


def optimal_partition(y, beta):
    """精確最佳分割：cost = n*log(var)，懲罰 beta。回傳變點索引。"""
    n = len(y)
    cs = np.concatenate([[0], np.cumsum(y)])
    cs2 = np.concatenate([[0], np.cumsum(y*y)])

    def cost(s, e):
        m = e-s
        if m < 3:
            return np.inf
        ss = cs2[e]-cs2[s] - (cs[e]-cs[s])**2/m
        return m*np.log(max(ss/m, 1e-12))

    F = np.full(n+1, np.inf); F[0] = -beta
    prev = np.zeros(n+1, int)
    for e in range(1, n+1):
        for s in range(0, e):
            c = F[s]+cost(s, e)+beta
            if c < F[e]:
                F[e] = c; prev[e] = s
    cps, e = [], n
    while e > 0:
        cps.append(prev[e]); e = prev[e]
    return sorted(set(cps[:-1]))


def main():
    rows = gather()
    print(f'══ 變點偵測 ══')
    print(f'   去重後循環 {len(rows)} 個'
          f'   {rows[0]["t"].date()} → {rows[-1]["t"].date()}\n')

    for key, lab in (('kla', '組成校正 k_La 代理'), ('rate', '平均下降速率')):
        y = np.array([r[key] for r in rows], float)
        ok = np.isfinite(y) & (y > 0)
        y2 = np.log(y[ok])                      # 對數化：變異隨水平縮放
        idx = np.where(ok)[0]
        beta = 3*np.log(len(y2))                # BIC 型懲罰
        cps = optimal_partition(y2, beta)
        print(f'── {lab}（n={len(y2)}，懲罰 {beta:.1f}）──')
        print(f'   偵測到 {len(cps)} 個變點')
        bounds = [0]+cps+[len(y2)]
        print(f"{'區段':<6}{'起始':<13}{'結束':<13}{'n':>5}"
              f"{'中位':>10}{'相對前段':>10}")
        print('   ' + '-'*58)
        prev_med = None
        for i in range(len(bounds)-1):
            s, e = bounds[i], bounds[i+1]
            seg_v = np.exp(y2[s:e])
            t0 = rows[idx[s]]['t'].date()
            t1 = rows[idx[e-1]]['t'].date()
            med = np.median(seg_v)
            chg = f'{med/prev_med:.2f}×' if prev_med else '—'
            print(f'   {i+1:<4}{str(t0):<13}{str(t1):<13}{e-s:>5}'
                  f'{med:>10.4f}{chg:>10}')
            prev_med = med
        if cps:
            print('   變點日期：' + '  '.join(
                str(rows[idx[c]]['t'].date()) for c in cps))
        print()

    # 已知事件的對照
    print('══ 對照已知事件 ══')
    known = {dt.date(2026, 4, 7): '手動排氣（已由逐分鐘資料確認）',
             dt.date(2026, 7, 22): '七月新批次開始（τ=1min）',
             dt.date(2026, 7, 27): 'τ 切換 1→5min',
             dt.date(2026, 7, 30): 'τ 切換 5→10min'}
    y = np.array([r['kla'] for r in rows], float)
    ok = np.isfinite(y) & (y > 0)
    idx = np.where(ok)[0]
    cps = optimal_partition(np.log(y[ok]), 3*np.log(ok.sum()))
    det = [rows[idx[c]]['t'].date() for c in cps]
    for d, desc in known.items():
        near = min((abs((x-d).days), x) for x in det) if det else (999, None)
        mark = '✔ 偵測到' if near[0] <= 3 else '✘ 未偵測'
        print(f'   {d}  {desc:<28} {mark}'
              + (f'（{near[1]}，差 {near[0]} 天）' if near[0] <= 3 else ''))
    print('\n   未對應到已知事件的變點（可能是未記錄的異動）：')
    for x in det:
        if all(abs((x-d).days) > 3 for d in known):
            print(f'      {x}')

    with open(f'{OUT}/regime_changepoints.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['time', 'folder', 'dur_hr', 'P0', 'rate', 'kla_proxy'])
        for r in rows:
            w.writerow([r['t'].strftime('%Y-%m-%d %H:%M'), r['folder'],
                        f'{r["dur"]:.1f}', f'{r["P0"]:.2f}',
                        f'{r["rate"]:.5f}', f'{r["kla"]:.5f}'])
    print(f'\n輸出 → {OUT}/regime_changepoints.csv')


if __name__ == '__main__':
    main()
