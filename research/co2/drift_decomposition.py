# -*- coding: utf-8 -*-
"""
循環調變漂移分解（Circulation-Modulated Drift Decomposition, CMDD）
════════════════════════════════════════════════════════════════════════

要解的問題（操作面）
────────────────────
反應器效能下滑時，壓力軌跡無法分辨兩個成因：
    液相飽和  -> 應換液
    菌群衰退  -> 應重新接種
兩者都在批次尺度上單調累積、都不在補氣時重置，故「雙時鐘」亦分不開。

本模型的槓桿
────────────
兩者對 k_La 的依賴方式不同：

    液相飽和侵蝕的是推動力 (P - P_eq)  -> 效應**正比於 k_La**
    菌群衰退侵蝕的是生物匯 r_b         -> 效應**與 k_La 無關**

    dP/dt = -k(tau) (P - P_eq(t)) - r_b(t)
    P_eq(t) = P_eq0 + alpha * t          （液相載入）
    r_b(t)  = r_b0 * exp(-lambda * t)    （菌群衰退）

於是在固定壓力 P0 量得的速率，其**批次尺度漂移**為

    D = d(rate)/dt_batch = -k * alpha - r_b0 * lambda * exp(-lambda t)

第一項正比於 k、第二項不含 k。故對多個循環設定量 D，
把 D 對 k 迴歸：**斜率 = -alpha（飽和）、截距 = 生物衰退項**。

與失敗的 tau 槓桿的差別
───────────────────────
tau 槓桿迴歸的是**水平值**（Peq' 對 1/kLa），設定誤差就住在那裡；
本法迴歸的是**批次尺度的漂移**，是二階量，與循環內軌跡形狀無關。

輸出 -> docs/analysis_charts_3batch/drift_decomposition.csv
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
        u = (t-tc)/M
        ins = np.abs(u) < 1
        if ins.sum() < 20:
            continue
        base = 1-u[ins]**2
        ph = base**PORD
        dph = PORD*base**(PORD-1)*(-2*u[ins])/M
        w = np.trapezoid(ph, t[ins])
        if w <= 0:
            continue
        out.append((np.trapezoid(ph*y[ins], t[ins])/w,
                    np.trapezoid(dph*y[ins], t[ins])/w))
    return out


def cycle_rate_at_P0(t, y):
    """該循環在 P0 處的速率（中心化迴歸的截距），以及 k。"""
    pts = weak_pts(t, y)
    if len(pts) < 6:
        return None
    p = np.array([x[0] for x in pts]); r = np.array([x[1] for x in pts])
    A = np.column_stack([p-P0, np.ones(len(p))])
    b, *_ = np.linalg.lstsq(A, r, rcond=None)
    return b[0], b[1]              # k_cycle, rate@P0


def gather():
    """回傳 {條件: [(t_batch_hr, rate@P0, k_cycle), ...]}"""
    out = {}
    # 七八月
    for name, cs in collect().items():
        tag = {'1.1 (1min)': 'tau=1min', '2.1 (5min)': 'tau=5min',
               '3.1 (10min)': 'tau=10min'}.get(name, name)
        t0 = cs[0].ts.iloc[0]
        lst = []
        for c in cs:
            t = (c.ts-c.ts.iloc[0]).dt.total_seconds().values/3600
            y = c.p_reactor.values.astype(float)
            if t[-1] < 2*M+0.5 or (y[0]-y[-1]) < 0.10:
                continue
            f = cycle_rate_at_P0(t, y)
            if f:
                lst.append(((c.ts.iloc[0]-t0).total_seconds()/3600, f[1], f[0]))
        out[tag] = lst
    # 三四月
    raw = []
    for fp in sorted(glob.glob(os.path.join(OLD, '*.csv'))):
        for line in open(fp, encoding='utf-8', errors='replace'):
            p = line.strip().split(',')
            if len(p) < 14:
                continue
            try:
                raw.append((dt.datetime(int(p[0]), int(p[1]), int(p[2]),
                                        int(p[3]), int(p[4]), int(float(p[5]))),
                            float(p[11])))
            except Exception:
                continue
    raw.sort()
    ts = [r[0] for r in raw]; P = np.array([r[1] for r in raw])
    h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
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
    for tag, sel in (('泵關(3月)', lambda t: t < SPLIT),
                     ('泵開5min(4月)', lambda t: t >= SPLIT)):
        lst, base = [], None
        for a, b in cyc:
            if h[b]-h[a] < 4 or P[a]-P[b] < 0.10 or not sel(ts[a]):
                continue
            if base is None:
                base = h[a]
            f = cycle_rate_at_P0(h[a:b+1]-h[a], P[a:b+1])
            if f:
                lst.append((h[a]-base, f[1], f[0]))
        out[tag] = lst
    return out


def drift(lst):
    """該條件的批次尺度漂移 D = d(rate@P0)/d(t_batch)。"""
    t = np.array([x[0] for x in lst]); r = np.array([x[1] for x in lst])
    if len(t) < 4:
        return np.nan, np.nan, np.nan
    A = np.column_stack([t, np.ones(len(t))])
    b, *_ = np.linalg.lstsq(A, r, rcond=None)
    resid = r - A @ b
    se = np.sqrt(np.sum(resid**2)/(len(t)-2) /
                 np.sum((t-t.mean())**2))
    return b[0], se, float(np.mean([x[2] for x in lst]))


def main():
    data = gather()
    order = ['泵關(3月)', 'tau=1min', 'tau=5min', 'tau=10min', '泵開5min(4月)']
    order = [o for o in order if o in data and len(data[o]) >= 4]
    print('══ CMDD：循環調變漂移分解 ══\n')
    print(f"{'條件':<16}{'循環':>5}{'跨度hr':>9}{'k_La':>9}"
          f"{'D = d(rate)/dt':>18}{'SE':>11}")
    print('-' * 70)
    K, Dv, W = [], [], []
    for o in order:
        D, se, k = drift(data[o])
        span = max(x[0] for x in data[o])
        print(f'{o:<16}{len(data[o]):>5}{span:>9.0f}{k:>9.4f}'
              f'{D:>18.3e}{se:>11.2e}')
        if np.isfinite(D) and np.isfinite(se) and se > 0:
            K.append(k); Dv.append(D); W.append(1/se**2)
    K, Dv, W = np.array(K), np.array(Dv), np.array(W)

    print('\n══ 把 D 對 k 迴歸（加權）══')
    A = np.column_stack([K, np.ones(len(K))])
    Wm = np.diag(W)
    b = np.linalg.solve(A.T @ Wm @ A, A.T @ Wm @ Dv)
    alpha = -b[0]
    bio = -b[1]
    pred = A @ b
    ss = float(np.sum(W*(Dv-pred)**2)); sst = float(np.sum(W*(Dv-Dv.mean())**2))
    print(f'   D = {b[0]:+.4e}·k {b[1]:+.4e}')
    print(f'   → ★ alpha（液相載入） = {alpha:+.6f} kg cm⁻² hr⁻¹')
    print(f'   → ★ 生物衰退項        = {bio:+.6e} kg cm⁻² hr⁻²')
    print(f'   加權 R² = {1-ss/sst:.3f}')
    print('   逐條件殘差：' + '  '.join(f'{x:+.2e}' for x in (Dv-pred)))

    print('\n══ 這兩個數字的操作解讀 ══')
    if alpha > 0:
        days = 0.08/alpha/24 if alpha > 0 else np.inf
        print(f'   液相載入：P_eq 以 {alpha:.6f} kg cm⁻²/hr 上漂'
              f' → 累積 0.08 需 {days:.0f} 天 → 換液週期上限')
    if abs(bio) > 0:
        print(f'   生物衰退：r_b 以 {bio:.3e} kg cm⁻² hr⁻² 下降')
        print(f'   兩者的相對貢獻（在 k = {np.median(K):.3f} 時）：'
              f'飽和 {abs(alpha*np.median(K))/(abs(alpha*np.median(K))+abs(bio))*100:.0f}%'
              f' / 衰退 {abs(bio)/(abs(alpha*np.median(K))+abs(bio))*100:.0f}%')

    # 自助
    rng = np.random.default_rng(17)
    AL, BI = [], []
    for _ in range(NBOOT):
        kk, dd, ww = [], [], []
        ok = True
        for o in order:
            lst = data[o]
            idx = rng.integers(0, len(lst), len(lst))
            D, se, k = drift([lst[i] for i in idx])
            if not np.isfinite(D) or not np.isfinite(se) or se <= 0:
                ok = False; break
            kk.append(k); dd.append(D); ww.append(1/se**2)
        if not ok:
            continue
        Ab = np.column_stack([kk, np.ones(len(kk))])
        Wb = np.diag(ww)
        try:
            bb = np.linalg.solve(Ab.T @ Wb @ Ab, Ab.T @ Wb @ np.array(dd))
        except Exception:
            continue
        AL.append(-bb[0]); BI.append(-bb[1])
    AL, BI = np.array(AL), np.array(BI)
    if len(AL):
        print(f'\n══ 自助（B = {len(AL)}）══')
        for nm, v in (('alpha', AL), ('生物衰退項', BI)):
            lo, hi = np.percentile(v, [2.5, 97.5])
            print(f'   {nm:<12} = {np.median(v):+.6f}'
                  f'  [{lo:+.6f}, {hi:+.6f}]'
                  f'  {"★ 不含 0" if lo*hi > 0 else "區間含 0"}')

    with open(f'{OUT}/drift_decomposition.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['condition', 'n_cycles', 'kLa', 'drift_D', 'se'])
        for o in order:
            D, se, k = drift(data[o])
            w.writerow([o, len(data[o]), f'{k:.6f}', f'{D:.6e}', f'{se:.6e}'])
        w.writerow([])
        w.writerow(['alpha', f'{alpha:.6f}'])
        w.writerow(['bio_decay', f'{bio:.6e}'])
    print(f'\n輸出 → {OUT}/drift_decomposition.csv')


if __name__ == '__main__':
    main()
