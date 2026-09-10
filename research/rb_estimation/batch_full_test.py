# -*- coding: utf-8 -*-
"""三批次（2026-07~08）的全面測試：把論文的估計器直接跑在這三批上，
和化學計量對帳的答案做正面對照。

為什麼要這樣做。先前的比較是「論文的全資料集中位 0.0126」對「這三批的
化學計量結果 0.016~0.029」，但那是**不同資料**的比較，差異可能只是時期
不同。這裡把論文的估計器跑在**同一批資料**上，差異才歸因得到方法。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
from paths import testing_data          # Testing_data 的位置解析
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import glob
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from analyze_three_batches import load_txt

plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei']
plt.rcParams['axes.unicode_minus'] = False
B, R, G, O = '#1F6FB5', '#C0392B', '#666666', '#E8912B'

DIR = os.path.join(testing_data(), '202607至08最新循環研究')
KG = np.arange(0.01, 3.001, 0.02)
CSTAR, RISE, ATM = 0.45, 0.03, 1.033

BATCH = [('1 分', '2026-07-22 14:48', '2026-07-27 09:17', 0.0950,
          0.3164, 1.179, 1.085, 114.485, 0.0161),
         ('5 分', '2026-07-27 09:25', '2026-07-30 09:07', 0.0856,
          0.3484, 1.191, 1.014, 71.696, 0.0292),
         ('10 分', '2026-07-30 09:13', '2026-08-03 09:11', 0.0841,
          0.4304, 1.165, 0.962, 95.966, 0.0281)]


def fit(t, y):
    """論文 Algorithm 1：曲率預篩 + 輪廓化最小平方。"""
    n = len(y)
    c = (y[0] - y[n // 2]) / (y[0] - y[-1]) if y[0] != y[-1] else 0
    if c < CSTAR:
        return None, c
    tt = t - t[0]
    best = (np.inf, 0)
    for k in KG:
        X = np.column_stack([np.ones_like(tt), np.exp(-k * tt), -tt])
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        r = float(np.sum((X @ b - y) ** 2))
        if r < best[0]:
            best = (r, float(b[2]))
    return best[1], c


def cycles(s):
    p, t = s.p_reactor.values, (
        s.ts - s.ts.iloc[0]).dt.total_seconds().values / 3600
    cut = np.flatnonzero(np.diff(p) > RISE) + 1
    e = np.concatenate([[0], cut, [len(p)]])
    out = []
    for u, v in zip(e[:-1], e[1:]):
        if v - u >= 120 and (p[u] - p[v - 1]) > 0.10:
            out.append((t[u:v], p[u:v], s.ts.iloc[u]))
    return out


def main():
    df = pd.concat([load_txt(q) for q in sorted(glob.glob(DIR + '/*.txt'))],
                   ignore_index=True).sort_values('ts')
    df = df.drop_duplicates('ts').reset_index(drop=True)

    fig, ax = plt.subplots(2, 3, figsize=(14.5, 7.6))
    print('批次   循環 篩後  逐段 r_b 中位   四分位          化學計量 r_b  差異')
    res = []
    for j, (nm, a, b, f1, f2, P1, P2, tt, rb_st) in enumerate(BATCH):
        s = df[(df.ts >= a) & (df.ts <= b)].reset_index(drop=True)
        cy = cycles(s)
        rbs, cs, ts = [], [], []
        for t, p, t0 in cy:
            r, c = fit(t, p)
            cs.append(c)
            if r is not None:
                rbs.append(r); ts.append(t0)
        rbs = np.array(rbs)
        med = np.median(rbs) if rbs.size else np.nan
        q1, q3 = (np.percentile(rbs, [25, 75]) if rbs.size else (0, 0))
        print('%-5s  %3d  %3d   %.5f   %.5f/%.5f   %.5f   %+.0f%%'
              % (nm, len(cy), rbs.size, med, q1, q3, rb_st,
                 (rb_st / med - 1) * 100))
        res.append((nm, rbs, ts, rb_st, med))

        # 上排：壓力軌跡
        ax[0, j].plot((s.ts - s.ts.iloc[0]).dt.total_seconds() / 3600,
                      s.p_reactor, lw=.7, color=B)
        ax[0, j].set_title('批次%d（循環%s）　%d 段，篩後 %d'
                           % (j + 1, nm, len(cy), rbs.size),
                           fontweight='bold')
        ax[0, j].set_xlabel('時間（hr）')
        if j == 0:
            ax[0, j].set_ylabel('反應槽壓力（kg/cm²）')
        ax[0, j].grid(alpha=.25)

        # 下排：逐段 r_b 隨時間
        if rbs.size:
            h = [(x - ts[0]).total_seconds() / 3600 for x in ts]
            ax[1, j].plot(h, rbs, 'o-', ms=5, lw=1.2, color=G, alpha=.8,
                          label='逐段估計')
            ax[1, j].axhline(med, color=B, lw=2, ls='--',
                             label='逐段中位 %.4f' % med)
        ax[1, j].axhline(rb_st, color=R, lw=2.4,
                         label='化學計量 %.4f' % rb_st)
        ax[1, j].axhline(0.0126, color=O, lw=1.6, ls=':',
                         label='論文 0.0126')
        ax[1, j].set_ylim(-0.02, 0.09)
        ax[1, j].set_xlabel('批內經過時間（hr）')
        if j == 0:
            ax[1, j].set_ylabel('r_b（kg/cm²/hr）')
        ax[1, j].legend(fontsize=8.5, framealpha=.95)
        ax[1, j].grid(alpha=.25)

    fig.suptitle('三批次全面測試：論文估計器 vs 化學計量對帳（同一批資料）',
                 fontsize=14, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, .95))
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                     'docs', 'paper_figures', 'figZ2_batch_full.png')
    fig.savefig(q, dpi=170); plt.close(fig)
    print('\n→ figZ2_batch_full.png')


if __name__ == '__main__':
    main()
