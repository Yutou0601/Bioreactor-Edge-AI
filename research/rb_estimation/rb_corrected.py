
# -*- coding: utf-8 -*-
"""把偏誤警告改成**已修正的估計 + 回收精度**。
════════════════════════════════════════════════════════════════════════

現況：論文報 median r_b = 0.0117，另註「系統性 −3%~−12%」，把換算丟給讀者。
間接推論（Gouriéroux 1993）的標準收尾不是這樣——校準曲線本來就是拿來
**反解並修正**的，不是拿來附註的。

做法：
  1. 由 degeneracy_invert.csv 的 ρ(β) 找出「與實測相容」的 β 集合
     相容 = |ρ_obs − ρ(β)| ≤ TOL 個校準標準差
     ⚠ 沒有任何 β 真正達到 0.831，所以這是「最接近」而非「涵蓋」，
       推論強度較弱，正文必須明講。
  2. 取該集合的偏誤範圍，反推修正後的 r_b = r_obs / (1 + bias)
  3. 一併報「回收精度」：整個可接受族裡，估計量距真值多遠

輸出 -> docs/analysis_charts_3batch/rb_corrected.csv
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

# 幾個校準標準差之內算相容。
# ⚠ 用 2.0 時相容集合只剩 β = 0.40/0.50/0.65 三點，精度看似 ±1.5%，
#   但 0.20/0.25/0.80 是以 2.1–2.4σ 剛好落選的——門檻挪一點集合就變樣，
#   那個 ±1.5% 是網格運氣不是實力。放寬到 2.5σ 讓集合穩定，報 ±4%。
TOL = 2.5


def main():
    head, rows = {}, []
    with open(f'{OUT}/degeneracy_invert.csv', encoding='utf-8-sig') as fh:
        grab = False
        for r in csv.reader(fh):
            if not r:
                continue
            if r[0] == 'beta':
                grab = True; continue
            if grab:
                rows.append([float(v) for v in r])
            elif len(r) > 1:
                head[r[0]] = float(r[1])

    a = np.array(rows)
    beta, rho, rsd, bias = a[:, 0], a[:, 1], a[:, 2], a[:, 5]
    rho_obs, r_obs = head['rho_obs'], head['R0']

    z = (rho_obs-rho)/rsd
    ok = np.abs(z) <= TOL

    print('══ 偏誤修正後的 r_b ══\n')
    print(f'   實測 ρ = {rho_obs:.3f}   未修正中位 r_b = {r_obs:.5f}\n')
    print(f'   {"β":>6}{"ρ":>9}{"距實測(σ)":>12}{"偏誤":>9}'
          f'{"修正後 r_b":>13}{"相容":>7}')
    print('   '+'-'*56)
    for i in range(len(beta)):
        corr = r_obs/(1+bias[i]/100)
        print(f'   {beta[i]:>6.2f}{rho[i]:>9.3f}{z[i]:>12.1f}'
              f'{bias[i]:>8.1f}%{corr:>13.5f}'
              f'{"  ✓" if ok[i] else "":>7}')

    if not ok.any():
        print('\n   ✘ 沒有任何 β 落在容差內，無法給修正值')
        return

    b_ok = bias[ok]
    corr = r_obs/(1+b_ok/100)
    lo, hi, mid = corr.min(), corr.max(), float(np.median(corr))

    print(f'\n══ 結果（相容集合 β ∈ [{beta[ok].min():.2f}, '
          f'{beta[ok].max():.2f}]）══')
    print(f'   偏誤範圍      {b_ok.min():+.1f}% ~ {b_ok.max():+.1f}%')
    print(f'   修正後 r_b    {mid:.5f}  [{lo:.5f}, {hi:.5f}]')
    print(f'   相對未修正    {mid/r_obs-1:+.1%}')
    halfw = (hi-lo)/2/mid
    print(f'\n   回收精度：整個相容族裡，修正後估計的散布為 ±{halfw:.1%}')
    print(f'   （未修正的估計對真值的誤差則是 {b_ok.min():+.1f}%~'
          f'{b_ok.max():+.1f}%，全部同號＝系統性偏高）')

    path = os.path.join(OUT, 'rb_corrected.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['rho_obs', f'{rho_obs:.4f}'])
        w.writerow(['rb_uncorrected', f'{r_obs:.5f}'])
        w.writerow(['rb_corrected', f'{mid:.5f}'])
        w.writerow(['rb_lo', f'{lo:.5f}'])
        w.writerow(['rb_hi', f'{hi:.5f}'])
        w.writerow(['accuracy_pct', f'{halfw*100:.1f}'])
        w.writerow([])
        w.writerow(['beta', 'rho', 'z', 'bias_pct', 'rb_corr', 'compatible'])
        for i in range(len(beta)):
            w.writerow([f'{beta[i]:.2f}', f'{rho[i]:.4f}', f'{z[i]:.2f}',
                        f'{bias[i]:.1f}', f'{r_obs/(1+bias[i]/100):.5f}',
                        int(ok[i])])
    print(f'\n   → {path}')


if __name__ == '__main__':
    main()
