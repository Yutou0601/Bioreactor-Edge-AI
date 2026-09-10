
# -*- coding: utf-8 -*-
"""把抽樣誤差與真值族散布合成單一區間。
════════════════════════════════════════════════════════════════════════

rb_corrected.py 給的 ±4.0% 是**跨相容真值族的散布**——「不管真值是這族
裡的哪一個，估計都落在這裡」。它不含抽樣誤差，所以不是信賴區間，審稿人
問「這是 95% CI 嗎」時答案是否。

這裡把兩個來源合起來，用蒙地卡羅而不是誤差傳遞公式，因為修正是**除法**
（corrected = median / (1+bias)），兩個來源不是簡單相加：

  每次抽樣 → 對 301 個循環做 bootstrap 取中位數
           → 從相容集合裡抽一個偏誤
           → 相除得一個修正後的值

⚠ 兩個來源的性質不同：bootstrap 是統計的、可隨樣本數收斂；族散布是
  系統性的、加再多循環也不會變小。合成區間要標明這一點，不能讓讀者
  以為多量幾天就會變窄。

輸出 -> docs/analysis_charts_3batch/rb_interval.csv
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
from degeneracy_invert import build_fits                           # noqa: E402

RNG = np.random.default_rng(20260810)
NBOOT = 20000


def main():
    fits = build_fits()
    rb = np.array([f['rb'] for f in fits])
    n = len(rb)
    med = float(np.median(rb))

    # 相容集合的偏誤（rb_corrected.csv 的 compatible 列）
    bias = []
    with open(f'{OUT}/rb_corrected.csv', encoding='utf-8-sig') as fh:
        grab = False
        for r in csv.reader(fh):
            if not r:
                continue
            if r[0] == 'beta':
                grab = True; continue
            if grab and int(r[5]):
                bias.append(float(r[3]))
    bias = np.array(bias)

    print('══ 合成區間：抽樣誤差 + 真值族散布 ══\n')
    print(f'   循環 {n}   未修正中位 {med:.5f}')
    print(f'   相容集合的偏誤 {bias.min():+.1f}% ~ {bias.max():+.1f}%'
          f'（{len(bias)} 個網格點）\n')

    # ── 只有抽樣誤差 ────────────────────────────────────
    idx = RNG.integers(0, n, size=(NBOOT, n))
    boot = np.median(rb[idx], axis=1)
    se = float(boot.std(ddof=1))
    print(f'   bootstrap 中位數 SE  {se:.5f}  = {se/med:.1%}')
    print(f'   只計抽樣的 95%      [{np.percentile(boot, 2.5):.5f}, '
          f'{np.percentile(boot, 97.5):.5f}]')

    # ── 只有族散布 ──────────────────────────────────────
    fam = med/(1+bias/100)
    print(f'\n   只計族散布          [{fam.min():.5f}, {fam.max():.5f}]'
          f'  = ±{(fam.max()-fam.min())/2/np.median(fam):.1%}')

    # ── 合成 ────────────────────────────────────────────
    b = RNG.choice(bias, size=NBOOT)
    comb = boot/(1+b/100)
    lo, hi = np.percentile(comb, [2.5, 97.5])
    mid = float(np.median(comb))
    print(f'\n══ 合成 ══')
    print(f'   r_b = {mid:.5f}   95% [{lo:.5f}, {hi:.5f}]'
          f'   = ±{(hi-lo)/2/mid:.1%}')
    print(f'\n   拆解：抽樣 ±{se/med:.1%}（可隨樣本收斂）'
          f'　系統 ±{(fam.max()-fam.min())/2/np.median(fam):.1%}'
          f'（加樣本不會變小）')

    path = os.path.join(OUT, 'rb_interval.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        for k, v in (('n_cycles', n), ('median_raw', f'{med:.5f}'),
                     ('boot_se', f'{se:.5f}'),
                     ('boot_se_pct', f'{se/med*100:.2f}'),
                     ('family_pct',
                      f'{(fam.max()-fam.min())/2/np.median(fam)*100:.2f}'),
                     ('rb', f'{mid:.5f}'), ('lo95', f'{lo:.5f}'),
                     ('hi95', f'{hi:.5f}'),
                     ('total_pct', f'{(hi-lo)/2/mid*100:.2f}')):
            w.writerow([k, v])
    print(f'\n   → {path}')


if __name__ == '__main__':
    main()
