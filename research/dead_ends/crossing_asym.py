# -*- coding: utf-8 -*-
"""速率空間的漸近線估計量：r_b 從「斜率」變成「水平漸近線」。

文獻定位（第五次撞題，一律寫成引用並應用）：
  event-based / send-on-delta sampling   Miskowicz 2006
  level-crossing sampling                Mark and Todd 1981; Sayiner 1996
  time encoding machines                 Lazar and Toth 2004
  grouped-data ML / Sheppard corrections 量化似然那一側

結構上的差別（這才是可能勝過現行估計器的地方）：
  位準空間  P(t) = P_eq + A exp(-kt) - r_b t   四參數，r_b 是埋著的斜率
  速率空間  v(tau) = A k exp(-k tau) + r_b     三參數，r_b 是漸近線
  差分把 P_eq 消掉了，而 P_eq 正是耦合式裡吸收 r_b 的那個參數。

已知偏誤（結果必須照這個順序讀）：
  1 running-min 觸發偏早，但差分後大致抵消
  2 最後一次跨越受端點選擇影響，預設丟棄
  3 一次掉多階時會漏掉中間位準
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dataset_c import collect_c

D = 0.01
KG = np.arange(0.02, 3.001, 0.02)


def crossings(x, y):
    q = np.round(y / D).astype(int)
    rm = np.minimum.accumulate(q)
    i = np.flatnonzero(np.diff(rm) < 0) + 1
    return x[i]


def fit_rate(tau, drop_last=1):
    """對 v = a exp(-k tau) + r_b 做輪廓擬合，回傳 (r_b, k, n)。"""
    if drop_last:
        tau = tau[:-drop_last] if len(tau) > drop_last + 3 else tau
    if len(tau) < 6:
        return None
    dt = np.diff(tau)
    ok = dt > 0
    v = D / dt[ok]
    tm = (0.5 * (tau[1:] + tau[:-1]))[ok]
    tm = tm - tm[0]
    best = None
    for k in KG:
        X = np.column_stack([np.exp(-k * tm), np.ones_like(tm)])
        c, *_ = np.linalg.lstsq(X, v, rcond=None)
        r = float(np.sum((X @ c - v) ** 2))
        if best is None or r < best[0]:
            best = (r, float(c[1]), float(k))
    return best[1], best[2], len(v)


def main():
    out = []
    for tag, x, y in collect_c():
        if len(x) < 120:
            continue
        tau = crossings(x, y)
        if len(tau) < 8:
            continue
        f = fit_rate(tau)
        if f:
            out.append(f)
    rb = np.array([a for a, _, _ in out])
    kk = np.array([b for _, b, _ in out])
    print('可用段 %d' % len(out))
    print('  r_b 中位  %.5f      四分位 %.5f / %.5f'
          % (np.median(rb), *np.percentile(rb, [25, 75])))
    print('  負值比例  %.0f%%' % ((rb < 0).mean() * 100))
    print('  k  中位   %.3f' % np.median(kk))
    g = np.random.default_rng(11)
    bm = np.median(g.choice(rb, size=(6000, rb.size)), axis=1)
    lo, hi = np.percentile(bm, [2.5, 97.5])
    print('  拔靴 95%%  [%.5f, %.5f]' % (lo, hi))
    print()
    print('  現行估計器（位準空間，未修正）0.01283')
    print('  定版（校準後）                0.01256')
    print('  上一版（只讀後段平台）        0.0170')


if __name__ == '__main__':
    main()
