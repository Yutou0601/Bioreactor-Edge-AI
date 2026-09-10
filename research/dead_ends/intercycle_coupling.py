# -*- coding: utf-8 -*-
"""兩件事：設定點檢定的檢定力；以及新特徵「跨循環耦合的時間不對稱」。

新特徵的動機。簡併是**單一循環內**擬合的產物：A、k、r_b 在同一次
最小平方裡交換工作量。它完全不預測「第 i 段的 r_b 會影響第 i+1 段」。
但生物會：菌吃掉溶解的氣體，液體更不飽和，下一段開始時驅動力更大、
初期物理吸收更快。

⚠ 共同趨勢（菌齡、季節）會讓相鄰段一起漂，造成**對稱**的相關。
   生物機制只造成**向前**的因果。所以判準不是相關本身，是
   forward 減 backward 的不對稱。這是這個特徵能否成立的關鍵。
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

CUT = '2026-07-11'
G = np.random.default_rng(23)


def sp(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    rows = [r for r in csv.DictReader(
        open('../docs/analysis_charts_3batch/rb_per_cycle.csv',
             encoding='utf-8-sig')) if r['folder'] not in EXCLUDE]
    cyc = collect_c()
    rb = np.array([float(r['rb']) for r in rows])

    # ── 一、設定點檢定的檢定力 ───────────────────────────
    pre = np.array([v for v, r in zip(rb, rows) if r['time'][:10] < CUT])
    post = np.array([v for v, r in zip(rb, rows) if r['time'][:10] >= CUT])
    d = np.array([np.median(G.choice(post, post.size))
                  - np.median(G.choice(pre, pre.size)) for _ in range(6000)])
    se = float(d.std(ddof=1))
    mde = 2.80 * se                       # 雙尾 alpha=.05、檢定力 .8
    print('== 設定點檢定的檢定力 ==')
    print('  中位差的標準誤 %.5f' % se)
    print('  可偵測的最小跳躍 %.5f  = 變更前中位的 %.0f%%'
          % (mde, mde / np.median(pre) * 100))
    print('  實測跳躍 %.5f（%.0f%%）→ 落在偵測門檻'
          % (np.median(post) - np.median(pre),
             (np.median(post) - np.median(pre)) / np.median(pre) * 100),
          '之下' if abs(np.median(post) - np.median(pre)) < mde else '之上')

    # ── 二、新特徵：跨循環耦合的時間不對稱 ───────────────
    v0 = []
    for tag, x, y in cyc:
        m = x - x[0] <= 1.0               # 前一小時的平均下降速率
        v0.append((y[0] - y[m][-1]) / max(x[m][-1] - x[0], 1e-9)
                  if m.sum() > 5 else np.nan)
    v0 = np.array(v0)
    t = np.array([r['time'] for r in rows], dtype='datetime64[m]')
    fo = np.array([r['folder'] for r in rows])

    fwd_a, fwd_b, bwd_a, bwd_b = [], [], [], []
    for i in range(len(rows) - 1):
        if fo[i] != fo[i + 1] or not np.isfinite(v0[i + 1]):
            continue
        gap = (t[i + 1] - t[i]) / np.timedelta64(1, 'h')
        if not (0 < gap < 60):            # 必須是真的相鄰
            continue
        fwd_a.append(rb[i]); fwd_b.append(v0[i + 1])
    for i in range(1, len(rows)):
        if fo[i] != fo[i - 1] or not np.isfinite(v0[i - 1]):
            continue
        gap = (t[i] - t[i - 1]) / np.timedelta64(1, 'h')
        if not (0 < gap < 60):
            continue
        bwd_a.append(rb[i]); bwd_b.append(v0[i - 1])

    f = sp(np.array(fwd_a), np.array(fwd_b))
    b = sp(np.array(bwd_a), np.array(bwd_b))
    print('\n== 新特徵：跨循環耦合 ==')
    print('  向前 corr(r_b[i], 初速[i+1]) = %+.3f   n=%d' % (f, len(fwd_a)))
    print('  向後 corr(r_b[i], 初速[i-1]) = %+.3f   n=%d' % (b, len(bwd_a)))
    print('  不對稱 前減後 = %+.3f' % (f - b))

    # 置換：把 r_b 在同一批次內洗牌，破壞時間關係
    A, B = np.array(fwd_a), np.array(fwd_b)
    C, Dd = np.array(bwd_a), np.array(bwd_b)
    null = []
    for _ in range(3000):
        p1 = G.permutation(A.size); p2 = G.permutation(C.size)
        null.append(sp(A[p1], B) - sp(C[p2], Dd))
    null = np.array(null)
    p = float((np.abs(null) >= abs(f - b)).mean())
    print('  置換虛無下的不對稱 %.3f ± %.3f   p = %.3f'
          % (null.mean(), null.std(), p))
    print('\n  p 小 → 存在向前的因果不對稱，簡併解釋不了')
    print('  p 大 → 只是共同趨勢，這個特徵沒有用')


if __name__ == '__main__':
    main()
