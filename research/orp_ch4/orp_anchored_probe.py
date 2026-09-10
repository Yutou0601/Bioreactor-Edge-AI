# -*- coding: utf-8 -*-
"""
以 CH4 離散錨點校準 ORP 連續探針（Anchored ORP Probe, AOP）
════════════════════════════════════════════════════════════════════════

想法
────
兩種量測各有一半的優點，剛好互補：

  排氣目測 CH4   絕對、不需校準，但整個批次只有 1 次（26 循環共 3 次）
  ORP           每分鐘連續（33,573 筆），但無絕對尺度（電極有效斜率未知）

用前者校準後者，即可把「一批一次」變成「逐分鐘」——資訊量差四個數量級。

化學計量
────────
CO2 + 4H2 -> CH4 + 2H2O：H2 消耗 4、CO2 消耗 1、CH4 留在氣相 1，
故**淨氣體移除 = 4 = H2 移除量**。物理溶解幾乎只溶 CO2（H2 溶解度約 CO2 的
1/44），對 pH2 貢獻可忽略。因此

    生物造成的壓降  =  H2 分壓的下降量

Nernst（對數形式）
──────────────────
    E = C - S ln(pH2)   =>   pH2(t) = pH2(0) exp( -(E(t)-E(0)) / S )

故單一循環的生物移除量

    dBio = pH2(0) [ 1 - exp(-dE/S) ] ,  pH2(0) = f * P(0)

只有兩個待定常數：f（補氣後的 H2 分率）與 S（電極有效斜率）。
兩者由 3 個批次的 CH4 錨點總量擬合。

驗證（關鍵，非循環論證）
────────────────────────
**留一批次**：以兩個批次的 CH4 錨點擬合 (f, S)，去預測第三個批次的錨點總量。
被預測的那個錨點完全沒有進入擬合。三折全部做。

輸出 -> docs/analysis_charts_3batch/orp_anchored_probe.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv

import numpy as np
from scipy import optimize

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                    # noqa: E402
from analyze_new_methods import collect                  # noqa: E402

M, PORD = 1.0, 6            # 弱形式測試函數：半寬 1 hr
BN = ['1.1 (1min)', '2.1 (5min)', '3.1 (10min)']


def smooth_end_values(t, y):
    """以緊支撐測試函數取循環頭尾的加權平均，避免用單點（±20 mV 噪聲）。"""
    def w_at(tc):
        u = (t - tc) / M
        ins = np.abs(u) < 1
        if ins.sum() < 5:
            return np.nan
        ph = (1 - u[ins] ** 2) ** PORD
        return float(np.sum(ph * y[ins]) / np.sum(ph))
    return w_at(t[0] + M), w_at(t[-1] - M)


def cycle_features():
    rows = []
    for name, cs in collect().items():
        for j, c in enumerate(cs, 1):
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600.0
            if t[-1] < 2 * M + 0.5:
                continue
            E = c.orp.values.astype(float)
            P = c.p_reactor.values.astype(float)
            e0, e1 = smooth_end_values(t, E)
            p0, _ = smooth_end_values(t, P)
            if not np.isfinite(e0) or not np.isfinite(e1):
                continue
            rows.append(dict(batch=name, cyc=j, dE=e1 - e0, P0=p0,
                             hours=t[-1]))
    return rows


def anchors():
    fp = f'{OUT}/separation_ch4_anchor.csv'
    a = {}
    with open(fp, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            a[r['batch']] = float(r['bio_removed'])
    return a


def predict(rows, f, S, batch):
    """該批次的生物移除總量（壓力單位）。"""
    tot = 0.0
    for r in rows:
        if r['batch'] != batch:
            continue
        tot += f * r['P0'] * (1.0 - np.exp(-r['dE'] / S))
    return tot


def fit(rows, anch, batches):
    def obj(th):
        f, S = th
        return sum((predict(rows, f, S, b) - anch[b]) ** 2 for b in batches)
    best, bx = np.inf, None
    for f0 in (0.3, 0.5, 0.8):
        for S0 in (40, 80, 150):
            r = optimize.minimize(obj, [f0, S0], method='Nelder-Mead',
                                  bounds=[(0.05, 1.0), (10, 600)],
                                  options=dict(maxiter=6000, fatol=1e-14))
            if r.fun < best:
                best, bx = r.fun, r.x
    return bx


def main():
    rows = cycle_features()
    anch = anchors()
    print('══ 以 CH4 錨點校準 ORP 連續探針 ══')
    print(f'   循環 {len(rows)} 個；ORP 頭尾值以 1 hr 弱形式窗平滑\n')
    print(f"{'批次':<14}{'循環':>4}{'ΔE 平均(mV)':>13}{'CH4 錨點總量':>14}")
    print('-' * 46)
    for b in BN:
        sub = [r for r in rows if r['batch'] == b]
        print(f"{b:<14}{len(sub):>4}{np.mean([r['dE'] for r in sub]):>13.1f}"
              f"{anch[b]:>14.4f}")

    print('\n══ 全批擬合（3 個錨點、2 個參數）══')
    f, S = fit(rows, anch, BN)
    print(f'   f = {f:.4f}（補氣後 H2 分率）   S = {S:.1f} mV/ln'
          f'  ≈ {S*2.303:.0f} mV/decade')
    print(f"{'批次':<14}{'預測':>10}{'錨點':>10}{'相對誤差':>10}")
    print('-' * 46)
    for b in BN:
        p = predict(rows, f, S, b)
        print(f'{b:<14}{p:>10.4f}{anch[b]:>10.4f}'
              f'{(p/anch[b]-1)*100:>9.1f}%')

    print('\n══ 留一批次驗證（被預測的錨點未進入擬合）══')
    print(f"{'留出批次':<14}{'f':>8}{'S':>8}{'預測':>10}{'錨點':>10}"
          f"{'相對誤差':>10}")
    print('-' * 62)
    out = []
    for held in BN:
        tr = [b for b in BN if b != held]
        ff, SS = fit(rows, anch, tr)
        p = predict(rows, ff, SS, held)
        err = (p / anch[held] - 1) * 100
        print(f'{held:<14}{ff:>8.4f}{SS:>8.1f}{p:>10.4f}{anch[held]:>10.4f}'
              f'{err:>9.1f}%')
        out.append(dict(held=held, f=ff, S=SS, pred=p, anchor=anch[held],
                        rel_err_pct=err))

    mae = np.mean([abs(o['rel_err_pct']) for o in out])
    print(f'\n   留一批次平均絕對相對誤差 = {mae:.1f}%')
    print(f'   對照基準：若改用「三批共用單一 r_b」去預測，'
          f'誤差為 {base_err(rows, anch):.1f}%')

    with open(f'{OUT}/orp_anchored_probe.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)
    print(f'\n輸出 → {OUT}/orp_anchored_probe.csv')


def base_err(rows, anch):
    """基準：生物移除量正比於批次時長（等同共用常數 r_b）。"""
    hrs = {b: sum(r['hours'] for r in rows if r['batch'] == b) for b in BN}
    errs = []
    for held in BN:
        tr = [b for b in BN if b != held]
        rb = np.mean([anch[b] / hrs[b] for b in tr])
        errs.append(abs(rb * hrs[held] / anch[held] - 1) * 100)
    return float(np.mean(errs))


if __name__ == '__main__':
    main()
