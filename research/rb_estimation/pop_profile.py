# -*- coding: utf-8 -*-
"""(a) kT>7 子樣本是不是特定時期  (b) 族群層級的共享 r_b 輪廓似然。

(b) 的動機：逐段的輪廓是平的（單一循環資訊不足），但把 239 條各自
微彎的輪廓**相加**，族群層級可能出現明確的最小值。這與「逐段擬合
再取中位數」是不同的估計量：前者要求所有段共用同一個 r_b，
後者允許每段自己一個。

作法：對每個候選共享 r_b，把線性項移到反應變數那側
    y + r_b t = P_eq + A exp(-kt)
於是給定 k 時對 (P_eq, A) 是線性的，內層用最小平方、k 用網格輪廓化。
把 239 段的最小 RSS 相加，得到族群輪廓。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import csv
import sys
from collections import Counter

import numpy as np

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dataset_c import EXCLUDE, collect_c

KG = np.arange(0.02, 3.001, 0.05)
RG = np.arange(0.000, 0.0301, 0.0025)


def main():
    rows = [r for r in csv.DictReader(
        open('../docs/analysis_charts_3batch/rb_per_cycle.csv',
             encoding='utf-8-sig')) if r['folder'] not in EXCLUDE]
    cyc = collect_c()
    kk = np.array([float(r['k']) for r in rows])
    du = np.array([float(r['dur_hr']) for r in rows])
    kT = kk * du

    # ── (a) kT>7 的段落在哪些批次與時期 ──────────────────
    hi = kT > 7
    print('== kT>7 的 %d 段分布 ==' % hi.sum())
    for f, n in Counter(rows[i]['folder'] for i in np.flatnonzero(hi)).most_common():
        tot = sum(1 for r in rows if r['folder'] == f)
        print('  %-40s %3d / %3d 段' % (f[:40], n, tot))
    ts = sorted(rows[i]['time'][:7] for i in np.flatnonzero(hi))
    print('  月份範圍 %s ~ %s' % (ts[0], ts[-1]))
    print('  全體月份 %s ~ %s' % (min(r['time'][:7] for r in rows),
                                  max(r['time'][:7] for r in rows)))

    # ── (b) 族群層級的共享 r_b 輪廓 ─────────────────────
    print('\n== 族群輪廓：所有段共用同一個 r_b ==')
    tot = np.zeros(RG.size)
    used = 0
    for i, (tag, x, y) in enumerate(cyc):
        if len(x) < 120:
            continue
        used += 1
        t = x - x[0]
        for j, rbv in enumerate(RG):
            z = y + rbv * t
            best = np.inf
            for k in KG:
                X = np.column_stack([np.ones_like(t), np.exp(-k * t)])
                c, *_ = np.linalg.lstsq(X, z, rcond=None)
                r = float(np.sum((X @ c - z) ** 2))
                if r < best:
                    best = r
            tot[j] += best
    tot = tot / used
    lo = tot.min()
    print('  用了 %d 段' % used)
    print('  r_b      平均RSS       相對最小值')
    for j, rbv in enumerate(RG):
        mark = '  <== 最小' if tot[j] == lo else ''
        print('  %.4f   %.6e   %+7.2f%%%s'
              % (rbv, tot[j], (tot[j] / lo - 1) * 100, mark))
    print('\n  最小值在 r_b = %.4f' % RG[int(np.argmin(tot))])
    print('  定版 0.01256 ／ 尾段斜率 0.0177')


if __name__ == '__main__':
    main()
