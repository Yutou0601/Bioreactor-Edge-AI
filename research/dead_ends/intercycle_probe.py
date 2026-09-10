# -*- coding: utf-8 -*-
"""跨循環不對稱的三道把關：安慰劑、視窗敏感度、時長偏相關。

必須先排除的非生物路徑：
    r_b[i] --簡併--> k[i] --持續性--> k[i+1] --機械--> 初速[i+1]
安慰劑檢定：把預測子換成 k[i]。若 k 也給出同樣的不對稱，
r_b 的結果就只是這條路徑，不是生物。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import csv
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dataset_c import EXCLUDE, collect_c

G = np.random.default_rng(31)


def rk(a):
    return np.argsort(np.argsort(a)).astype(float)


def sp(a, b):
    return float(np.corrcoef(rk(a), rk(b))[0, 1])


def partial(a, b, c):
    """在秩空間把 c 迴歸掉之後的相關。"""
    A, B, Cc = rk(a), rk(b), rk(c)
    X = np.column_stack([Cc, np.ones_like(Cc)])
    ra = A - X @ np.linalg.lstsq(X, A, rcond=None)[0]
    rbv = B - X @ np.linalg.lstsq(X, B, rcond=None)[0]
    return float(np.corrcoef(ra, rbv)[0, 1])


def main():
    rows = [r for r in csv.DictReader(
        open('../docs/analysis_charts_3batch/rb_per_cycle.csv',
             encoding='utf-8-sig')) if r['folder'] not in EXCLUDE]
    cyc = collect_c()
    rb = np.array([float(r['rb']) for r in rows])
    kk = np.array([float(r['k']) for r in rows])
    du = np.array([float(r['dur_hr']) for r in rows])
    t = np.array([r['time'] for r in rows], dtype='datetime64[m]')
    fo = np.array([r['folder'] for r in rows])

    def v0_of(win):
        out = []
        for tag, x, y in cyc:
            m = x - x[0] <= win
            out.append((y[0] - y[m][-1]) / max(x[m][-1] - x[0], 1e-9)
                       if m.sum() > 4 else np.nan)
        return np.array(out)

    def pairs(v0, shift):
        a, b, d = [], [], []
        rng = range(len(rows) - 1) if shift > 0 else range(1, len(rows))
        for i in rng:
            j = i + shift
            if fo[i] != fo[j] or not np.isfinite(v0[j]):
                continue
            gap = abs((t[j] - t[i]) / np.timedelta64(1, 'h'))
            if not (0 < gap < 60):
                continue
            a.append(i); b.append(j); d.append(du[i])
        return np.array(a), np.array(b), np.array(d)

    print('視窗   預測子   向前     向後     不對稱    p      扣時長後')
    for win in (0.5, 1.0, 2.0):
        v0 = v0_of(win)
        for name, pred in (('r_b', rb), ('k  ', kk)):
            fi, fj, fd = pairs(v0, +1)
            bi, bj, bd = pairs(v0, -1)
            f = sp(pred[fi], v0[fj]); b = sp(pred[bi], v0[bj])
            asym = f - b
            null = []
            for _ in range(2000):
                null.append(sp(pred[fi][G.permutation(fi.size)], v0[fj])
                            - sp(pred[bi][G.permutation(bi.size)], v0[bj]))
            p = float((np.abs(null) >= abs(asym)).mean())
            pf = partial(pred[fi], v0[fj], fd)
            pb = partial(pred[bi], v0[bj], bd)
            print('%4.1f   %s    %+.3f   %+.3f   %+.3f   %.3f   %+.3f'
                  % (win, name, f, b, asym, p, pf - pb))
    print()
    print('判讀：若 k 那一列的不對稱與 r_b 同樣大，就是簡併路徑，非生物。')
    print('      若扣掉時長後不對稱消失，就是循環長度帶動的。')


if __name__ == '__main__':
    main()
