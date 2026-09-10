
# -*- coding: utf-8 -*-
"""區間寬度的權衡：偏誤 vs 抽樣誤差
════════════════════════════════════════════════════════════════════════

`rb_vs_k_recovery.py` 證明逐區間反解在「真值隨 k 變」時有 5–10 % 的偏誤，
錯配代價 27 倍。**病因是區間內部的梯度**——區間內各循環的真值不同，
中位數反解出來的是加權平均而非區間中心的值。

⇒ 偏誤 ∝（梯度 × 區間寬）。**把區間變窄，偏誤就等比下降。**
   代價是每區間樣本數減少、抽樣誤差變大。

本檔直接量這個權衡：掃描區間數，對每個區間數重跑完整回收檢定，
報告「偏誤」與「信賴區間寬度」如何隨區間數變化，並找出兩者的平衡點。

判準：偏誤中位 < 2 %（與恆定真值的 0 % 同量級）且各區間仍可分辨。

輸出 -> docs/analysis_charts_3batch/rb_vs_k_binsweep.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from simulator_check import QUANT                                  # noqa: E402
from rb_vs_k_form import fit_LE_fast, prep, ar1                    # noqa: E402
from residual_structure import collect                             # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402
from rb_vs_k_nsga2 import K_MIN                                    # noqa: E402

RNG = np.random.default_rng(161803)
CURV_MIN = 0.45
NREP = 6
GRID = np.arange(-0.005, 0.0451, 0.005)
NBINS = [5, 8, 12, 16]
# 最難的一條：梯度最大，錯配代價最高
TRUTH_S = lambda k: 0.030*k/(0.25+k)          # noqa: E731


def binned(rr, kk, edges):
    out = []
    for j in range(len(edges)-1):
        m = (kk >= edges[j]) & (kk < edges[j+1])
        out.append(np.median(rr[m]) if m.sum() >= 3 else np.nan)
    return np.array(out)


def pipeline(fits, rb_fn):
    rr, kk = [], []
    for f in fits:
        t = f['t']
        y = f['peq']+f['amp']*np.exp(-f['k']*t)-rb_fn(f['k'])*t \
            + ar1(len(t), f['sd'], f['phi'])
        y = np.round(y/QUANT)*QUANT
        if curvature(t, y) < CURV_MIN:
            continue
        g = fit_LE_fast(t, y)
        if g and g['k'] >= K_MIN:
            rr.append(g['rb']); kk.append(g['k'])
    return np.array(rr), np.array(kk)


def main():
    fits = [f for f in prep(collect()) if f['k'] >= K_MIN]
    ks = np.array([f['k'] for f in fits])
    print('══ 區間寬度的權衡：偏誤 vs 抽樣誤差 ══\n')
    print(f'   循環 {len(fits)}   投入真值為飽和型（梯度最大、錯配最嚴苛）')
    print(f'   每個區間數各建一次校準曲線（{len(GRID)} 值 × {NREP} 次）\n')

    print(f'   {"區間數":>7}{"每區間 n":>10}{"偏誤中位":>11}{"偏誤最大":>11}'
          f'{"CI 寬中位":>12}{"可分辨":>8}')
    print('   '+'-'*60)
    rows = []
    for nb in NBINS:
        edges = np.quantile(ks, np.linspace(0, 1, nb+1)); edges[-1] *= 1.001
        ctr = np.array([np.sqrt(edges[j]*edges[j+1]) for j in range(nb)])
        # 校準曲線
        cal = np.full((len(GRID), NREP, nb), np.nan)
        for a, c in enumerate(GRID):
            for r in range(NREP):
                rr, kk = pipeline(fits, lambda k, c=c: c)
                cal[a, r] = binned(rr, kk, edges)
        gj = np.nanmean(cal, axis=1); sj = np.nanstd(cal, axis=1, ddof=1)
        # 回收
        rr, kk = pipeline(fits, TRUTH_S)
        obs = binned(rr, kk, edges)
        bias, wid, est_all, lo_all, hi_all = [], [], [], [], []
        for j in range(nb):
            if np.any(np.isnan(gj[:, j])) or not np.all(np.diff(gj[:, j]) > 0) \
                    or np.isnan(obs[j]):
                continue
            true = float(TRUTH_S(ctr[j]))
            est = float(np.interp(obs[j], gj[:, j], GRID))
            sl = float(np.interp(est, GRID, np.gradient(gj[:, j], GRID)))
            m = (kk >= edges[j]) & (kk < edges[j+1])
            b = np.array([np.median(RNG.choice(rr[m], m.sum()))
                          for _ in range(300)]) if m.sum() > 5 else np.zeros(1)
            se = np.hypot(np.std(b, ddof=1),
                          float(np.interp(est, GRID, sj[:, j])))/max(abs(sl), 1e-9)
            bias.append(abs(est-true)/max(abs(true), 1e-9))
            wid.append(2*1.96*se)
            est_all.append(est); lo_all.append(est-1.96*se)
            hi_all.append(est+1.96*se)
        if not bias:
            continue
        mb, xb, mw = np.median(bias), np.max(bias), np.median(wid)
        sep = lo_all[-1] > hi_all[0]          # 兩端是否仍可分辨
        npb = int(len(rr)/nb)
        print(f'   {nb:>7}{npb:>10}{mb*100:>10.1f}%{xb*100:>10.1f}%'
              f'{mw:>12.5f}{"  ✓" if sep else "  ✘":>8}')
        rows.append([nb, npb, f'{mb:.4f}', f'{xb:.4f}', f'{mw:.5f}', int(sep)])

    print(f'\n── 判定 ──')
    ok = [r for r in rows if float(r[2]) < 0.02 and r[5] == 1]
    if ok:
        best = ok[0]
        print(f'   ✓ 區間數 {best[0]} 時偏誤中位 {float(best[2])*100:.1f} %'
              f'（< 2 %），且兩端仍可分辨')
        print(f'     → 縮窄區間確實壓下偏誤，架構在此設定下可用')
    else:
        print('   ✘ 無任何區間數同時滿足「偏誤 < 2 %」與「兩端可分辨」')
        print('     → 偏誤與抽樣誤差此消彼長，資料撐不起逐區間的 r_b(k)')

    with open(f'{OUT}/rb_vs_k_binsweep.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['n_bins', 'n_per_bin', 'bias_median', 'bias_max',
                    'ci_width_median', 'endpoints_separable'])
        w.writerows(rows)
    print(f'\n輸出 → {OUT}/rb_vs_k_binsweep.csv')


if __name__ == '__main__':
    main()
