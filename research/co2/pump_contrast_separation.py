# -*- coding: utf-8 -*-
"""
以循環泵開／關的對照分離 r_b 與 P_eq（Pump-Contrast Separation, PCS）
════════════════════════════════════════════════════════════════════════

資料
────
Testing_data/0301-0416_無循環與有循環_5mins
  2026-03-01 ~ 04-06  循環泵**關**（只有液面接觸）  38 個循環
  2026-04-07 ~ 04-16  循環泵**開** 5 min/hr          16 個循環
兩段的菌群、液相、溫度與補氣帶（0.7 -> 1.1）皆相同，唯一差異是泵。

原理
────
兩段共用同一個 P_eq 與同一個 r_b，只有 k_La 不同：

    rate_off(P) = k_off (P - P_eq) + r_b
    rate_on (P) = k_on  (P - P_eq) + r_b

把速率對壓力作線性迴歸，兩條線的斜率即 k_off、k_on，截距為
    I = r_b - k P_eq
於是

    P_eq = (I_on - I_off) / (k_off - k_on)
    r_b  = (I_on k_off - I_off k_on) / (k_off - k_on)

關鍵：k 的差異來自**外部操作**（泵開關），不是來自同一次擬合，
故先前使 tau 槓桿失效的「相關估計誤差」在此不成立。
速率一律以弱形式量測（不對量化壓力做微分）。

輸出 -> docs/analysis_charts_3batch/pump_contrast.csv
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

SRC = os.path.join(testing_data(),
                   '0301-0416_無循環與有循環_5mins')
SPLIT = dt.datetime(2026, 4, 7, 9)
M, PORD, NT = 1.5, 6, 20          # 弱形式測試函數
NBOOT = 2000


def load():
    rows = []
    for fp in sorted(glob.glob(os.path.join(SRC, '*.csv'))):
        for line in open(fp, encoding='utf-8', errors='replace'):
            p = line.strip().split(',')
            if len(p) < 14:
                continue
            try:
                rows.append((dt.datetime(int(p[0]), int(p[1]), int(p[2]),
                                         int(p[3]), int(p[4]), int(float(p[5]))),
                             float(p[11])))          # 反應槽壓力
            except Exception:
                continue
    rows.sort()
    return rows


def cycles(rows):
    ts = [r[0] for r in rows]
    P = np.array([r[1] for r in rows])
    h = np.array([(t - ts[0]).total_seconds() / 3600 for t in ts])
    out, valley, start = [], P[0], 0
    for i in range(1, len(P)):
        if h[i] - h[i-1] > 0.5:
            if h[i-1] - h[start] > 3:
                out.append((start, i-1))
            start, valley = i, P[i]; continue
        if P[i] - valley > 0.03:
            if h[i-1] - h[start] > 3:
                out.append((start, i-1))
            start, valley = i, P[i]
        elif P[i] < valley:
            valley = P[i]
    if h[-1] - h[start] > 3:
        out.append((start, len(P)-1))
    return [(a, b) for a, b in out
            if h[b]-h[a] >= 4 and P[a]-P[b] >= 0.10]


def weak_points(rows, cyc):
    """每個測試函數窗給一個 (壓力, 速率, 期別, 循環編號) 樣本。"""
    ts = [r[0] for r in rows]
    P = np.array([r[1] for r in rows])
    h = np.array([(t - ts[0]).total_seconds() / 3600 for t in ts])
    pts = []
    for ci, (a, b) in enumerate(cyc):
        t = h[a:b+1] - h[a]; y = P[a:b+1]
        if t[-1] < 2*M + 0.5:
            continue
        seg = 'off' if ts[a] < SPLIT else 'on'
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
            rate = -np.trapezoid(dph * y[ins], t[ins]) / w   # dP/dt (<0)
            pres = np.trapezoid(ph * y[ins], t[ins]) / w
            pts.append((pres, -rate, seg, ci))               # 速率取正
    return pts


def wls(pp, rr):
    A = np.column_stack([pp, np.ones(len(pp))])
    b, *_ = np.linalg.lstsq(A, rr, rcond=None)
    return b[0], b[1]                     # slope=k, intercept=I


def solve(k_off, I_off, k_on, I_on):
    d = k_off - k_on
    if abs(d) < 1e-9:
        return np.nan, np.nan
    peq = (I_on - I_off) / d
    rb = (I_on*k_off - I_off*k_on) / d
    return peq, rb


def main():
    rows = load()
    cyc = cycles(rows)
    pts = weak_points(rows, cyc)
    print('══ 循環泵開／關對照分離 ══')
    ts = [r[0] for r in rows]
    n_off = len({c for p, r, s, c in pts if s == 'off'})
    n_on = len({c for p, r, s, c in pts if s == 'on'})
    print(f'   泵關 {n_off} 個循環、泵開 {n_on} 個循環；'
          f'弱形式樣本 {len(pts)} 個\n')

    res = {}
    for seg in ('off', 'on'):
        pp = np.array([p for p, r, s, c in pts if s == seg])
        rr = np.array([r for p, r, s, c in pts if s == seg])
        k, I = wls(pp, rr)
        res[seg] = (k, I, pp, rr,
                    np.array([c for p, r, s, c in pts if s == seg]))
        lab = '泵關（僅液面）' if seg == 'off' else '泵開（5 min/hr）'
        print(f'   {lab}：n = {len(pp)}   壓力 {pp.min():.2f}–{pp.max():.2f}')
        print(f'      rate = {k:+.5f}·P {I:+.5f}'
              f'   → k_La = {k:.4f}')

    k_off, I_off = res['off'][0], res['off'][1]
    k_on, I_on = res['on'][0], res['on'][1]
    peq, rb = solve(k_off, I_off, k_on, I_on)
    print(f'\n   k_La 比值（開/關） = {k_on/k_off:.2f}×')
    print(f'   ★ P_eq = {peq:.4f} kg cm⁻²')
    print(f'   ★ r_b  = {rb:.5f} kg cm⁻² hr⁻¹')

    # ── 叢集自助（叢集 = 循環）────────────────────────────────
    rng = np.random.default_rng(5)
    RB, PEQ, KO, KN = [], [], [], []
    for _ in range(NBOOT):
        th = {}
        ok = True
        for seg in ('off', 'on'):
            k0, I0, pp, rr, cc = res[seg]
            uc = np.unique(cc)
            pick = rng.choice(uc, len(uc), replace=True)
            m = np.concatenate([np.where(cc == c)[0] for c in pick])
            if len(m) < 10:
                ok = False; break
            th[seg] = wls(pp[m], rr[m])
        if not ok:
            continue
        pe, r = solve(th['off'][0], th['off'][1], th['on'][0], th['on'][1])
        if np.isfinite(pe) and np.isfinite(r):
            PEQ.append(pe); RB.append(r)
            KO.append(th['off'][0]); KN.append(th['on'][0])
    RB, PEQ = np.array(RB), np.array(PEQ)
    lo, hi = np.percentile(RB, [2.5, 97.5])
    print(f'\n   叢集自助（B = {len(RB)}，叢集 = 循環）')
    print(f'      k_La 關 = {np.median(KO):.4f} [{np.percentile(KO,2.5):.4f},'
          f' {np.percentile(KO,97.5):.4f}]')
    print(f'      k_La 開 = {np.median(KN):.4f} [{np.percentile(KN,2.5):.4f},'
          f' {np.percentile(KN,97.5):.4f}]')
    print(f'      P_eq = {np.median(PEQ):.4f}'
          f' [{np.percentile(PEQ,2.5):.4f}, {np.percentile(PEQ,97.5):.4f}]')
    print(f'      ★ r_b = {np.median(RB):.5f} [{lo:.5f}, {hi:.5f}]')
    print(f'      r_b > 0 的自助比例 = {(RB > 0).mean()*100:.1f}%')
    verdict = ('★★ r_b 顯著大於 0' if lo > 0 else
               '✗ r_b 的 95% 區間含 0')
    print(f'      {verdict}')

    with open(f'{OUT}/pump_contrast.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['quantity', 'estimate', 'ci_lo', 'ci_hi'])
        w.writerow(['kLa_pump_off', f'{np.median(KO):.6f}',
                    f'{np.percentile(KO,2.5):.6f}', f'{np.percentile(KO,97.5):.6f}'])
        w.writerow(['kLa_pump_on', f'{np.median(KN):.6f}',
                    f'{np.percentile(KN,2.5):.6f}', f'{np.percentile(KN,97.5):.6f}'])
        w.writerow(['P_eq', f'{np.median(PEQ):.6f}',
                    f'{np.percentile(PEQ,2.5):.6f}', f'{np.percentile(PEQ,97.5):.6f}'])
        w.writerow(['r_b', f'{np.median(RB):.6f}', f'{lo:.6f}', f'{hi:.6f}'])
    print(f'\n輸出 → {OUT}/pump_contrast.csv')


if __name__ == '__main__':
    main()
