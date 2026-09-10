
# -*- coding: utf-8 -*-
"""驗證「小問題」架構：逐區間反解能不能撈回已知的 r_b(k)？
════════════════════════════════════════════════════════════════════════

第一階段（逐區間反解）在真實資料上給出四個彼此不重疊的錨點，看起來成立。
**但成立與否不能由「看起來合理」判定**，必須以已知真值檢驗。

**本檔要測的關鍵疑慮**：校準曲線是用**恆定**真值建的
（掃描 r_b = −0.005 … 0.045，每個都是常數），
卻要套用在**真值隨 k 變**的資料上。這個錯配會不會引入偏誤？

  作法：以三條**已知**的 r_b(k) 產生資料，走完整第一階段，
        比對反解出的錨點與該 k 上的真值。

  C  恆定     r_b(k) = 0.015                      ← 錯配為零，作為對照
  L  線性     r_b(k) = 0.006 + 0.010 k
  S  飽和     r_b(k) = 0.030 k / (0.25 + k)       ← 錯配最大

  判準：偏誤是否可忽略、95 % 信賴區間是否涵蓋真值。
        **若 S 的偏誤明顯大於 C，代表錯配確實引入偏誤，架構不可用。**

輸出 -> docs/analysis_charts_3batch/rb_vs_k_recovery.csv
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
from rb_vs_k_form import fit_LE_fast, prep, ar1, summary, NBIN     # noqa: E402
from residual_structure import collect                             # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402
from rb_vs_k_nsga2 import K_MIN                                    # noqa: E402

RNG = np.random.default_rng(2718281)
CURV_MIN = 0.45
NREP = 8
GRID = np.arange(-0.005, 0.0451, 0.005)

TRUTH = {
    'C  constant':   lambda k: 0.015+0*k,
    'L  linear':     lambda k: 0.006+0.010*k,
    'S  saturating': lambda k: 0.030*k/(0.25+k),
}


def run_pipeline(fits, rb_fn, edges):
    """以給定的 r_b(k) 產生資料並走完整管線，回傳 (分層中位數, 各區間的 rb)。"""
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
    rr, kk = np.array(rr), np.array(kk)
    return summary(rr, kk, edges), rr, kk


def main():
    fits = [f for f in prep(collect()) if f['k'] >= K_MIN]
    ks = np.array([f['k'] for f in fits])
    edges = np.quantile(ks, np.linspace(0, 1, NBIN+1)); edges[-1] *= 1.001
    ctr = np.array([np.sqrt(edges[j]*edges[j+1]) for j in range(NBIN)])

    print('══ 驗證「小問題」架構：逐區間反解的回收檢定 ══\n')
    print(f'   循環 {len(fits)}（已排除 k < {K_MIN}）   區間 {NBIN} 個')
    print(f'   區間幾何中心  ' + '  '.join(f'{c:.3f}' for c in ctr))

    # ── 建校準曲線（以**恆定**真值掃描）────────────────
    print(f'\n── 建立校準曲線（{len(GRID)} 個恆定真值 × {NREP} 次）──')
    cal = np.full((len(GRID), NREP, NBIN), np.nan)
    for a, c in enumerate(GRID):
        for r in range(NREP):
            cal[a, r], _, _ = run_pipeline(fits, lambda k, c=c: c, edges)
    gj = np.nanmean(cal, axis=1)              # (GRID, NBIN)
    sj = np.nanstd(cal, axis=1, ddof=1)
    print('   完成。各區間之校準映射是否單調：', end=' ')
    ok_bins = [j for j in range(NBIN) if np.all(np.diff(gj[:, j]) > 0)]
    print(' '.join('✓' if j in ok_bins else '✘' for j in range(NBIN)))

    # ── 對三條已知真值做回收 ────────────────────────────
    print(f'\n── 回收檢定 ──')
    rows = []
    for name, fn in TRUTH.items():
        print(f'\n   ▸ 投入真值：{name}')
        print(f'     {"k":>8}{"真值":>10}{"反解":>10}{"偏誤":>10}'
              f'{"95% 區間":>21}{"涵蓋":>6}')
        print('     '+'-'*62)
        obs, rr_all, kk_all = run_pipeline(fits, fn, edges)
        for j in ok_bins:
            true = float(fn(ctr[j]))
            est = float(np.interp(obs[j], gj[:, j], GRID))
            slope = np.gradient(gj[:, j], GRID)
            sl = float(np.interp(est, GRID, slope))
            # ⚠ 不確定度必須與 `rb_vs_k_pointwise.py` **完全一致**，
            #   否則判涵蓋率不公平。該處為「校準散布 ⊕ 觀測中位數的自助
            #   抽樣誤差」，後者大一到兩個數量級。初版僅用校準散布並把它
            #   翻倍充數，區間窄了數十倍，涵蓋率自然全部落空。
            mb = (kk_all >= edges[j]) & (kk_all < edges[j+1])
            rb_bin = rr_all[mb]
            boot = np.array([np.median(RNG.choice(rb_bin, len(rb_bin)))
                             for _ in range(400)]) if len(rb_bin) > 5 \
                else np.array([0.0])
            se_obs = float(np.std(boot, ddof=1))
            se_cal = float(np.interp(est, GRID, sj[:, j]))
            se = np.hypot(se_obs, se_cal)/max(abs(sl), 1e-9)
            lo, hi = est-1.96*se, est+1.96*se
            cov = lo <= true <= hi
            bias = (est-true)/abs(true) if abs(true) > 1e-9 else np.inf
            print(f'     {ctr[j]:>8.3f}{true:>10.5f}{est:>10.5f}'
                  f'{bias*100:>9.0f}%{f"[{lo:+.4f}, {hi:+.4f}]":>21}'
                  f'{"  ✓" if cov else "  ✘":>6}')
            rows.append([name, f'{ctr[j]:.4f}', f'{true:.6f}',
                         f'{est:.6f}', f'{bias:.4f}', int(cov)])

    # ── 判定 ────────────────────────────────────────────
    print(f'\n── 判定 ──')
    byform = {}
    for r in rows:
        byform.setdefault(r[0], []).append((abs(float(r[4])), int(r[5])))
    for name, v in byform.items():
        mb = float(np.median([x[0] for x in v]))
        cov = sum(x[1] for x in v)/len(v)
        print(f'   {name:<16} 偏誤中位 {mb*100:>5.0f} %   '
              f'區間涵蓋 {cov*100:>3.0f} %')
    mb_c = float(np.median([x[0] for x in byform['C  constant']]))
    mb_s = float(np.median([x[0] for x in byform['S  saturating']]))
    print(f'\n   錯配代價：飽和真值的偏誤 / 恆定真值的偏誤 = '
          f'{mb_s/max(mb_c,1e-9):.2f} 倍')
    ok = mb_s < 0.25 and all(
        sum(x[1] for x in v)/len(v) >= 0.75 for v in byform.values())
    print(f'   → {"✓ 架構可用：以恆定真值建的校準曲線，套在真值隨 k 變的資料上仍能回收" if ok else "✘ 架構有偏誤，不可直接寫進論文"}')

    with open(f'{OUT}/rb_vs_k_recovery.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['truth_form', 'k', 'true_rb', 'recovered_rb',
                    'rel_bias', 'ci_covers'])
        w.writerows(rows)
    print(f'\n輸出 → {OUT}/rb_vs_k_recovery.csv')


if __name__ == '__main__':
    main()
