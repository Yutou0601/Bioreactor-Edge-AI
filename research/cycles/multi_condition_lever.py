# -*- coding: utf-8 -*-
"""
多條件槓桿：把 tau 槓桿改用「中心化的分箱速率迴歸」重做
════════════════════════════════════════════════════════════════════════

五個條件（k_La 由小到大）
  泵關（2026-03）、泵開 5min/hr（2026-04）、tau=1/5/10 min（2026-07~08）

對每個條件各做一次**中心化**的線性迴歸

    rate = k * (P - P0) + c ,   P0 = 1.00 kg/cm² 固定

中心化使同一次迴歸的 k 與 c 的估計誤差**正交**——這正是當初兩步驟法失效的
根源（未中心化時 slope 與 intercept 誤差強相關，投影到 Peq'-1/kLa 平面製造假相關）。

模型預測
    c_i = k_i (P0 - P_eq) + r_b
故把 c 對 k 作圖應**共線**，截距 = r_b、斜率 = P0 - P_eq。
共線性本身是可檢驗的預測（兩個條件時無從驗證，三個以上才有自由度）。

速率一律以弱形式量測，不對量化壓力做微分。

輸出 -> docs/analysis_charts_3batch/multi_condition_lever.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
from paths import testing_data          # Testing_data 的位置解析
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

from analyze_three_batches import OUT                    # noqa: E402
from analyze_new_methods import collect                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OLD = os.path.join(testing_data(), '0301-0416_無循環與有循環_5mins')
SPLIT = dt.datetime(2026, 4, 7, 9)
P0 = 1.00
M, PORD, NT = 1.5, 6, 20
NBOOT = 3000


def weak_pts(t, y):
    out = []
    for tc in np.linspace(t[0]+M, t[-1]-M, NT):
        u = (t - tc) / M
        ins = np.abs(u) < 1
        if ins.sum() < 20:
            continue
        base = 1 - u[ins]**2
        ph = base**PORD
        dph = PORD * base**(PORD-1) * (-2*u[ins]) / M
        w = np.trapezoid(ph, t[ins])
        if w <= 0:
            continue
        out.append((np.trapezoid(ph*y[ins], t[ins])/w,
                    np.trapezoid(dph*y[ins], t[ins])/w))   # (P, rate>0)
    return out


def old_conditions():
    rows = []
    for fp in sorted(glob.glob(os.path.join(OLD, '*.csv'))):
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
    ts = [r[0] for r in rows]; P = np.array([r[1] for r in rows])
    h = np.array([(t-ts[0]).total_seconds()/3600 for t in ts])
    cyc, valley, start = [], P[0], 0
    for i in range(1, len(P)):
        if h[i]-h[i-1] > 0.5:
            if h[i-1]-h[start] > 3:
                cyc.append((start, i-1))
            start, valley = i, P[i]; continue
        if P[i]-valley > 0.03:
            if h[i-1]-h[start] > 3:
                cyc.append((start, i-1))
            start, valley = i, P[i]
        elif P[i] < valley:
            valley = P[i]
    d = {'泵關 (2026-03)': [], '泵開 5min (2026-04)': []}
    for ci, (a, b) in enumerate(cyc):
        if h[b]-h[a] < 4 or P[a]-P[b] < 0.10:
            continue
        key = '泵關 (2026-03)' if ts[a] < SPLIT else '泵開 5min (2026-04)'
        for pr, rt in weak_pts(h[a:b+1]-h[a], P[a:b+1]):
            d[key].append((pr, rt, ci))
    return d


def new_conditions():
    d = {}
    for name, cs in collect().items():
        tag = {'1.1 (1min)': 'tau=1min (2026-07)',
               '2.1 (5min)': 'tau=5min (2026-07)',
               '3.1 (10min)': 'tau=10min (2026-08)'}.get(name, name)
        d[tag] = []
        for ci, c in enumerate(cs):
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values/3600
            y = c.p_reactor.values.astype(float)
            if t[-1] < 2*M+0.5:
                continue
            for pr, rt in weak_pts(t, y):
                d[tag].append((pr, rt, ci))
    return d


def fit_centered(pts):
    p = np.array([x[0] for x in pts]); r = np.array([x[1] for x in pts])
    A = np.column_stack([p - P0, np.ones(len(p))])
    b, *_ = np.linalg.lstsq(A, r, rcond=None)
    return b[0], b[1]          # k, c


def main():
    cond = {}
    cond.update(old_conditions())
    cond.update(new_conditions())
    order = ['泵關 (2026-03)', '泵開 5min (2026-04)', 'tau=1min (2026-07)',
             'tau=5min (2026-07)', 'tau=10min (2026-08)']
    order = [o for o in order if o in cond and len(cond[o]) > 30]

    print('══ 各條件的中心化速率迴歸（P0 = 1.00）══')
    print(f"{'條件':<24}{'窗數':>6}{'循環':>6}{'壓力範圍':>14}"
          f"{'k_La':>9}{'c (P0處速率)':>13}")
    print('-' * 74)
    K, C = [], []
    for o in order:
        pts = cond[o]
        k, c = fit_centered(pts)
        p = np.array([x[0] for x in pts])
        ncy = len({x[2] for x in pts})
        print(f'{o:<24}{len(pts):>6}{ncy:>6}'
              f'{f"{p.min():.2f}-{p.max():.2f}":>14}{k:>9.4f}{c:>13.5f}')
        K.append(k); C.append(c)
    K, C = np.array(K), np.array(C)

    print('\n══ 槓桿迴歸：c 對 k（模型預測共線）══')
    A = np.column_stack([K, np.ones(len(K))])
    b, res, *_ = np.linalg.lstsq(A, C, rcond=None)
    slope, rb = b
    pred = A @ b
    ss = float(np.sum((C-pred)**2))
    sst = float(np.sum((C-C.mean())**2))
    print(f'   c = {slope:+.4f}·k {rb:+.5f}')
    print(f'   → P_eq = P0 - slope = {P0-slope:.4f} kg cm⁻²')
    print(f'   → ★ r_b = {rb:.5f} kg cm⁻² hr⁻¹')
    print(f'   共線性 R² = {1-ss/sst:.4f}   殘差 = '
          + '  '.join(f'{x:+.5f}' for x in (C-pred)))

    print('\n   逐條件殘差（偏離共線的程度）：')
    for o, r in zip(order, C-pred):
        flag = '   ← 明顯偏離' if abs(r) > 2*np.std(C-pred) else ''
        print(f'     {o:<24}{r:+.5f}{flag}')

    # 只用 7-8 月三批（同液體、同期間）
    idx = [i for i, o in enumerate(order) if o.startswith('tau=')]
    if len(idx) >= 3:
        A2 = np.column_stack([K[idx], np.ones(len(idx))])
        b2, *_ = np.linalg.lstsq(A2, C[idx], rcond=None)
        p2 = A2 @ b2
        print(f'\n   [只用 7-8 月三批，同液體同期間]')
        print(f'     P_eq = {P0-b2[0]:.4f}   r_b = {b2[1]:.5f}'
              f'   共線殘差 = ' + '  '.join(f'{x:+.5f}' for x in (C[idx]-p2)))

    # 叢集自助
    rng = np.random.default_rng(11)
    RB, PEQ = [], []
    for _ in range(NBOOT):
        kk, cc = [], []
        ok = True
        for o in order:
            pts = cond[o]
            ids = np.array([x[2] for x in pts])
            uc = np.unique(ids)
            pick = rng.choice(uc, len(uc), replace=True)
            m = np.concatenate([np.where(ids == c)[0] for c in pick])
            if len(m) < 20:
                ok = False; break
            k, c = fit_centered([pts[i] for i in m])
            kk.append(k); cc.append(c)
        if not ok:
            continue
        Ab = np.column_stack([kk, np.ones(len(kk))])
        try:
            bb, *_ = np.linalg.lstsq(Ab, np.array(cc), rcond=None)
        except Exception:
            continue
        PEQ.append(P0-bb[0]); RB.append(bb[1])
    RB, PEQ = np.array(RB), np.array(PEQ)
    lo, hi = np.percentile(RB, [2.5, 97.5])
    print(f'\n══ 叢集自助（B = {len(RB)}，叢集 = 循環）══')
    print(f'   P_eq = {np.median(PEQ):.4f}'
          f' [{np.percentile(PEQ,2.5):.4f}, {np.percentile(PEQ,97.5):.4f}]')
    print(f'   ★ r_b = {np.median(RB):.5f} [{lo:.5f}, {hi:.5f}]')
    print(f'   r_b > 0 的比例 = {(RB>0).mean()*100:.1f}%')
    print(f'   {"★★ 顯著大於 0" if lo > 0 else "✗ 區間含 0"}')

    with open(f'{OUT}/multi_condition_lever.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['condition', 'n_windows', 'kLa', 'c_at_P0'])
        for o, k, c in zip(order, K, C):
            w.writerow([o, len(cond[o]), f'{k:.6f}', f'{c:.6f}'])
        w.writerow([])
        w.writerow(['r_b', f'{np.median(RB):.6f}', f'{lo:.6f}', f'{hi:.6f}'])
        w.writerow(['P_eq', f'{np.median(PEQ):.6f}',
                    f'{np.percentile(PEQ,2.5):.6f}',
                    f'{np.percentile(PEQ,97.5):.6f}'])
    print(f'\n輸出 → {OUT}/multi_condition_lever.csv')


if __name__ == '__main__':
    main()
